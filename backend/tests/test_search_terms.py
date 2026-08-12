"""
Search query construction.

Naive queries return noise: Slack tokenizes on punctuation so an unquoted
LOC-431 matches "loc" or "431" anywhere, and a PR title searched verbatim
matches nothing. These tests pin the query shapes.
"""

from app.services.search_terms import jira_jql, significant_words, slack_queries


class TestSignificantWords:
    def test_strips_stopwords_and_pr_noise(self):
        assert significant_words("Fix payment webhook timeouts") == [
            "payment", "webhook", "timeouts"
        ]

    def test_strips_conventional_commit_prefix(self):
        assert "api" not in significant_words("feat(api): add retry logic")
        assert "retry" in significant_words("feat(api): add retry logic")

    def test_strips_branch_prefix(self):
        words = significant_words("feature/payment-retry-fix")
        assert "feature" not in words
        assert "payment" in words

    def test_noise_only_title_yields_little(self):
        # "chore: bump deps" carries no searchable subject beyond "deps".
        assert len(significant_words("chore: bump deps")) <= 1

    def test_handles_none(self):
        assert significant_words(None) == []


class TestSlackQueries:
    def test_ticket_keys_are_quoted(self):
        queries = slack_queries(["LOC-431"], "acme/api", 892)
        assert '"LOC-431"' in queries

    def test_includes_pr_url_and_short_reference(self):
        queries = slack_queries([], "acme/api", 892)
        assert '"github.com/acme/api/pull/892"' in queries
        assert '"api#892"' in queries

    def test_includes_linked_issue_references(self):
        queries = slack_queries([], "acme/api", 892, issue_numbers=[12])
        assert '"api#12"' in queries

    def test_topic_query_added_for_descriptive_title(self):
        queries = slack_queries([], "acme/api", 1, title="Fix payment webhook timeouts")
        assert any("payment" in q and not q.startswith('"') for q in queries)

    def test_no_topic_query_for_vague_title(self):
        """A single common word would match everything, so it is not issued."""
        queries = slack_queries([], "acme/api", 1, title="chore: bump deps")
        assert all(q.startswith('"') for q in queries)

    def test_queries_are_deduplicated(self):
        queries = slack_queries(["LOC-1", "LOC-1"], "acme/api", 1)
        assert len(queries) == len(set(queries))


class TestJiraJQL:
    def test_builds_conjunctive_text_search(self):
        jql = jira_jql([], "Fix payment webhook timeouts")
        assert 'text ~ "payment"' in jql
        assert " AND " in jql
        assert "ORDER BY updated DESC" in jql

    def test_excludes_already_known_keys(self):
        jql = jira_jql(["LOC-431"], "Fix payment webhook timeouts")
        assert 'key NOT IN ("LOC-431")' in jql

    def test_scopes_to_project_when_hinted(self):
        jql = jira_jql([], "Fix payment webhook timeouts", project_hint="LOC")
        assert 'project = "LOC"' in jql

    def test_returns_none_when_nothing_searchable(self):
        assert jira_jql([], "chore: bump deps") is None
        assert jira_jql([], None) is None
