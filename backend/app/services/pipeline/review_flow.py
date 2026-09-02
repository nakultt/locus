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
from app.services.chat.llm import get_llm

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

# A refactor touching forty files should not produce a forty-line Slack
# message; past a handful the list stops being scannable, which is the point.
_MAX_DELTA_FILES = 8


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
    The author pushed to a pull request someone has already looked at.

    What that means depends on where the review had got to, and all three
    cases send it back to the reviewer:

    **After changes were requested** -- the loop's main step. Round number
    increments: this is the round trip the count exists to measure.

    **After approval** -- the approval no longer describes the code. A reviewer
    approved a diff; the diff has changed. Leaving the state `approved` meant
    the auto-merge sweep, which runs on a timer and re-evaluates the gate
    every minute, would merge commits no human ever saw. That is the one path
    that writes to a default branch with nobody in the loop, so a push has to
    revoke the approval. The round increments here too -- a re-review after
    approval is a genuine extra trip.

    **While awaiting review** -- the reviewer has been asked but has not
    answered. Recorded and reported so they learn the code moved under them,
    but the round does *not* increment: they have not finished round one, and
    counting each push would turn the round number into a commit counter and
    make an ordinary PR look stalled.

    A push to a pull request nobody has ever reviewed still returns None. That
    is ordinary development, and the analysis re-runs on its own without the
    review loop needing to hear about it.

    Returns None when the push does not concern the review loop.
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

    # A merged pull request is terminal. A push to its branch after the merge
    # belongs to whatever comes next, not to a review that is over.
    if review.state == schemas.ReviewState.merged.value:
        return None

    # Never reviewed by anyone: no verdict to invalidate, nobody waiting.
    if review.state == schemas.ReviewState.awaiting_review.value and not any(
        r.outcome in (
            schemas.ReviewOutcome.approved.value,
            schemas.ReviewOutcome.changes_requested.value,
            schemas.ReviewOutcome.review_requested.value,
        )
        for r in review.rounds
    ):
        return None

    was_approved = review.state == schemas.ReviewState.approved.value
    # Only a completed verdict opens a new round. A push arriving while the
    # reviewer is still deciding is part of the round already running.
    opens_new_round = review.state in (
        schemas.ReviewState.changes_requested.value,
        schemas.ReviewState.approved.value,
    )

    if opens_new_round:
        review.round_number += 1

    review.state = schemas.ReviewState.awaiting_review.value
    review.pr_url = pr_url or review.pr_url
    review.pr_title = pr_title or review.pr_title
    review.author = author or review.author

    if was_approved:
        # The approval is gone, so anything it cleared is gone with it. Asks
        # were already cleared when the approval landed.
        logger.info(
            "Push to approved %s#%s revoked the approval; back to review",
            repo, pr_number,
        )

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


