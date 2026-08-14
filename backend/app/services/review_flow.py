"""
The senior-dev review loop.

The pipeline already covered "PR opened" and "PR merged". Between them sits the
part that actually takes the time: a senior dev asks for changes, the author
pushes, the senior dev looks again, and that repeats until it is good. GitHub
emits each of those as an isolated event and remembers nothing between them, so
this module accumulates the state.

Three things it deliberately does not do:

**It does not move Jira backwards.** A changes-requested review is a real
backward step in the workflow, but `merge_actions.is_forward_transition` refuses
backward transitions for a good reason -- a misconfigured status must never drag
a team's board into an earlier stage. Rather than carve an exception into that
guard, a changes-requested review notifies and records, and leaves the board
alone. The board follows the merge, not the round trip.

**It does not decide whether the review is correct.** The summarizer turns a
reviewer's prose into a checklist so the author can see what is being asked. It
is advisory; the reviewer's own words are stored verbatim alongside and are
canonical.

**It does not gate on who reviewed.** GitHub does not restrict who may submit a
review, and a configured reviewer list is an expectation, not an ACL. A review
from someone unexpected is recorded like any other, flagged by the fact that
their login is not in the list.
"""

import logging

import httpx
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

# GitHub review states, lowercased, mapped onto our outcomes. GitHub sends
# "dismissed" too, which reverts an earlier verdict rather than adding one.
_REVIEW_STATE_MAP = {
    "approved": schemas.ReviewOutcome.approved,
    "changes_requested": schemas.ReviewOutcome.changes_requested,
    "commented": schemas.ReviewOutcome.commented,
}

# Turning reviewer prose into a checklist. No tools bound: a review body is
# written by anyone who can review the PR, which on a public repo is anyone.
_ASKS_PROMPT = """Read this code review and list what the reviewer is asking the author to change.

Rules:
- One line per distinct requested change. No numbering, no bullets, no preamble.
- Use the reviewer's own terms. Do not invent requirements they did not state.
- Praise, questions, and general remarks are not requested changes. Skip them.
- If nothing concrete is being requested, output exactly: NONE

Review:
{body}"""

# A reviewer can paste a lot. Enough to capture the asks, bounded so one
# enormous review cannot dominate a context window.
_MAX_BODY_CHARS = 6000


def _get_or_create_review(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
) -> models.PRReview:
    """
    Fetch this PR's review row, creating it if the loop starts mid-stream.

    Created on demand rather than at PR-open time because a repo may be
    registered after its PRs are already open, and the first review event we
    see should still be recorded rather than dropped.
    """
    review = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.repo == repo,
            models.PRReview.pr_number == pr_number,
            models.PRReview.owner_id == owner_id,
        )
        .first()
    )

    if review is None:
        review = models.PRReview(
            repo=repo,
            pr_number=pr_number,
            state=schemas.ReviewState.awaiting_review.value,
            round_number=1,
            owner_id=owner_id,
        )
        db.add(review)
        db.flush()

    return review


async def summarize_asks(body: str) -> list[str]:
    """
    Reduce a review body to the changes it requests.

    Returns an empty list when nothing concrete is asked, when the body is
    empty, or when the model is unavailable -- an empty checklist reads as
    "see the review itself", which is safe. A fabricated checklist would not be.
    """
    text = (body or "").strip()
    if not text:
        return []

    try:
        llm = get_llm(temperature=0)
        chain = ChatPromptTemplate.from_template(_ASKS_PROMPT) | llm
        response = await chain.ainvoke({"body": text[:_MAX_BODY_CHARS]})
    except Exception as e:
        logger.warning("Could not summarize review asks: %s", e)
        return []

    content = response.content if isinstance(response.content, str) else str(response.content)
    if content.strip().upper().startswith("NONE"):
        return []

    asks = []
    for line in content.splitlines():
        cleaned = line.strip().lstrip("-*0123456789. ").strip()
        # A model that ignores "no preamble" tends to lead with a sentence
        # ending in a colon; that is not an ask.
        if cleaned and not cleaned.endswith(":"):
            asks.append(cleaned)

    return asks


