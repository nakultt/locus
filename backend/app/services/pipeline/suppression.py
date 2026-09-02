"""
Dismissing a finding, and the `@locus` commands that do it.

A false positive is otherwise permanent. The scan re-runs on every push, the
finding comes back, and the only way to silence it is to stop reading the
comment -- which silences the true positives too. That is exactly the loss of
trust the confirmed/unverified split exists to prevent, reached from the other
side.

**The command text is untrusted.** Anyone who can comment on a pull request can
write one, which on a public repo is anyone. Parsing is therefore a plain
regex over a fixed vocabulary -- no model is involved in deciding what a
comment asks for, so there is nothing to talk into a wider action than the
words allow. The only thing a comment can do is suppress a finding on the pull
request it was posted on, or explain one. Neither reaches another repository,
another user's data, or any outward channel.

**Matching is by file and title, never line.** Same reason as `finding_diff`:
an edit above a finding shifts it, and a line-keyed suppression would lapse
the next time anyone touched the file -- silently, which is the worst way for
a dismissal to expire.
"""

import logging
import re

from sqlalchemy.orm import Session

from app import models, schemas

logger = logging.getLogger(__name__)

# Commands are matched case-insensitively at the start of a line, so a mention
# quoted inside a longer discussion does not fire.
_COMMAND = re.compile(
    r"^\s*@locus\s+(?P<verb>ignore|dismiss|explain)\s+(?P<target>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# `@locus ignore <title> -- reason`. The reason is optional and free text; it
# is stored for the audit trail and never interpreted.
_REASON = re.compile(r"\s+(?:--|—|because)\s+(?P<reason>.+)$", re.IGNORECASE)

_SUPPRESS_VERBS = {"ignore", "dismiss"}


def normalise(value: str) -> str:
    """Collapse whitespace and case, so matching is plain equality."""
    return " ".join((value or "").split()).lower()


class Command:
    """One parsed `@locus` instruction."""

    def __init__(self, verb: str, target: str, reason: str | None = None):
        self.verb = verb.lower()
        self.target = target
        self.reason = reason

    @property
    def suppresses(self) -> bool:
        return self.verb in _SUPPRESS_VERBS

    def __repr__(self) -> str:
        return f"<Command {self.verb} {self.target!r}>"


def parse_commands(body: str) -> list[Command]:
    """
    Pull `@locus` instructions out of a comment body.

    Returns an empty list for ordinary comments, which is almost all of them.
    A body mentioning @locus without a recognised verb is deliberately not an
    error: people talk about the bot, and replying "unknown command" to every
    such mention would be its own kind of noise.
    """
    commands: list[Command] = []

    for match in _COMMAND.finditer(body or ""):
        target = match.group("target").strip()
        reason = None

        reason_match = _REASON.search(target)
        if reason_match:
            reason = reason_match.group("reason").strip()
            target = target[: reason_match.start()].strip()

        # Strip surrounding quotes or backticks people naturally add.
        target = target.strip("\"'`").strip()
        if target:
            commands.append(Command(match.group("verb"), target, reason))

    return commands


def suppress(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int | None,
    file_path: str,
    title: str,
    scope: str = "pr",
    suppressed_by: str | None = None,
    reason: str | None = None,
) -> models.SuppressedFinding:
    """
    Record that a finding should not be reported again.

    Idempotent: dismissing the same finding twice updates the existing row
    rather than stacking duplicates, so a reviewer repeating themselves does
    not corrupt the audit trail.
    """
    normalised_title = normalise(title)
    normalised_path = normalise(file_path)

    existing = (
        db.query(models.SuppressedFinding)
        .filter(
            models.SuppressedFinding.owner_id == owner_id,
            models.SuppressedFinding.repo == repo,
            models.SuppressedFinding.pr_number == pr_number,
            models.SuppressedFinding.file_path == normalised_path,
            models.SuppressedFinding.title == normalised_title,
        )
        .first()
    )

    if existing is not None:
        existing.reason = reason or existing.reason
        existing.suppressed_by = suppressed_by or existing.suppressed_by
        db.commit()
        return existing

    row = models.SuppressedFinding(
        owner_id=owner_id,
        repo=repo,
        pr_number=pr_number,
        file_path=normalised_path,
        title=normalised_title,
        scope=scope,
        suppressed_by=suppressed_by,
        reason=reason,
    )
    db.add(row)
    db.commit()
    return row


def active_for(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
) -> set[tuple[str, str]]:
    """
    Every suppression that applies to this pull request.

    Includes both the ones dismissed on this PR and any repo-wide ones.

    Returns:
        Set of (normalised file_path, normalised title).
    """
    rows = (
        db.query(models.SuppressedFinding)
        .filter(
            models.SuppressedFinding.owner_id == owner_id,
            models.SuppressedFinding.repo == repo,
        )
        .all()
    )

    return {
        (row.file_path, row.title)
        for row in rows
        if row.pr_number is None or row.pr_number == pr_number
    }


def apply(
    result: schemas.PRAnalysisResult,
    suppressed: set[tuple[str, str]],
) -> int:
    """
    Remove dismissed findings from an analysis, in place.

    Applied to the result rather than at scan time so the scanners stay
    unaware of it: a suppression is a reporting decision, and a scanner whose
    output depends on who dismissed what is much harder to reason about.

    Matching a title exactly is deliberate. A fuzzy match would let one
    dismissal silence findings nobody looked at, which is the failure mode
    that makes suppression worse than no suppression.

    Returns:
        How many findings were withheld.
    """
    if not suppressed:
        return 0

    def keep(finding) -> bool:
        return (
            normalise(finding.file_path),
            normalise(finding.title),
        ) not in suppressed

    withheld = 0
    for attribute in (
        "confirmed_findings",
        "unverified_findings",
        "review_findings",
    ):
        findings = getattr(result, attribute)
        kept = [f for f in findings if keep(f)]
        withheld += len(findings) - len(kept)
        setattr(result, attribute, kept)

    return withheld


def match_finding(
    result: schemas.PRAnalysisResult,
    target: str,
) -> tuple[str, str] | None:
    """
    Find the finding a command refers to.

    People do not retype a title exactly, so a target that is contained in a
    title counts as a match. Ambiguity resolves to nothing rather than to a
    guess: silencing the wrong finding is invisible, and the reply says which
    titles matched so the author can be more specific.

    Returns:
        (file_path, title) of the single match, or None.
    """
    needle = normalise(target)
    if not needle:
        return None

    matches: list[tuple[str, str]] = []
    for attribute in (
        "confirmed_findings",
        "unverified_findings",
        "review_findings",
    ):
        for finding in getattr(result, attribute):
            title = normalise(finding.title)
            if needle == title or needle in title:
                matches.append((finding.file_path, finding.title))

    return matches[0] if len(matches) == 1 else None
