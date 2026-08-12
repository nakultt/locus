"""Ticket-key extraction — the primitive the PR Context Agent rests on."""

from app.services.linking import (
    extract_from_pr,
    extract_pr_references,
    extract_ticket_keys,
)


class TestTicketKeyExtraction:
    def test_extracts_from_title(self):
        assert extract_ticket_keys("Fix timeouts (LOC-431)") == ["LOC-431"]

    def test_extracts_from_branch_with_slash_and_underscore(self):
        assert extract_from_pr(branch="feature/LOC-431-retry") == ["LOC-431"]
        assert extract_from_pr(branch="bugfix/OPS-12_hotfix") == ["OPS-12"]

    def test_deduplicates_across_sources(self):
        keys = extract_from_pr(
            title="LOC-431: retry logic",
            branch="fix/LOC-431",
            body="Closes LOC-431",
        )
        assert keys == ["LOC-431"]

    def test_preserves_first_seen_order(self):
        keys = extract_from_pr(
            title="LOC-431: retry",
            branch="bugfix/OPS-12_hotfix",
            body="Also closes ENG-7",
        )
        assert keys == ["LOC-431", "OPS-12", "ENG-7"]

    def test_reads_commit_messages(self):
        assert extract_from_pr(commit_messages=["ENG-7 fix parser"]) == ["ENG-7"]

    def test_returns_empty_when_no_keys(self):
        assert extract_from_pr(title="No ticket here", branch="main") == []

    def test_ignores_none_fields(self):
        assert extract_from_pr(title=None, branch=None, body=None) == []


class TestFalsePositives:
    """
    Tokens shaped like ticket keys that never are. Without this filter a PR
    titled "Fix UTF-8 handling" invents a ticket and the agent hunts for it.
    """

    def test_rejects_encodings_and_hashes(self):
        assert extract_ticket_keys("Fix UTF-8 and SHA-256 handling") == []

    def test_rejects_language_versions(self):
        assert extract_ticket_keys("Bump to ES-2020") == []

    def test_rejects_cve_identifiers(self):
        assert extract_ticket_keys("Patch CVE-2024 advisory") == []

    def test_still_finds_real_key_alongside_false_positive(self):
        assert extract_ticket_keys("LOC-431: fix UTF-8 decoding") == ["LOC-431"]


class TestPRReferences:
    def test_extracts_and_deduplicates_pr_urls(self):
        text = (
            "see https://github.com/acme/api/pull/892 "
            "and https://github.com/acme/api/pull/892"
        )
        assert extract_pr_references(text) == [("acme/api", 892)]

    def test_handles_none(self):
        assert extract_pr_references(None) == []
