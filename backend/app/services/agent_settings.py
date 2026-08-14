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
    context_doc_ids: list[str] = field(default_factory=list)
    # GitHub logins expected to review this repo.
    reviewers: list[str] = field(default_factory=list)
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

    # Context docs are repo-specific by nature -- they describe that codebase.
    resolved.context_doc_ids = (
        _lines(registration.context_doc_ids) if registration else []
    )
    resolved.sources["context_doc_ids"] = "repo" if resolved.context_doc_ids else "unset"

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

    resolved.merge_method = pick(
        "merge_method",
        (registration.merge_method or "") if registration else "",
        (defaults.merge_method or "") if defaults else "",
        "squash",
    )

    return resolved