async def record_review_submitted(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
    review_state: str,
    reviewer: str | None,
    body: str | None,
    head_sha: str | None = None,
    pr_url: str | None = None,
    pr_title: str | None = None,
    author: str | None = None,
) -> models.PRReview | None:
    """
    Apply one submitted review to the loop.

    Args:
        review_state: GitHub's review state -- approved, changes_requested,
            commented, or dismissed.

    Returns:
        The updated review row, or None when the event carries no verdict
        worth recording (a bare "commented" review, or a dismissal).
    """
    outcome = _REVIEW_STATE_MAP.get((review_state or "").strip().lower())

    # A "commented" review is a note, not a verdict: it neither blocks nor
    # clears the merge. Recorded for history, but it does not move the state
    # or open a new round -- doing so would inflate the round count with
    # drive-by remarks and make a converging review look stalled.
    if outcome is None:
        logger.info("Ignoring review state %r on %s#%s", review_state, repo, pr_number)
        return None

    review = _get_or_create_review(db, owner_id, repo, pr_number)

    # Late-arriving identity: fill in what we learn, never overwrite with None.
    review.pr_url = pr_url or review.pr_url
    review.pr_title = pr_title or review.pr_title
    review.author = author or review.author

    db.add(models.PRReviewRound(
        review_id=review.id,
        round_number=review.round_number,
        outcome=outcome.value,
        reviewer=reviewer,
        body=body,
        head_sha=head_sha,
    ))

    if outcome is schemas.ReviewOutcome.commented:
        db.commit()
        db.refresh(review)
        return review

    review.last_reviewer = reviewer or review.last_reviewer

    if outcome is schemas.ReviewOutcome.approved:
        review.state = schemas.ReviewState.approved.value
        # Approval clears the outstanding asks; leaving them would show a
        # merge-ready PR with a list of unfinished work against it.
        review.pending_asks = None
    else:
        review.state = schemas.ReviewState.changes_requested.value
        asks = await summarize_asks(body or "")
        review.pending_asks = "\n".join(asks) if asks else None

    db.commit()
    db.refresh(review)
    return review


def record_review_requested(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
    reviewer: str | None,
    pr_url: str | None = None,
    pr_title: str | None = None,
    author: str | None = None,
) -> models.PRReview:
    """
    Record that a review was requested from someone.

    Does not reset an approval. Requesting a second opinion on an already
    approved PR is normal, and silently un-approving it would be a surprising
    side effect of asking.
    """
    review = _get_or_create_review(db, owner_id, repo, pr_number)

    review.pr_url = pr_url or review.pr_url
    review.pr_title = pr_title or review.pr_title
    review.author = author or review.author

    db.add(models.PRReviewRound(
        review_id=review.id,
        round_number=review.round_number,
        outcome=schemas.ReviewOutcome.review_requested.value,
        reviewer=reviewer,
        body=None,
    ))

    if review.state == schemas.ReviewState.changes_requested.value:
        review.state = schemas.ReviewState.awaiting_review.value

    db.commit()
    db.refresh(review)
    return review


def record_resubmission(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
    head_sha: str | None = None,
    pr_url: str | None = None,
    pr_title: str | None = None,
    author: str | None = None,
) -> models.PRReview | None:
    """
    The author pushed after changes were requested: open the next round.

    This is the step that makes the loop a loop. Only a push that follows a
    changes-requested review counts -- a push to a PR nobody has reviewed yet
    is just development, and counting it would make round numbers meaningless.

    Returns None when the push does not advance a round.
    """
    review = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.repo == repo,
            models.PRReview.pr_number == pr_number,
            models.PRReview.owner_id == owner_id,
        )
        .first()
    )

    if review is None or review.state != schemas.ReviewState.changes_requested.value:
        return None

    review.round_number += 1
    review.state = schemas.ReviewState.awaiting_review.value
    review.pr_url = pr_url or review.pr_url
    review.pr_title = pr_title or review.pr_title
    review.author = author or review.author

    db.add(models.PRReviewRound(
        review_id=review.id,
        round_number=review.round_number,
        outcome=schemas.ReviewOutcome.resubmitted.value,
        reviewer=None,
        body=None,
        head_sha=head_sha,
    ))

    db.commit()
    db.refresh(review)
    return review


def record_merged(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
) -> models.PRReview | None:
    """
    Close the loop when the PR merges.

    Terminal: the QA cycle takes over from here, and a merged PR should not
    reappear in a review queue. Returns None if the PR was never reviewed --
    a merge without a review is a fact worth not inventing a record for.
    """
    review = (
        db.query(models.PRReview)
        .filter(
            models.PRReview.repo == repo,
            models.PRReview.pr_number == pr_number,
            models.PRReview.owner_id == owner_id,
        )
        .first()
    )

    if review is None:
        return None

    review.state = schemas.ReviewState.merged.value
    review.pending_asks = None
    db.commit()
    db.refresh(review)
    return review


def format_review_notification(
    review: models.PRReview,
    outcome: schemas.ReviewOutcome,
    reviewer: str | None,
    asks: list[str],
    expected_reviewers: list[str],
) -> str:
    """
    Build the Slack message for one review event.

    Addressed to whoever the ball is now with: the author on
    changes-requested, the reviewers on a request.
    """
    pr_ref = f"{review.repo}#{review.pr_number}"
    link = f"<{review.pr_url}|{pr_ref}>" if review.pr_url else pr_ref
    title = f" — {review.pr_title}" if review.pr_title else ""
    who = f"@{reviewer}" if reviewer else "a reviewer"

    if outcome is schemas.ReviewOutcome.approved:
        return f":white_check_mark: {who} approved {link}{title} — ready to merge."

    if outcome is schemas.ReviewOutcome.changes_requested:
        author = f"@{review.author}" if review.author else "the author"
        lines = [
            f":pencil: {who} requested changes on {link}{title} "
            f"(round {review.round_number}) — over to {author}."
        ]
        if asks:
            lines.append("")
            lines.extend(f"• {ask}" for ask in asks)
        return "\n".join(lines)

    if outcome is schemas.ReviewOutcome.review_requested:
        mentions = " ".join(f"@{r}" for r in expected_reviewers) or "reviewers"
        return f":eyes: Review requested on {link}{title} — {mentions}"

    if outcome is schemas.ReviewOutcome.resubmitted:
        mentions = " ".join(f"@{r}" for r in expected_reviewers) or "reviewers"
        return (
            f":arrows_counterclockwise: {link}{title} updated and ready for "
            f"round {review.round_number} — {mentions}"
        )

    return f"Update on {link}{title}"


