"""
Requesting a review on the pull requests autonomous mode opens.

The mode used to open its pull requests with nobody requested, so the work
never appeared in GitHub's own review queue -- the place a reviewer actually
looks -- and the first anybody heard of it was a Slack ping.

The three rules pinned here are all about not spending a reviewer's attention
twice: the request goes out only on the pull request this call created, never
on the one the already-open path returns; the author is dropped, because GitHub
rejects a list naming them and rejects the whole of it; and a failure is
swallowed, because the pull request is open either way and the attempt was
already spent.
"""

import httpx
import pytest

from app.services.integrations import github_pr

PR = {
    "number": 7,
    "html_url": "https://github.com/acme/api/pull/7",
    "user": {"login": "locus-agent"},
}


@pytest.fixture
def calls(monkeypatch):
    """Record every request, answering from a caller-supplied handler."""
    recorded: list[httpx.Request] = []

    def install(handler):
        original = httpx.AsyncClient

        def responder(request: httpx.Request) -> httpx.Response:
            recorded.append(request)
            return handler(request)

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(responder)
            return original(*args, **kwargs)

        monkeypatch.setattr(github_pr.httpx, "AsyncClient", factory)
        return recorded

    return install


def _created(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/requested_reviewers"):
        return httpx.Response(201, json=PR)
    return httpx.Response(201, json=PR)


async def _open(reviewers):
    return await github_pr.create_pull_request(
        "token",
        "acme/api",
        title="PROJ-1: Retry the webhook",
        head="locus/proj-1",
        base="main",
        body="body",
        reviewers=reviewers,
    )


class TestOnCreate:
    @pytest.mark.asyncio
    async def test_the_configured_reviewers_are_requested(self, calls):
        recorded = calls(_created)

        result = await _open(["senior-dev", "tech-lead"])

        assert result["number"] == 7
        request = recorded[-1]
        assert request.url.path == "/repos/acme/api/pulls/7/requested_reviewers"
        assert b'"senior-dev"' in request.content
        assert b'"tech-lead"' in request.content

    @pytest.mark.asyncio
    async def test_nobody_configured_makes_no_second_call(self, calls):
        """The default. An empty list must not cost a request, and must not
        reach GitHub as an empty review request either."""
        recorded = calls(_created)

        await _open([])

        assert len(recorded) == 1

    @pytest.mark.asyncio
    async def test_the_author_is_dropped(self, calls):
        """
        GitHub rejects a request naming the pull request's own author with a
        422 covering the whole list, so the agent's account appearing in a
        team's reviewer list would cost everyone else their request too.
        """
        recorded = calls(_created)

        await _open(["locus-agent", "senior-dev"])

        assert b"locus-agent" not in recorded[-1].content
        assert b"senior-dev" in recorded[-1].content

    @pytest.mark.asyncio
    async def test_the_author_alone_makes_no_call(self, calls):
        recorded = calls(_created)

        await _open(["Locus-Agent"])

        assert len(recorded) == 1

    @pytest.mark.asyncio
    async def test_a_refused_request_still_returns_the_pull_request(self, calls):
        """
        The pull request is open, which is what the attempt was spent on.
        Failing the run over a notification would hand the work item back.
        """
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/requested_reviewers"):
                return httpx.Response(422, json={"message": "Reviews may only be requested from collaborators"})
            return httpx.Response(201, json=PR)

        calls(handler)

        result = await _open(["outside-contractor"])

        assert result["number"] == 7
        assert "error" not in result


class TestOnAnExistingPullRequest:
    @pytest.mark.asyncio
    async def test_a_rework_does_not_re_request(self, calls):
        """
        A rework pushes to the branch the reviewer already read, so
        `create_pull_request` 422s and returns the open one. Re-requesting
        there re-notifies them on every round, which is what gets a bot muted.
        """
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("/pulls"):
                return httpx.Response(422, json={"errors": [{"message": "A pull request already exists"}]})
            if request.method == "GET":
                return httpx.Response(200, json=[PR])
            return httpx.Response(201, json=PR)

        recorded = calls(handler)

        result = await _open(["senior-dev"])

        assert result["number"] == 7
        assert not any(
            r.url.path.endswith("/requested_reviewers") for r in recorded
        )

    @pytest.mark.asyncio
    async def test_an_empty_diff_requests_nobody(self, calls):
        """No pull request was opened, so there is nothing to review."""
        recorded = calls(lambda request: httpx.Response(
            422, json={"errors": [{"message": "No commits between main and locus/proj-1"}]}
        ))

        result = await _open(["senior-dev"])

        assert "error" in result
        assert not any(
            r.url.path.endswith("/requested_reviewers") for r in recorded
        )


class TestRequestReviewersDirectly:
    @pytest.mark.asyncio
    async def test_it_reports_who_was_actually_requested(self, calls):
        calls(lambda request: httpx.Response(201, json=PR))

        requested = await github_pr.request_reviewers(
            "token", "acme/api", 7, ["senior-dev", "locus-agent"],
            author="locus-agent",
        )

        assert requested == ["senior-dev"]

    @pytest.mark.asyncio
    async def test_a_transport_failure_is_swallowed(self, calls):
        def boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        calls(boom)

        assert await github_pr.request_reviewers(
            "token", "acme/api", 7, ["senior-dev"]
        ) == []

    @pytest.mark.asyncio
    async def test_no_pull_request_number_is_not_a_call(self, calls):
        recorded = calls(lambda request: httpx.Response(201, json=PR))

        assert await github_pr.request_reviewers(
            "token", "acme/api", None, ["senior-dev"]
        ) == []
        assert recorded == []