def asks_for_qa(
    db: Session,
    owner_id: int,
    repo: str,
    pr_number: int,
) -> list[str]:
    """
    Everything the reviewer asked for on this PR, oldest first.

    Read from `PRReviewRound` rather than `review.pending_asks`, for two
    reasons. The rounds are append-only, so this returns what was asked across
    the whole review and not only the last outstanding round -- a change
    requested in round one and satisfied in round two is still something QA
    should verify. And `record_merged` clears `pending_asks` on the way past,
    which is exactly the moment this is needed.

    Deduped, preserving order: a reviewer restating the same request across
    rounds is one thing to test, not two.
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
        return []

    asks: list[str] = []
    seen: set[str] = set()

    for round_ in sorted(review.rounds, key=lambda r: r.id):
        if round_.outcome != schemas.ReviewOutcome.changes_requested.value:
            continue
        body = (round_.body or "").strip()
        if not body:
            continue
        key = body.lower()
        if key in seen:
            continue
        seen.add(key)
        asks.append(body)

    return asks


def format_review_notification(
    review: models.PRReview,
    outcome: schemas.ReviewOutcome,
    reviewer: str | None,
    asks: list[str],
    expected_reviewers: list[str],
    changed_files: list[dict] | None = None,
    doc_url: str | None = None,
    resubmit_reason: str | None = None,
) -> str:
    """
    Build the Slack message for one review event.

    Args:
        resubmit_reason: Why a resubmission is being reported --
            "approval_revoked" when a push invalidated an approval,
            "updated_during_review" when the diff moved while the reviewer was
            still deciding, or None for the ordinary next round. A revoked
            approval reads very differently from "round 3 is ready", and
            reporting both the same way would bury the one that matters.

    Addressed to whoever the ball is now with: the author on
    changes-requested, the reviewers on a request.

    The written report is linked on the messages that ask someone to read the
    change -- the review request and each resubmission. It is deliberately not
    added to the approval or changes-requested messages: those report a
    verdict someone has already reached, and a link to the analysis they just
    finished reading is noise.
    """
    changed_files = changed_files or []
    pr_ref = f"{review.repo}#{review.pr_number}"
    link = f"<{review.pr_url}|{pr_ref}>" if review.pr_url else pr_ref
    title = f" — {review.pr_title}" if review.pr_title else ""
    who = f"@{reviewer}" if reviewer else "a reviewer"
    report = f"\n:page_facing_up: <{doc_url}|Full analysis>" if doc_url else ""

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
        return f":eyes: Review requested on {link}{title} — {mentions}{report}"

    if outcome is schemas.ReviewOutcome.resubmitted:
        mentions = " ".join(f"@{r}" for r in expected_reviewers) or "reviewers"

        if resubmit_reason == "approval_revoked":
            # Materially different from an ordinary re-review: someone had
            # already said yes, and that yes no longer covers what is there.
            # Auto-merge is held until it is given again, and saying so stops
            # the message reading as noise on a PR the reviewer thought was
            # finished.
            lines = [
                f":warning: New commits on {link}{title} *after approval* — "
                f"the approval no longer covers this code and has been "
                f"withdrawn. {mentions} please take another look."
                f"{report}"
            ]
        elif resubmit_reason == "updated_during_review":
            # They are mid-review; the diff moved under them. Not a new round.
            lines = [
                f":arrows_counterclockwise: {link}{title} was updated while "
                f"you were reviewing it — {mentions}{report}"
            ]
        else:
            lines = [
                f":arrows_counterclockwise: {link}{title} ready for "
                f"round {review.round_number} — {mentions}{report}"
            ]
        # What the reviewer asked for last time, so re-review is "check these
        # two things" rather than "read the whole diff again". This is the
        # expensive re-read in the loop, and it is a person's time.
        if asks:
            lines.append("")
            lines.append("*You asked for:*")
            lines.extend(f"• {ask}" for ask in asks)
        if changed_files:
            shown = changed_files[:_MAX_DELTA_FILES]
            lines.append("")
            lines.append("*Changed since your review:*")
            lines.extend(
                f"• `{f['filename']}` +{f['additions']} −{f['deletions']}"
                for f in shown
            )
            if len(changed_files) > _MAX_DELTA_FILES:
                lines.append(f"• …and {len(changed_files) - _MAX_DELTA_FILES} more")
        return "\n".join(lines)

    return f"Update on {link}{title}"


def format_retry_notice(
    *,
    repo: str,
    pr_number: int,
    pr_url: str | None,
    pr_title: str | None,
    ticket_key: str,
    previous: models.PRReview,
    qa_rejected: bool,
    reviewers: list[str],
    doc_url: str | None = None,
) -> str:
    """
    Announce a pull request that retries work already merged once.

    The reopened-ticket shape: the first attempt merged, QA rejected it, the
    ticket went back to In Progress, and the fix arrives on a fresh branch as
    a new pull request. To the review loop that PR looks new -- different
    branch, different number, no history -- and a reviewer given it without
    context re-reviews from scratch, missing that this exact change already
    failed once and why.

    Names the earlier pull request so the reviewer can read what was wrong
    with it rather than being told there is history and left to find it.
    """
    pr_ref = f"{repo}#{pr_number}"
    link = f"<{pr_url}|{pr_ref}>" if pr_url else pr_ref
    title = f" — {pr_title}" if pr_title else ""
    mentions = " ".join(f"@{r}" for r in reviewers) or "reviewers"
    report = f"\n:page_facing_up: <{doc_url}|Full analysis>" if doc_url else ""

    previous_ref = f"{previous.repo}#{previous.pr_number}"
    previous_link = (
        f"<{previous.pr_url}|{previous_ref}>" if previous.pr_url else previous_ref
    )

    reason = (
        "which QA rejected" if qa_rejected
        else "which merged earlier"
    )

    return (
        f":repeat: {link}{title} is another attempt at *{ticket_key}*, "
        f"previously {previous_link} {reason}. {mentions} — worth reading "
        f"the earlier round before this one.{report}"
    )


def evaluate_merge_gate(
    review: models.PRReview,
    analysis: schemas.PRAnalysisResult | None,
    ci_state: str,
    failing_checks: list[str],
    mergeable: bool | None,
    changed_paths: list[str] | None = None,
    machine_authored: bool = False,
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

    # Confirmed findings are deterministic rule matches, not model opinions.
    # Auto-merging over one would contradict the reason the
    # confirmed/unverified split exists at all.
    #
    # Review findings deliberately do not block at any priority, p1 included.
    # Every priority is a model's judgement about the change, and the people
    # who act on that judgement -- the reviewer and their manager -- already
    # read it: findings are rendered in the PR comment and in the Slack
    # notification whatever the gate decides. Gating on one as well made the
    # approval advisory, since a p1 the reviewer had seen and accepted could
    # not be merged without dismissing it by hand first.
    if analysis is not None and analysis.confirmed_findings:
        blockers.append(
            f"{len(analysis.confirmed_findings)} confirmed security finding(s)"
        )

    # An agent-authored change to what CI runs never auto-merges, at any
    # approval. The driver refuses to produce one -- a workflow edit aborts the
    # attempt on the diff -- so reaching here means it arrived by some other
    # route, and the one thing that must not happen is a machine-written change
    # to the checks that gate machine-written changes landing on the strength
    # of those checks.
    if machine_authored:
        workflow_edits = [
            path for path in (changed_paths or [])
            if ".github/workflows/" in path.lower()
        ]
        if workflow_edits:
            blockers.append(
                "machine-authored change touches CI workflows: "
                + ", ".join(sorted(workflow_edits))
            )

    # True today by construction -- GitHub does not let you approve your own
    # pull request -- and asserted so it cannot regress. An approval by the
    # author is not a review, and autonomous mode makes the author a machine.
    if (
        review.state == schemas.ReviewState.approved.value
        and review.author
        and review.last_reviewer
        and review.author.lower() == review.last_reviewer.lower()
    ):
        blockers.append("the approving reviewer is the pull request author")

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
    thread_ts: str | None = None,
) -> bool:
    """
    Post one review-loop message to Slack.

    Failure is logged and swallowed: a Slack outage must not fail the job and
    lose the recorded review state, which is the part that matters.

    Args:
        thread_ts: Reply inside a thread rather than at channel level. The busy
            reply uses it so an answer lands where the question was asked; the
            review loop leaves it unset, since a review request is a new
            message rather than a reply to one.
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
                json=(
                    {"channel": channel, "text": text, "thread_ts": thread_ts}
                    if thread_ts
                    else {"channel": channel, "text": text}
                ),
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
