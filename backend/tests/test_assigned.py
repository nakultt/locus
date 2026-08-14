"""
Fetching what is assigned to a user.

Two properties matter here and neither is obvious from the happy path.

**A source that fails must not blank the board.** GitHub and Jira are queried
independently, and a dead one has to cost only its own half. A board that
renders empty because one integration timed out reads as "nothing assigned",
which is the one wrong answer -- someone acts on it by going home.

**The GitHub issues endpoint returns pull requests too.** They carry a
`pull_request` key and nothing else distinguishes them. Left in, every open PR
would appear as a freshly assigned task with no work done on it, which is
exactly backwards.
"""

import httpx
import pytest

from app import schemas
from app.services import assigned

JIRA_CONFIG = {
    "api_key": "token",
    "credentials": {"email": "dev@acme.com", "url": "https://acme.atlassian.net"},
}


def _transport(handler):
    """Route every request in a test through one fake responder."""
    return httpx.MockTransport(handler)


@pytest.fixture
def patched_client(monkeypatch):
    """Swap httpx.AsyncClient for one backed by a caller-supplied handler."""

    def install(handler):
        original = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = _transport(handler)
            return original(*args, **kwargs)

        monkeypatch.setattr(assigned.httpx, "AsyncClient", factory)

    return install


class TestGitHubAssigned:
    @pytest.mark.asyncio
    async def test_returns_assigned_issues(self, patched_client):
        patched_client(lambda request: httpx.Response(200, json=[
            {
                "number": 12,
                "title": "Retry the webhook",
                "html_url": "https://github.com/acme/api/issues/12",
                "state": "open",
                "assignee": {"login": "dev"},
                "repository": {"full_name": "acme/api"},
                "updated_at": "2026-08-01T10:00:00Z",
            },
        ]))

        items = await assigned.github_assigned("token")

        assert len(items) == 1
        assert items[0].key == "acme/api#12"
        assert items[0].source is schemas.TaskSource.github
        assert items[0].repo == "acme/api"
        assert items[0].number == 12

    @pytest.mark.asyncio
    async def test_drops_pull_requests(self, patched_client):
        """That endpoint returns PRs alongside issues; only issues are tasks."""
        patched_client(lambda request: httpx.Response(200, json=[
            {
                "number": 12,
                "title": "An issue",
                "html_url": "https://github.com/acme/api/issues/12",
                "repository": {"full_name": "acme/api"},
            },
            {
                "number": 13,
                "title": "A pull request",
                "html_url": "https://github.com/acme/api/pull/13",
                "repository": {"full_name": "acme/api"},
                "pull_request": {"url": "https://api.github.com/..."},
            },
        ]))

        items = await assigned.github_assigned("token")

        assert [i.key for i in items] == ["acme/api#12"]

    @pytest.mark.asyncio
    async def test_survives_an_explicit_null_repository(self, patched_client):
        """GitHub sends `null`, so `.get(key, default)` does not save you."""
        patched_client(lambda request: httpx.Response(200, json=[
            {"number": 1, "title": "Orphan", "repository": None},
            {
                "number": 2,
                "title": "Fine",
                "html_url": "https://github.com/acme/api/issues/2",
                "repository": {"full_name": "acme/api"},
            },
        ]))

        items = await assigned.github_assigned("token")

        assert [i.key for i in items] == ["acme/api#2"]

    @pytest.mark.asyncio
    async def test_failure_returns_empty_not_raise(self, patched_client):
        patched_client(lambda request: httpx.Response(500))

        assert await assigned.github_assigned("token") == []

    @pytest.mark.asyncio
    async def test_no_token_skips_the_call(self):
        assert await assigned.github_assigned("") == []


class TestJiraAssigned:
    @pytest.mark.asyncio
    async def test_returns_assigned_tickets(self, patched_client):
        patched_client(lambda request: httpx.Response(200, json={
            "issues": [
                {
                    "key": "LOC-431",
                    "fields": {
                        "summary": "Retry the merge gate",
                        "status": {"name": "In Progress"},
                        "assignee": {"displayName": "Dev"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Story"},
                        "updated": "2026-08-01T10:00:00.000+0530",
                    },
                }
            ]
        }))

        items = await assigned.jira_assigned(JIRA_CONFIG)

        assert len(items) == 1
        assert items[0].key == "LOC-431"
        assert items[0].source is schemas.TaskSource.jira
        assert items[0].status == "In Progress"
        assert items[0].url == "https://acme.atlassian.net/browse/LOC-431"

    @pytest.mark.asyncio
    async def test_falls_back_when_the_new_search_path_is_absent(self, patched_client):
        """Atlassian deprecated /search; instances differ on which they serve."""
        seen: list[str] = []

        def handler(request):
            seen.append(request.url.path)
            if request.url.path.endswith("/search/jql"):
                return httpx.Response(404)
            return httpx.Response(200, json={
                "issues": [{"key": "LOC-1", "fields": {"summary": "Old path"}}]
            })

        patched_client(handler)
        items = await assigned.jira_assigned(JIRA_CONFIG)

        assert [i.key for i in items] == ["LOC-1"]
        assert any(p.endswith("/search/jql") for p in seen)
        assert any(p.endswith("/rest/api/3/search") for p in seen)

    @pytest.mark.asyncio
    async def test_flattens_the_document_format_description(self, patched_client):
        """Jira Cloud returns nested ADF nodes, not a string."""
        patched_client(lambda request: httpx.Response(200, json={
            "issues": [
                {
                    "key": "LOC-2",
                    "fields": {
                        "summary": "Nested",
                        "description": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Retry"},
                                        {"type": "text", "text": "the gate"},
                                    ],
                                }
                            ],
                        },
                    },
                }
            ]
        }))

        items = await assigned.jira_assigned(JIRA_CONFIG)

        assert items[0].body == "Retry the gate"

    @pytest.mark.asyncio
    async def test_incomplete_credentials_skip_the_call(self):
        assert await assigned.jira_assigned({"api_key": "t", "credentials": {}}) == []

    @pytest.mark.asyncio
    async def test_failure_returns_empty_not_raise(self, patched_client):
        patched_client(lambda request: httpx.Response(500))

        assert await assigned.jira_assigned(JIRA_CONFIG) == []
