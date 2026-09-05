"""
The accumulated context for one piece of work, as a single document.

Every model call used to receive context gathered fresh and scattered across
several arguments. This assembles what is already stored -- the message log,
the review history, the current findings -- into one ordered narrative.

**Rendered on demand, never stored.** The obvious alternative is to keep a
markdown file per task and update it as things arrive, but a file has no
transactions, and three things already write per-PR state concurrently: the
job worker, the Gmail poller, and the auto-merge sweeper. It is also not
queryable, and it breaks under the multi-instance deployment this needs
anyway. Rendering from the tables keeps one source of truth and costs nothing
to keep correct.

The useful consequence of rendering rather than storing: the *volatile* half
of the context is automatically current and the *stable* half is automatically
whatever the log holds, with no cache logic in this module at all. Caching
belongs to the gathering step; this only reads.
"""

import logging

from sqlalchemy.orm import Session

from app import models, schemas
from app.services.pipeline import comms_log

logger = logging.getLogger(__name__)

# Per section, so one noisy PR cannot produce a brief that will not fit a
# context window. Slack discussion is the section that runs long.
MAX_ITEMS_PER_SECTION = 12
MAX_QUOTE_CHARS = 600


def _quote(text: str | None) -> str:
    """One message, trimmed and indented as a markdown blockquote."""
    body = (text or "").strip()
    if not body:
        return ""
    if len(body) > MAX_QUOTE_CHARS:
        body = body[:MAX_QUOTE_CHARS].rstrip() + "…"
    return "\n".join(f"  > {line}" for line in body.splitlines())