def evaluate_merge_gate(
    review: models.PRReview,
    analysis: schemas.PRAnalysisResult | None,
    ci_state: str,
    failing_checks: list[str],
    mergeable: bool | None,
) -> tuple[bool, list[str]]:
    """
    Decide whether an approved PR may be merged automatically.

    Approval is necessary but not sufficient. A human clicking approve is
    saying "the change is right", not "every check passed" -- they may not
    have looked, and on a fast-moving PR the checks may not have finished when
    they clicked. Auto-merge is the one place Locus writes to a repo's default
    branch without a human in the loop, so each of these is checked
    independently of the approval.

    Returns:
        (allowed, blockers). `blockers` is empty when allowed, and is written
        to be read by a human in Slack -- these get reported, never swallowed.
    """
    blockers: list[str] = []

    if review.state != schemas.ReviewState.approved.value:
        blockers.append(f"not approved (state is {review.state})")

    if ci_state == "failure":
        blockers.append(f"CI failing: {', '.join(failing_checks)}")
    elif ci_state == "pending":
        blockers.append("CI has not finished")

    # GitHub reports None while it recomputes mergeability, which is a
    # genuinely unknown answer -- treated as "not now" rather than assumed
    # either way. The next event re-evaluates.
    if mergeable is False:
        blockers.append("merge conflict with the base branch")
    elif mergeable is None:
        blockers.append("GitHub has not computed mergeability yet")

    if analysis is not None:
        # Confirmed findings are deterministic rule matches, not model
        # opinions. Auto-merging over one would contradict the reason the
        # confirmed/unverified split exists at all.
        if analysis.confirmed_findings:
            blockers.append(
                f"{len(analysis.confirmed_findings)} confirmed security "
                f"finding(s)"
            )

        # p1 means "do not merge this" by definition. Unverified findings and
        # p2/p3 do not block: they are advisory, and blocking on a model's
        # opinion would make auto-merge unusable.
        p1s = [
            f for f in analysis.review_findings
            if f.priority == schemas.ReviewPriority.p1
        ]
        if p1s:
            blockers.append(f"{len(p1s)} P1 review finding(s)")

    return (not blockers), blockers


def format_merge_gate(gate: schemas.MergeGateResult) -> str:
    """
    One line saying what auto-merge did, or why it held.

    Always says something. An approved PR that quietly stays open reads as the
    feature being broken, which costs more trust than a noisy channel.
    """
    if gate.merged:
        return ":rocket: Auto-merged. Post-merge actions are running."

    if gate.attempted:
        return f":warning: Auto-merge failed — {gate.detail}"

    reasons = "; ".join(gate.blockers) or "gate not satisfied"
    return f":hourglass: Not auto-merged — {reasons}"


async def post_review_notification(
    slack_config: dict,
    channel: str,
    text: str,
) -> bool:
    """
    Post one review-loop message to Slack.

    Failure is logged and swallowed: a Slack outage must not fail the job and
    lose the recorded review state, which is the part that matters.
    """
    credentials = slack_config.get("credentials", {}) or {}
    bot_token = credentials.get("bot_token") or slack_config.get("api_key", "")
    if not bot_token:
        return False

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel, "text": text},
            )
            payload = response.json()
    except Exception as e:
        logger.warning("Review notification failed: %s", e)
        return False

    if not payload.get("ok"):
        logger.warning("Review notification rejected: %s", payload.get("error"))
        return False

    return True


def to_detail(review: models.PRReview) -> schemas.PRReviewDetail:
    """Serialize a review row and its history for the API."""
    return schemas.PRReviewDetail(
        id=review.id,
        repo=review.repo,
        pr_number=review.pr_number,
        pr_url=review.pr_url,
        pr_title=review.pr_title,
        author=review.author,
        state=schemas.ReviewState(review.state),
        round_number=review.round_number,
        last_reviewer=review.last_reviewer,
        updated_at=review.updated_at or review.created_at,
        pending_asks=[
            line.strip()
            for line in (review.pending_asks or "").splitlines()
            if line.strip()
        ],
        rounds=[
            schemas.ReviewRound(
                round_number=r.round_number,
                outcome=schemas.ReviewOutcome(r.outcome),
                reviewer=r.reviewer,
                body=r.body,
                head_sha=r.head_sha,
                created_at=r.created_at,
            )
            for r in review.rounds
        ],
    )
