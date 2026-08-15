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


def resolve_settings(
    db: Session,
    owner_id: int,
    registration: models.RepoWebhook | None,
) -> EffectiveSettings:
    """
    Merge a repo registration over the user's account defaults.

    Args:
        registration: The repo's own row, or None when the repo was never
            registered -- the case where falling back matters most.
    """
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

    return resolved