def build(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
    analysis: schemas.PRAnalysisResult | None = None,
) -> str:
    """
    Assemble the brief for one pull request.

    Args:
        ticket_key: When given, discussion and issue context is drawn from the
            whole work item rather than this pull request alone -- so the
            second PR on a ticket opens with the first one's history, including
            the QA rejection that caused it to exist.
        analysis: The *current* run's findings. Passed in rather than read from
            storage because findings are derived from the diff, and the diff
            is what changed. Reading a stored result here would be exactly the
            mistake this design exists to avoid.

    Returns:
        Markdown. Empty sections are omitted rather than rendered as "none",
        so absence is visible as absence.
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

    # Ticket-scoped when we know the ticket, PR-scoped otherwise.
    if ticket_key:
        events = comms_log.ticket_timeline(
            db, owner_id=owner_id, ticket_key=ticket_key
        )
    else:
        events = comms_log.timeline(
            db, owner_id=owner_id, repo=repo, pr_number=pr_number
        )

    lines: list[str] = []

    title = (review.pr_title if review else None) or f"{repo}#{pr_number}"
    lines.append(f"# {repo}#{pr_number} — {title}")

    state_bits = []
    if review:
        state_bits.append(f"round {review.round_number}")
        state_bits.append(review.state.replace("_", " "))
        if review.author:
            state_bits.append(f"opened by {review.author}")
    if ticket_key:
        state_bits.append(f"task {ticket_key}")
    if state_bits:
        lines.append(" · ".join(state_bits))

    # --- Requirement: what this work is supposed to do -------------------
    tickets = analysis.context.tickets if analysis else []
    issues = [
        e for e in events
        if e.channel == "github" and e.direction == "received"
        and e.outcome in ("closes", "mentions")
    ]

    if tickets or issues:
        lines.append("\n## Requirement")
        for ticket in tickets[:MAX_ITEMS_PER_SECTION]:
            status = f" ({ticket.status})" if ticket.status else ""
            lines.append(f"- {ticket.key}{status}: {ticket.summary or '—'}")
        for issue in issues[:MAX_ITEMS_PER_SECTION]:
            who = f" by {issue.participant}" if issue.participant else ""
            lines.append(f"- {issue.target} {issue.outcome}{who}: {issue.subject or '—'}")
            quoted = _quote(issue.body)
            if quoted:
                lines.append(quoted)

    # --- Prior discussion -------------------------------------------------
    from app.services.pipeline.review_flow import is_own_slack_notification

    discussion = [
        e for e in events
        if e.channel == "slack" and e.direction == "received"
        and e.loop == "context"
        # Not discussion: Locus's own review pings, QA briefs and merge
        # announcements, which the user-token search returns from the channel
        # it posts them into. Filtered here as well as in `cached_search`
        # because this reads the timeline directly, and every consumer of this
        # brief is a model -- the authoring driver and the code reviewer.
        and not is_own_slack_notification(e.body)
    ]
    if discussion:
        lines.append("\n## Prior discussion")
        for event in discussion[:MAX_ITEMS_PER_SECTION]:
            where = f"#{event.target}" if event.target else "slack"
            who = event.participant or "someone"
            lines.append(f"- {where}, {who}:")
            quoted = _quote(event.body)
            if quoted:
                lines.append(quoted)

    # --- Review history: what humans asked for, in their words -----------
    if review and review.rounds:
        from app.services.pipeline.review_flow import is_bot_or_internal_comment

        lines.append("\n## Review history")
        for round_ in review.rounds:
            if is_bot_or_internal_comment(round_.reviewer, round_.body):
                continue
            if round_.outcome == schemas.ReviewOutcome.resubmitted.value:
                lines.append(f"- Round {round_.round_number}: author pushed changes")
                continue
            who = round_.reviewer or "a reviewer"
            label = round_.outcome.replace("_", " ")
            lines.append(f"- Round {round_.round_number}: {who} — {label}")
            quoted = _quote(round_.body)
            if quoted:
                lines.append(quoted)

    # --- Testing ----------------------------------------------------------
    qa = [e for e in events if e.loop == "qa" and e.direction == "received"]
    if qa:
        lines.append("\n## Testing feedback")
        for event in qa[:MAX_ITEMS_PER_SECTION]:
            who = event.participant or "a tester"
            verdict = f" [{event.outcome}]" if event.outcome else ""
            lines.append(f"- {who}{verdict}:")
            quoted = _quote(event.body)
            if quoted:
                lines.append(quoted)

    # --- Outstanding ------------------------------------------------------
    from app.services.pipeline.review_flow import is_bot_or_internal_comment

    asks = [
        line.strip()
        for line in ((review.pending_asks if review else None) or "").splitlines()
        if line.strip() and not is_bot_or_internal_comment(None, line)
    ]
    if asks:
        lines.append("\n## Outstanding asks")
        lines.extend(f"- {ask}" for ask in asks)

    # --- Findings: always this run's, never a stored one -------------------
    if analysis and (analysis.confirmed_findings or analysis.review_findings):
        lines.append("\n## Current findings")
        for finding in analysis.confirmed_findings[:MAX_ITEMS_PER_SECTION]:
            lines.append(
                f"- CONFIRMED {finding.severity.value}: {finding.title} "
                f"({finding.file_path})"
            )
        for finding in analysis.review_findings[:MAX_ITEMS_PER_SECTION]:
            lines.append(
                f"- {finding.priority.value.upper()}: {finding.title} "
                f"({finding.file_path})"
            )

    return "\n".join(lines).strip()


def requirement_context(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    ticket_key: str | None = None,
) -> str:
    """
    Just the stable half: requirement, discussion, and what reviewers asked.

    This is what `run_code_review` needs -- "does this change do what the team
    agreed" -- and it deliberately excludes findings, which are derived from
    the very diff being reviewed. Feeding a reviewer its own previous output
    invites it to agree with itself.
    """
    full = build(
        db, owner_id=owner_id, repo=repo, pr_number=pr_number,
        ticket_key=ticket_key, analysis=None,
    )
    # `build` with analysis=None already omits the findings section; this
    # wrapper exists to make the intent explicit at the call site rather than
    # relying on a caller remembering to pass None.
    return full
