"""
What changed between one analysis round and the next.

The review loop already counts rounds, and every run stores its findings on the
job. Nothing joined the two, so the question a reviewer actually asks on round
three -- "did they fix what I flagged in round two?" -- had no answer in the
tool. They had to diff two comments by eye.

**Identity is the file and the title, never the line number.** A finding moves
down the file the moment anyone inserts a line above it, so keying on the line
would report every surviving finding as "resolved, and here is a new one just
like it". Titles come from a model at temperature 0 and are stable in practice
for an unchanged problem; the file path anchors them so the same title in two
files stays two findings. Normalised for case and whitespace, because a model
that rewords capitalisation between runs should not read as a new defect.

**Resolved means "was there, is not now", which is not the same as "fixed".**
Deleting the file resolves a finding. So does a reviewer's change that moves
the problem somewhere the scanner cannot see it. The wording in the comment
says "no longer reported" rather than "fixed" for exactly that reason -- the
tool knows what it stopped seeing, not what someone did about it.

Only compared against the previous *completed* run on the same pull request.
Comparing across pull requests would report a colleague's findings as yours.
"""

import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models, schemas

logger = logging.getLogger(__name__)


def _identity(file_path: str, title: str) -> tuple[str, str]:
    """
    A finding's identity across rounds.

    Deliberately excludes the line number: an edit anywhere above a finding
    shifts it, and a shifted finding is the same finding.
    """
    return (
        (file_path or "").strip().lower(),
        " ".join((title or "").split()).lower(),
    )


@dataclass
class FindingDelta:
    """How this round's findings compare with the previous round's."""

    resolved: list[str] = field(default_factory=list)
    persisting: list[str] = field(default_factory=list)
    introduced: list[str] = field(default_factory=list)
    # False when there is no previous run to compare against, which is the
    # first analysis of a pull request. A delta of "everything is new" on a
    # first run is noise, so the caller renders nothing.
    has_baseline: bool = False

    @property
    def is_empty(self) -> bool:
        return not (self.resolved or self.persisting or self.introduced)


def _all_titles(payload: dict) -> dict[tuple[str, str], str]:
    """
    Every finding in a stored result, by identity.

    Security and review findings share one namespace here. A reviewer reading
    "2 no longer reported" does not care which pass produced them, and keeping
    them apart would mean three sets of counters for no gain.
    """
    found: dict[tuple[str, str], str] = {}

    for key in ("confirmed_findings", "unverified_findings", "review_findings"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            path = str(item.get("file_path") or "").strip()
            if not title:
                continue
            label = f"{path}: {title}" if path else title
            found[_identity(path, title)] = label

    return found


def previous_result(
    db: Session,
    *,
    owner_id: int,
    repo: str,
    pr_number: int,
    before_job_id: int | None = None,
) -> dict | None:
    """
    The stored findings from the last completed run on this pull request.

    `before_job_id` excludes the run being processed now, which has usually
    already been written by the time this is called.
    """
    query = db.query(models.PRJob).filter(
        models.PRJob.owner_id == owner_id,
        models.PRJob.repo == repo,
        models.PRJob.pr_number == pr_number,
        models.PRJob.status == schemas.PRJobStatus.completed.value,
        models.PRJob.result_json.isnot(None),
    )
    if before_job_id is not None:
        query = query.filter(models.PRJob.id != before_job_id)

    previous = query.order_by(models.PRJob.created_at.desc()).first()
    if previous is None:
        return None

    try:
        payload = json.loads(previous.result_json)
    except (json.JSONDecodeError, TypeError):
        # A result stored under an older schema is not a reason to fail the
        # run it was only meant to annotate.
        return None

    return payload if isinstance(payload, dict) else None


def compare(
    current: schemas.PRAnalysisResult,
    previous: dict | None,
) -> FindingDelta:
    """
    Diff this run's findings against the previous run's.

    Returns a delta with `has_baseline` False when there is nothing to compare
    against, so a first analysis does not report its entire finding list as
    newly introduced.
    """
    if previous is None:
        return FindingDelta(has_baseline=False)

    before = _all_titles(previous)
    now = _all_titles(json.loads(current.model_dump_json()))

    return FindingDelta(
        resolved=sorted(
            label for key, label in before.items() if key not in now
        ),
        persisting=sorted(
            label for key, label in now.items() if key in before
        ),
        introduced=sorted(
            label for key, label in now.items() if key not in before
        ),
        has_baseline=True,
    )


# How many findings to name before collapsing to a count. Past a handful the
# list stops being scannable, which is the only reason to render it.
_MAX_NAMED = 5


def render(delta: FindingDelta) -> str:
    """
    The delta as a PR comment section.

    Renders nothing on a first run, and nothing when there is no movement --
    a "0 resolved, 0 new" line on every push is noise that trains people to
    skip the section that matters.

    Says "no longer reported" rather than "fixed". The tool knows what it
    stopped seeing; whether someone fixed it, deleted the file, or moved it
    somewhere the scanner cannot look is not visible from here.
    """
    if not delta.has_baseline or delta.is_empty:
        return ""

    lines = ["### Since the last run", ""]

    def bullets(items: list[str], label: str, icon: str) -> None:
        if not items:
            return
        lines.append(f"- {icon} **{len(items)} {label}**")
        for item in items[:_MAX_NAMED]:
            lines.append(f"  - {item}")
        if len(items) > _MAX_NAMED:
            lines.append(f"  - …and {len(items) - _MAX_NAMED} more")

    bullets(delta.resolved, "no longer reported", "✅")
    bullets(delta.introduced, "new", "🆕")

    # Persisting findings are counted, not listed: they are already rendered
    # in full in the sections below, and repeating them here would double the
    # length of the comment to say nothing new.
    if delta.persisting:
        lines.append(f"- ↔️ **{len(delta.persisting)} still open**")

    lines.append("")
    return "\n".join(lines)
