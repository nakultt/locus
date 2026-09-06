"""
Effective PR agent settings.

Every setting exists in two places: on the repo registration, and on the
account-wide defaults. This module is the single place that decides which one
wins, so the worker, the API and the UI preview cannot disagree about what a
run will actually do.

The rule is "a repo that says something wins; otherwise fall back". A repo
value that is blank or unset is treated as *not saying anything*, which is what
lets an unregistered repo still export to Docs and email QA.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import models


@dataclass
class EffectiveSettings:
    """What a run will actually do, and where each value came from."""

    slack_channel: str | None = None
    export_to_docs: bool = False
    qa_emails: list[str] = field(default_factory=list)
    jira_done_status: str = "Done"
    close_issues_on_merge: bool = True
    # Hold the work item open until QA signs off, rather than closing at merge.
    close_on_qa_signoff: bool = False
    context_doc_ids: list[str] = field(default_factory=list)
    # GitHub logins expected to review this repo.
    reviewers: list[str] = field(default_factory=list)
    # login -> {"slack": ..., "email": ...}. Empty when nobody configured
    # contacts, which is fine: the loop still works, the UI just cannot say
    # where a given reviewer was reached.
    reviewer_contacts: dict[str, dict[str, str]] = field(default_factory=dict)
    # Where review-loop notifications go. Falls back to slack_channel only if
    # explicitly unset, so a team can keep review pings out of the summary feed.
    review_slack_channel: str | None = None
    auto_merge_on_approval: bool = False
    merge_method: str = "squash"
    # Move the issue's GitHub Projects card as the pipeline advances.
    project_board_sync: bool = True
    # Stage -> column name. Empty means project_board's default map; a stage
    # absent from a non-empty map deliberately moves no card.
    project_column_map: dict[str, str] = field(default_factory=dict)

    # Who writes the code: "assisted" (a person) or "autonomous" (the
    # authoring driver). Assisted is the final fallback everywhere -- a mode
    # that opens pull requests on its own is never inherited by accident.
    authoring_mode: str = "assisted"
    # The first attempt plus this many reworks.
    autonomous_max_rounds: int = 2
    # Display only; the UI compares the saved dials against the preset to
    # render "Assisted (modified)".
    preset_label: str | None = None
    # Where this repo is checked out locally. None falls back to
    # LOCUS_CODE_ROOT, and failing that to a managed clone.
    source_path: str | None = None
    # Run once in the fresh worktree before the agent runs.
    prepare_command: str | None = None
    # The authoring test gate. None means no gate.
    test_command: str | None = None
    # True when a WorkItemSettings row carries handed_back_at. The mode reads
    # `assisted` either way; this is what lets the UI say *why*, and what the
    # bound checks so the next event does not re-trigger the driver.
    handed_back: bool = False
    handed_back_reason: str | None = None

    # What starts the agent, as opposed to whether it may write at all.
    # Account-level only, so these resolve from the defaults row and nothing
    # else -- a repo has no say, because the question is one policy for the
    # account. `authoring_mode` remains the per-repo and per-item switch, and
    # is checked *as well*: auto-start on an item nobody put in autonomous mode
    # must still do nothing.
    #
    # Review and QA default True because both fired automatically before they
    # were settings; assignment defaults False because it is new and can open
    # a pull request per assigned ticket in one sweep.
    auto_start_on_assignment: bool = False
    auto_start_on_review: bool = True
    auto_start_on_qa: bool = True

    # Per key: "repo", "defaults", or "unset". The dashboard shows this so a
    # skipped stage can be traced to the setting responsible.
    sources: dict[str, str] = field(default_factory=dict)


def _lines(value: str | None) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def parse_contacts(value: str | None) -> dict[str, dict[str, str]]:
    """
    Parse reviewer contacts, one per line:

        github-login, @slack-handle, someone@company.com

    Slack and email are both optional and order-independent -- an entry is
    recognised as an address by the "@" plus a dot, and as a Slack handle
    otherwise. Getting this wrong is cheap (the UI shows the wrong label) and
    demanding a strict field order is not, since this is typed by hand.
    """
    contacts: dict[str, dict[str, str]] = {}

    for line in _lines(value):
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue

        login = parts[0].lstrip("@")
        entry: dict[str, str] = {}

        for part in parts[1:]:
            if "@" in part and "." in part.split("@")[-1]:
                entry["email"] = part
            else:
                entry["slack"] = part if part.startswith("@") else f"@{part}"

        contacts[login] = entry

    return contacts


def parse_column_map(value: str | None) -> dict[str, str]:
    """
    Parse a stage-to-column map, one entry per line:

        in_review: In review
        done: Done

    A column name may contain anything a person can type into GitHub, so the
    split is on the first colon only. Unknown stage names are kept rather than
    rejected: `project_board.resolve_column` looks up by stage, so a typo
    simply never matches, and silently dropping it here would hide the typo
    from anyone reading the setting back.
    """
    mapping: dict[str, str] = {}

    for line in _lines(value):
        stage, separator, column = line.partition(":")
        if not separator:
            continue
        stage = stage.strip()
        column = column.strip()
        if stage and column:
            mapping[stage] = column

    return mapping


VALID_AUTHORING_MODES = ("assisted", "autonomous")


def normalize_mode(value: str | None) -> str | None:
    """
    Coerce a stored or submitted mode string to one this code understands.

    An unrecognised value degrades to `assisted` rather than raising: a bad
    value should fall to the safe behaviour, not block a save or fail a run.
    None is preserved, because None is how a repo row says nothing.
    """
    if value is None:
        return None
    cleaned = str(value).strip().lower()
    if not cleaned:
        return None
    return cleaned if cleaned in VALID_AUTHORING_MODES else "assisted"


class SettingsPrefetch:
    """
    Every row a resolve would read for one board, loaded once up front.

    Resolution still happens in `resolve_settings` and nowhere else -- this
    supplies the same rows it would have fetched, it does not decide anything.
    That distinction is the whole design: a cache that answered questions
    would be a second arbiter, and two arbiters drift.

    It exists because the account defaults row is *one row* and the board was
    reading it once per card, along with a registration and a work-item row
    each. Twenty-four round trips to read three rows and two lookups was free
    against a local database and is a second and a half against a hosted one.

    Scoped to a single build and thrown away with it. Nothing is held between
    requests, so a setting saved now is read on the next board -- a cache that
    outlived the request would show a saved setting as not having saved, which
    is the failure this module is most careful about elsewhere.

    Scoping to `owner_id` is not an optimisation detail: `resolve_settings`
    turns a registration into `source_path`, `prepare_command` and
    `test_command`, so a borrowed row runs another account's shell commands.
    Every query here carries the owner, and a key that is absent resolves to
    None -- the same answer `.first()` gave, and the correct one.
    """

    def __init__(
        self,
        db: Session,
        owner_id: int,
        *,
        ticket_keys: set[str] | None = None,
    ) -> None:
        self.owner_id = owner_id

        self.defaults = db.query(models.PRAgentDefaults).filter(
            models.PRAgentDefaults.owner_id == owner_id
        ).first()

        # `in_([])` is valid SQL but a wasted round trip, which is the thing
        # being removed.
        self.items: dict[str, models.WorkItemSettings] = {}
        if ticket_keys:
            rows = db.query(models.WorkItemSettings).filter(
                models.WorkItemSettings.owner_id == owner_id,
                models.WorkItemSettings.ticket_key.in_(sorted(ticket_keys)),
            ).all()
            self.items = {row.ticket_key: row for row in rows}

        # Every registration this account has, rather than the repos on the
        # board: which repo a card resolves against is derived per card from
        # its pull requests and branches, and rebuilding that here to narrow
        # the query would be a second copy of `_registration_for`'s rule. An
        # account registers a handful of repos, so the whole set is one query
        # either way.
        self.registrations: dict[str, models.RepoWebhook] = {
            row.repo: row
            for row in db.query(models.RepoWebhook).filter(
                models.RepoWebhook.owner_id == owner_id
            ).all()
        }

    def registration(self, repo: str | None) -> models.RepoWebhook | None:
        """The repo's registration, or None -- never another account's."""
        return self.registrations.get(repo) if repo else None


def resolve_settings(
    db: Session,
    owner_id: int,
    registration: models.RepoWebhook | None,
    ticket_key: str | None = None,
    prefetch: SettingsPrefetch | None = None,
) -> EffectiveSettings:
    """
    Merge a work item over a repo registration over the user's account defaults.

    Args:
        registration: The repo's own row, or None when the repo was never
            registered -- the case where falling back matters most.
        ticket_key: The work item being resolved for. `None` must resolve
            exactly as this function did before the work-item layer existed,
            which is what keeps every pre-existing call site correct.
        prefetch: Rows already loaded for this owner, when many items are being
            resolved together. Omitted, every row is read here exactly as
            before, which is what keeps every other call site unchanged. A
            prefetch built for a different owner is refused rather than
            trusted, since the rows it holds decide what a run may execute.
    """
    if prefetch is not None and prefetch.owner_id != owner_id:
        raise ValueError(
            "SettingsPrefetch belongs to another owner; resolving against it "
            "would read that account's registrations."
        )

    if prefetch is not None:
        defaults = prefetch.defaults
    else:
        defaults = db.query(models.PRAgentDefaults).filter(
            models.PRAgentDefaults.owner_id == owner_id
        ).first()

    resolved = EffectiveSettings()

    def pick(key: str, repo_value, default_value, fallback):
        """Take the repo value if it says anything, else the account default."""
        if repo_value:
            resolved.sources[key] = "repo"
            return repo_value
        if default_value:
            resolved.sources[key] = "defaults"
            return default_value
        resolved.sources[key] = "unset"
        return fallback

    resolved.slack_channel = pick(
        "slack_channel",
        (registration.slack_channel or "").strip() if registration else "",
        (defaults.slack_channel or "").strip() if defaults else "",
        None,
    )

    resolved.export_to_docs = bool(pick(
        "export_to_docs",
        bool(registration.export_to_docs) if registration else False,
        bool(defaults.export_to_docs) if defaults else False,
        False,
    ))

    resolved.qa_emails = pick(
        "qa_emails",
        _lines(registration.qa_emails) if registration else [],
        _lines(defaults.qa_emails) if defaults else [],
        [],
    )

    # A status always has a value, so "says something" cannot distinguish
    # unset from deliberate here; treat the schema default as unset.
    repo_status = (registration.jira_done_status or "") if registration else ""
    default_status = (defaults.jira_done_status or "") if defaults else ""
    resolved.jira_done_status = pick(
        "jira_done_status",
        repo_status if repo_status and repo_status != "Done" else "",
        default_status,
        "Done",
    )

    # Booleans that default to on cannot use truthiness either: False is a
    # real choice, not an absence. The repo row wins whenever it exists.
    if registration is not None:
        resolved.close_issues_on_merge = bool(registration.close_issues_on_merge)
        resolved.sources["close_issues_on_merge"] = "repo"
    elif defaults is not None:
        resolved.close_issues_on_merge = bool(defaults.close_issues_on_merge)
        resolved.sources["close_issues_on_merge"] = "defaults"
    else:
        resolved.close_issues_on_merge = True
        resolved.sources["close_issues_on_merge"] = "unset"

    # Same shape again. Off by default: holding a work item open is only safe
    # for a team whose QA loop actually replies, and a repo that has not opted
    # in must keep the behaviour it had.
    if registration is not None:
        resolved.close_on_qa_signoff = bool(registration.close_on_qa_signoff)
        resolved.sources["close_on_qa_signoff"] = "repo"
    elif defaults is not None:
        resolved.close_on_qa_signoff = bool(defaults.close_on_qa_signoff)
        resolved.sources["close_on_qa_signoff"] = "defaults"
    else:
        resolved.close_on_qa_signoff = False
        resolved.sources["close_on_qa_signoff"] = "unset"

    # Context docs are the one setting that accumulates rather than overrides.
    # The account-level docs are the standards that apply everywhere -- an API
    # style guide, a security policy -- while a repo's own describe that
    # codebase. A repo that adds a spec should be reviewed against both, so
    # letting the repo value win would silently drop the global standards.
    # Order puts the global ones first and dedupes, since the reviewer reads
    # them in order under a context budget.
    account_docs = _lines(defaults.context_doc_ids) if defaults else []
    repo_docs = _lines(registration.context_doc_ids) if registration else []
    seen: set[str] = set()
    resolved.context_doc_ids = [
        doc for doc in account_docs + repo_docs
        if not (doc in seen or seen.add(doc))
    ]
    if account_docs and repo_docs:
        resolved.sources["context_doc_ids"] = "both"
    elif repo_docs:
        resolved.sources["context_doc_ids"] = "repo"
    elif account_docs:
        resolved.sources["context_doc_ids"] = "defaults"
    else:
        resolved.sources["context_doc_ids"] = "unset"

    resolved.reviewers = pick(
        "reviewers",
        _lines(registration.reviewers) if registration else [],
        _lines(defaults.reviewers) if defaults else [],
        [],
    )

    # Falls back to the summary channel last: a review request with nowhere to
    # go is worse than one in a busy channel.
    resolved.review_slack_channel = pick(
        "review_slack_channel",
        (registration.review_slack_channel or "").strip() if registration else "",
        (defaults.review_slack_channel or "").strip() if defaults else "",
        resolved.slack_channel,
    )

    # Same shape as close_issues_on_merge: a boolean whose False is a real
    # choice, so the repo row wins whenever it exists rather than when truthy.
    # The final fallback is off -- an unconfigured repo must never auto-merge.
    if registration is not None:
        resolved.auto_merge_on_approval = bool(registration.auto_merge_on_approval)
        resolved.sources["auto_merge_on_approval"] = "repo"
    elif defaults is not None:
        resolved.auto_merge_on_approval = bool(defaults.auto_merge_on_approval)
        resolved.sources["auto_merge_on_approval"] = "defaults"
    else:
        resolved.auto_merge_on_approval = False
        resolved.sources["auto_merge_on_approval"] = "unset"

    resolved.reviewer_contacts = pick(
        "reviewer_contacts",
        parse_contacts(registration.reviewer_contacts) if registration else {},
        parse_contacts(defaults.reviewer_contacts) if defaults else {},
        {},
    )

    resolved.merge_method = pick(
        "merge_method",
        (registration.merge_method or "") if registration else "",
        (defaults.merge_method or "") if defaults else "",
        "squash",
    )

    # Same "a present row is a deliberate choice" shape as close_issues_on_merge:
    # False is a real answer here, so truthiness cannot distinguish it from
    # unset. Unlike auto_merge_on_approval the final fallback is *on* -- this
    # writes to a board rather than to a branch, and the failure it prevents is
    # a card that sits in Todo through an entire review and QA round trip.
    if registration is not None:
        resolved.project_board_sync = bool(registration.project_board_sync)
        resolved.sources["project_board_sync"] = "repo"
    elif defaults is not None:
        resolved.project_board_sync = bool(defaults.project_board_sync)
        resolved.sources["project_board_sync"] = "defaults"
    else:
        resolved.project_board_sync = True
        resolved.sources["project_board_sync"] = "unset"

    # Overrides rather than accumulating, unlike context_doc_ids: a board's
    # columns belong to that board, so merging one repo's map into another's
    # would map stages onto columns that do not exist there.
    resolved.project_column_map = pick(
        "project_column_map",
        parse_column_map(registration.project_column_map) if registration else {},
        parse_column_map(defaults.project_column_map) if defaults else {},
        {},
    )

    _resolve_authoring(
        db, owner_id, registration, defaults, ticket_key, resolved, prefetch
    )

    return resolved


def _resolve_authoring(
    db: Session,
    owner_id: int,
    registration: models.RepoWebhook | None,
    defaults: models.PRAgentDefaults | None,
    ticket_key: str | None,
    resolved: EffectiveSettings,
    prefetch: SettingsPrefetch | None = None,
) -> None:
    """
    Fill in the authoring fields: work item -> repo -> defaults -> fallback.

    Split out because it is the only part of the chain with three layers, and
    because the work-item layer reads *only* the two authoring fields -- a
    ticket is a judgement about autonomy, not a place to re-point a Slack
    channel.
    """
    item = None
    if ticket_key:
        if prefetch is not None:
            # Absent from the prefetch means no row exists for this owner and
            # key, which is what the query below returned too.
            item = prefetch.items.get(ticket_key)
        else:
            item = db.query(models.WorkItemSettings).filter(
                models.WorkItemSettings.owner_id == owner_id,
                models.WorkItemSettings.ticket_key == ticket_key,
            ).first()

    repo_mode = normalize_mode(registration.authoring_mode) if registration else None
    default_mode = normalize_mode(defaults.authoring_mode) if defaults else None
    item_mode = normalize_mode(item.authoring_mode) if item else None

    if item is not None and item.handed_back_at is not None:
        # The bound was spent, or a human took the branch over. This overrides
        # everything above it: without it the next review event re-triggers the
        # driver on a work item that was explicitly given back.
        resolved.authoring_mode = "assisted"
        resolved.sources["authoring_mode"] = "handed_back"
        resolved.handed_back = True
        resolved.handed_back_reason = item.handed_back_reason
    elif item_mode:
        resolved.authoring_mode = item_mode
        resolved.sources["authoring_mode"] = "work_item"
    elif repo_mode:
        resolved.authoring_mode = repo_mode
        resolved.sources["authoring_mode"] = "repo"
    elif default_mode:
        resolved.authoring_mode = default_mode
        resolved.sources["authoring_mode"] = "defaults"
    else:
        resolved.authoring_mode = "assisted"
        resolved.sources["authoring_mode"] = "unset"

    item_rounds = item.autonomous_max_rounds if item else None
    repo_rounds = registration.autonomous_max_rounds if registration else None
    default_rounds = defaults.autonomous_max_rounds if defaults else None

    if item_rounds is not None:
        resolved.autonomous_max_rounds = int(item_rounds)
        resolved.sources["autonomous_max_rounds"] = "work_item"
    elif repo_rounds is not None:
        resolved.autonomous_max_rounds = int(repo_rounds)
        resolved.sources["autonomous_max_rounds"] = "repo"
    elif default_rounds is not None:
        resolved.autonomous_max_rounds = int(default_rounds)
        resolved.sources["autonomous_max_rounds"] = "defaults"
    else:
        resolved.autonomous_max_rounds = 2
        resolved.sources["autonomous_max_rounds"] = "unset"

    # Account-level only: read straight off the defaults row, with no repo or
    # work-item layer to resolve against. A missing row means nobody has saved
    # settings, which is not the same as choosing the dataclass defaults -- but
    # it resolves to them, because that is the behaviour the install already
    # had before these were settings.
    for _flag in ("auto_start_on_assignment", "auto_start_on_review", "auto_start_on_qa"):
        stored = getattr(defaults, _flag, None) if defaults else None
        if stored is None:
            resolved.sources[_flag] = "unset"
        else:
            setattr(resolved, _flag, bool(stored))
            resolved.sources[_flag] = "defaults"

    resolved.preset_label = pick_text(
        resolved, "preset_label",
        (registration.preset_label or "").strip() if registration else "",
        (defaults.preset_label or "").strip() if defaults else "",
    )
    resolved.source_path = pick_text(
        resolved, "source_path",
        (registration.source_path or "").strip() if registration else "",
        (defaults.source_path or "").strip() if defaults else "",
    )
    resolved.prepare_command = pick_text(
        resolved, "prepare_command",
        (registration.prepare_command or "").strip() if registration else "",
        (defaults.prepare_command or "").strip() if defaults else "",
    )
    resolved.test_command = pick_text(
        resolved, "test_command",
        (registration.test_command or "").strip() if registration else "",
        (defaults.test_command or "").strip() if defaults else "",
    )


def pick_text(
    resolved: EffectiveSettings, key: str, repo_value: str, default_value: str
) -> str | None:
    """Repo wins if it says anything, else the account default, else None."""
    if repo_value:
        resolved.sources[key] = "repo"
        return repo_value
    if default_value:
        resolved.sources[key] = "defaults"
        return default_value
    resolved.sources[key] = "unset"
    return None
