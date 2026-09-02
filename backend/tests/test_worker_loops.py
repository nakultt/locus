"""
The background loops themselves.

Three loops run for the life of the process, and each one's failure is silent:
if `worker_loop` dies, PR jobs queue up and are never analyzed; if
`merge_gate_loop` dies, approved pull requests sit open forever; if
`qa_email_loop` dies, QA replies stop being processed. Nothing raises, nothing
alerts -- work simply stops happening.

So the property worth pinning is that a loop keeps running through a failure it
did not expect. Each test drives a real iteration and then cancels, rather than
asserting on internals.
"""

import asyncio

import pytest

from app.services import worker


async def run_briefly(coroutine_fn, seconds: float = 0.2) -> None:
    """Run a loop, then cancel it the way the lifespan shutdown does."""
    task = asyncio.create_task(coroutine_fn())
    await asyncio.sleep(seconds)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


class TestWorkerLoopSurvivesFailures:
    @pytest.mark.asyncio
    async def test_a_job_that_raises_does_not_kill_the_loop(self, monkeypatch):
        """
        One malformed job must not stop every later one from being analyzed.
        """
        calls = {"n": 0}

        def claim() -> int | None:
            calls["n"] += 1
            return 1

        async def explode(_job_id: int) -> None:
            raise RuntimeError("bad job")

        monkeypatch.setattr(worker, "_claim_next_job", claim)
        monkeypatch.setattr(worker, "recover_stale_jobs", lambda *a, **kw: 0)
        monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)
        monkeypatch.setattr(
            "app.routers.webhooks.run_pr_job", explode, raising=False
        )

        await run_briefly(worker.worker_loop)

        # It kept going rather than stopping at the first exception.
        assert calls["n"] > 1

    @pytest.mark.asyncio
    async def test_a_failing_claim_does_not_kill_the_loop(self, monkeypatch):
        """A database blip must not permanently stop the worker."""
        calls = {"n": 0}

        def flaky() -> int | None:
            calls["n"] += 1
            raise RuntimeError("database is gone")

        monkeypatch.setattr(worker, "_claim_next_job", flaky)
        monkeypatch.setattr(worker, "recover_stale_jobs", lambda *a, **kw: 0)
        monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)

        await run_briefly(worker.worker_loop)

        assert calls["n"] > 1

    @pytest.mark.asyncio
    async def test_recovery_failing_at_startup_does_not_stop_the_worker(
        self, monkeypatch
    ):
        """
        Recovery is a rescue, not a precondition. A worker that refused to
        start because it could not scan for orphans would turn a small problem
        into a total outage.
        """
        def boom(*_a, **_kw):
            raise RuntimeError("cannot reach the database")

        claimed = {"n": 0}

        def claim() -> int | None:
            claimed["n"] += 1
            return None

        monkeypatch.setattr(worker, "recover_stale_jobs", boom)
        monkeypatch.setattr(worker, "_claim_next_job", claim)
        monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)

        await run_briefly(worker.worker_loop)

        assert claimed["n"] > 0

    @pytest.mark.asyncio
    async def test_cancellation_stops_the_loop(self, monkeypatch):
        """The lifespan cancels these on shutdown; they must actually stop."""
        monkeypatch.setattr(worker, "recover_stale_jobs", lambda *a, **kw: 0)
        monkeypatch.setattr(worker, "_claim_next_job", lambda: None)
        monkeypatch.setattr(worker, "POLL_INTERVAL_SECONDS", 0.01)

        await run_briefly(worker.worker_loop)


class TestSweepLoopsSurviveFailures:
    @pytest.mark.asyncio
    async def test_a_failing_merge_sweep_does_not_kill_the_loop(
        self, monkeypatch
    ):
        """
        The sweep exists because no event will arrive to retry the gate. A
        loop that stopped on one error would leave approved PRs open forever
        -- the exact failure it was written to prevent.
        """
        calls = {"n": 0}

        async def explode() -> int:
            calls["n"] += 1
            raise RuntimeError("GitHub is down")

        monkeypatch.setattr("app.services.pipeline.automerge.sweep_once", explode)
        monkeypatch.setattr(
            "app.services.pipeline.automerge.SWEEP_INTERVAL_SECONDS", 0.01
        )

        await run_briefly(worker.merge_gate_loop)

        assert calls["n"] > 1

    @pytest.mark.asyncio
    async def test_a_failing_qa_poll_does_not_kill_the_loop(self, monkeypatch):
        calls = {"n": 0}

        async def explode() -> int:
            calls["n"] += 1
            raise RuntimeError("Gmail is down")

        monkeypatch.setattr("app.services.pipeline.qa_email_poller.poll_once", explode)
        monkeypatch.setattr(
            "app.services.pipeline.qa_email_poller.POLL_INTERVAL_SECONDS", 0.01
        )

        await run_briefly(worker.qa_email_loop)

        assert calls["n"] > 1


class TestAdvisoryLockGating:
    """
    The sweeps scan for work rather than claiming it, so every instance would
    match the same rows. Both loops end in a message to a person: two sweepers
    means an approved PR is announced twice, two pollers means one QA reply is
    processed twice.
    """

    @pytest.mark.asyncio
    async def test_a_held_merge_lock_skips_the_sweep(self, monkeypatch):
        from contextlib import contextmanager

        ran = {"n": 0}

        async def sweep() -> int:
            ran["n"] += 1
            return 0

        @contextmanager
        def taken(_key):
            yield False  # Another instance holds it.

        monkeypatch.setattr("app.services.pipeline.automerge.sweep_once", sweep)
        monkeypatch.setattr(
            "app.services.pipeline.automerge.SWEEP_INTERVAL_SECONDS", 0.01
        )
        monkeypatch.setattr("app.core.locks.advisory_lock", taken)

        await run_briefly(worker.merge_gate_loop)

        assert ran["n"] == 0

    @pytest.mark.asyncio
    async def test_a_held_qa_lock_skips_the_poll(self, monkeypatch):
        from contextlib import contextmanager

        ran = {"n": 0}

        async def poll() -> int:
            ran["n"] += 1
            return 0

        @contextmanager
        def taken(_key):
            yield False

        monkeypatch.setattr("app.services.pipeline.qa_email_poller.poll_once", poll)
        monkeypatch.setattr(
            "app.services.pipeline.qa_email_poller.POLL_INTERVAL_SECONDS", 0.01
        )
        monkeypatch.setattr("app.core.locks.advisory_lock", taken)

        await run_briefly(worker.qa_email_loop)

        assert ran["n"] == 0

    @pytest.mark.asyncio
    async def test_an_available_lock_runs_the_sweep(self, monkeypatch):
        """The gate must not be so tight that the work never runs."""
        ran = {"n": 0}

        async def sweep() -> int:
            ran["n"] += 1
            return 0

        monkeypatch.setattr("app.services.pipeline.automerge.sweep_once", sweep)
        monkeypatch.setattr(
            "app.services.pipeline.automerge.SWEEP_INTERVAL_SECONDS", 0.01
        )

        await run_briefly(worker.merge_gate_loop)

        # SQLite has no advisory locks, so the context manager yields True.
        assert ran["n"] > 0


class TestLockOnSQLite:
    def test_the_lock_is_a_no_op_without_postgres(self):
        """
        SQLite is the development database and single-instance by
        construction. Failing closed there would stop the loops running at all
        locally, which is a worse outcome than the duplication it guards.
        """
        from app.core import locks

        with locks.advisory_lock(locks.MERGE_SWEEP_LOCK) as held:
            assert held is True
