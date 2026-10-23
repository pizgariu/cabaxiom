"""Retry guarding the write phase - per-step attempts, paced by a Backoff, spent before OnError."""
import asyncio
import threading
import unittest

from cabaxiom import (
    Assessment,
    Cancelled,
    DriftItem,
    Kahn,
    OnError,
    Parallel,
    Reconciler,
    Retry,
    Step,
    ThreadDispatcher,
)
from cabaxiom.core.record import Observer
from cabaxiom.core.run import BaseRetry
from support import RecordingBackoff


class _FlakyFix(Step):
    # Raises on the first `failures` apply() calls, then applies cleanly. Counts every try.
    def __init__(self, failures: int):
        self.__failures = failures
        self.tries = [0]
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs fix")]), {}

    def apply(self, inputs):
        self.tries[0] += 1
        if self.tries[0] <= self.__failures:
            raise RuntimeError("transient io failure")
        self.__done[0] = True


        return None, {}
class _AsyncFlaky(Step):
    # The coroutine twin of _FlakyFix. Each attempt awaits, then fails or settles.
    def __init__(self, failures: int):
        self.__failures = failures
        self.tries = [0]
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")]), {}

    async def apply(self, inputs):
        self.tries[0] += 1
        await asyncio.sleep(0)
        if self.tries[0] <= self.__failures:
            raise RuntimeError("transient io failure")
        self.__done[0] = True


        return None, {}
class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_flaky_apply_succeeds_within_its_attempts(self):
        step = _FlakyFix(failures=2)
        residual = await Reconciler((step,), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries[0], 3)

    async def test_exhausted_attempts_propagate_under_failfast(self):
        step = _FlakyFix(failures=5)
        with self.assertRaises(RuntimeError):
            await Reconciler((step,), retry=Retry(2)).converge()
        self.assertEqual(step.tries[0], 2)   # both tries spent, then the failure aborted the run

    async def test_an_exhausted_failure_reaches_best_effort_as_one_residual_entry(self):
        step = _FlakyFix(failures=5)
        residual = await Reconciler((step,), mode=Parallel(OnError.BestEffort), retry=Retry(2)).converge()
        self.assertEqual(step.tries[0], 2)
        self.assertEqual(sum("step failed" in item.message for item in residual), 1)

    async def test_a_backoff_paces_the_attempts_with_the_stall_count(self):
        backoff = RecordingBackoff()
        step = _FlakyFix(failures=2)
        await Reconciler((step,), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, [1, 2])   # one pause after each failed try, none after success

    def test_the_neutral_single_try_wraps_nothing(self):
        def do(step, inputs):
            return None

        self.assertIs(Retry(1).around(do), do)

    async def test_a_direct_wrap_without_a_retried_hook_still_retries(self):
        # Retry used standalone (no reconciler, no observer). The hook is optional, the loop unchanged. The
        # wrapped write is a coroutine now, awaited even when the step it guards is plain.
        calls: list[int] = []

        def do(step, inputs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return None

        self.assertIsNone(await Retry(2).around(do)(Step(), {}))
        self.assertEqual(len(calls), 2)

    async def test_a_direct_async_wrap_without_a_retried_hook_still_retries(self):
        # The coroutine twin of the hookless path: __rerun paces without announcing.
        calls: list[int] = []

        def do(step, inputs):
            async def attempt():
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("transient")
                return None
            return attempt()

        async def drive():
            return await Retry(3).around(do)(Step(), {})

        self.assertIsNone(await drive())
        self.assertEqual(len(calls), 2)

    def test_attempts_must_be_positive(self):
        for bad in (0, -1):
            with self.subTest(attempts=bad):
                with self.assertRaises(ValueError):
                    Retry(bad)

    async def test_reads_are_never_retried(self):
        # The guard covers only the write phase, so a probe that raises does so once, not per attempt.
        class _BrokenProbe(Step):
            def __init__(self):
                self.probes = [0]

            def assess(self, inputs):
                self.probes[0] += 1
                raise RuntimeError("probe down")

        step = _BrokenProbe()
        with self.assertRaises(BaseExceptionGroup) as caught:
            await Reconciler((step,), retry=Retry(3)).converge()
        self.assertIsInstance(caught.exception.exceptions[0], RuntimeError)
        self.assertEqual(step.probes[0], 1)

    async def test_prune_is_guarded_too(self):
        class _FlakyPrune(Step):
            def __init__(self):
                self.tries = [0]

            def prune(self, inputs):
                self.tries[0] += 1
                if self.tries[0] == 1:
                    raise RuntimeError("transient teardown failure")
                return [], {}

        step = _FlakyPrune()
        residue = await Reconciler((step,), retry=Retry(2)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(step.tries[0], 2)

    async def test_a_subclass_retries_only_the_failures_it_selects(self):
        # The axis is open through its base. A BaseRetry subclass narrows which failures earn another try.
        class RetryValueErrorOnly(BaseRetry):
            def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
                return isinstance(error, ValueError)

        # RuntimeError is not selected, so it cuts through after a single try - no attempts wasted on it.
        runtime = _FlakyFix(failures=5)   # raises RuntimeError
        with self.assertRaises(RuntimeError):
            await Reconciler((runtime,), retry=RetryValueErrorOnly(3)).converge()
        self.assertEqual(runtime.tries[0], 1)

        # A ValueError-raising flaky step IS selected, so it still recovers within the attempts.
        class _FlakyValue(Step):
            def __init__(self) -> None:
                self.tries = [0]
                self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__done[0] else [DriftItem("v", "needs fix")]), {}

            def apply(self, inputs):
                self.tries[0] += 1
                if self.tries[0] < 3:
                    raise ValueError("transient")
                self.__done[0] = True

                return None, {}
        value = _FlakyValue()
        residual = await Reconciler((value,), retry=RetryValueErrorOnly(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(value.tries[0], 3)

    async def test_retries_are_uniform_under_a_fanning_executor(self):
        # The retries live inside the write callable, so a pool worker retries its own step inline.
        step = _FlakyFix(failures=1)
        executor = Parallel()
        residual = await Reconciler((step,), Kahn(), mode=executor, retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries[0], 2)   # failed once, recovered on the second, third never spent


class AsyncRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_flaky_coroutine_gets_a_fresh_attempt_on_the_loop(self):
        step = _AsyncFlaky(failures=2)
        residual = await Reconciler((step,), Kahn(), mode=Parallel(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries[0], 3)

    async def test_a_recovery_mid_attempts_stops_the_retrying(self):
        step = _AsyncFlaky(failures=1)
        residual = await Reconciler((step,), Kahn(), mode=Parallel(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries[0], 2)   # failed once, recovered on the second, third never spent

    async def test_exhausted_coroutine_attempts_propagate(self):
        step = _AsyncFlaky(failures=5)
        with self.assertRaises(RuntimeError):
            await Reconciler((step,), Kahn(), mode=Parallel(), retry=Retry(2)).converge()
        self.assertEqual(step.tries[0], 2)

    async def test_a_backoff_paces_the_attempts_on_the_event_loop(self):
        backoff = RecordingBackoff()
        step = _AsyncFlaky(failures=2)
        await Reconciler((step,), Kahn(), mode=Parallel(), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, [1, 2])

    async def test_a_sync_failure_before_a_coroutine_shares_one_attempt_budget(self):
        # A write that raises SYNCHRONOUSLY first and only later hands back a coroutine. The sync failures
        # and the awaited retries draw on ONE budget, so total calls never exceed Retry(n). Before the fix
        # the async loop restarted from scratch and Retry(3) could spend four calls here.
        calls: list[int] = []

        class _Mixed(Step):
            def apply(self, inputs):
                calls.append(1)
                if len(calls) == 1:
                    raise RuntimeError("sync failure first")

                async def _io() -> None:
                    raise RuntimeError("async failure after")

                return _io()

        with self.assertRaises(RuntimeError):
            await Reconciler((_Mixed(),), Kahn(), mode=Parallel(), retry=Retry(3)).converge()
        self.assertEqual(len(calls), 3)   # 1 sync fail + 2 awaited, not 1 + 3

    async def test_a_sync_raise_on_a_retry_re_call_spends_an_attempt_like_any_failure(self):
        # The mirror edge of the mixed budget above. The FIRST call hands back a failing coroutine, so the
        # RE-CALL raises synchronously (connection setup dying before the coroutine is even built). The sync
        # raise used to escape the async loop's try entirely - budget abandoned, no pacing, one retried
        # announcement short. It is an attempt like any other now, so the budget runs to its promise.
        calls: list[int] = []

        class _DiesOnRecall(Step):
            def apply(self, inputs):
                calls.append(1)
                if len(calls) == 2:
                    raise RuntimeError("sync death on the retry")

                async def _io() -> None:
                    raise RuntimeError("async failure")

                return _io()

        with self.assertRaises(RuntimeError):
            await Reconciler((_DiesOnRecall(),), Kahn(), mode=Parallel(), retry=Retry(4)).converge()
        self.assertEqual(len(calls), 4)   # every promised attempt spent, the sync death included

    async def test_a_retry_answered_with_plain_changes_is_taken_as_is(self):
        # A step that answers the first call with a coroutine and the RETRY with plain Changes. The write
        # contract allows both shapes on every call, so the async loop re-checks each fresh outcome instead
        # of blindly awaiting a list.
        calls: list[int] = []

        class _ShiftsColour(Step):
            def apply(self, inputs):
                calls.append(1)
                if len(calls) == 1:
                    async def _io() -> None:
                        raise RuntimeError("async failure first")

                    return _io()
                return [DriftItem("svc", "recovered synchronously")], {}

        residual = await Reconciler((_ShiftsColour(),), Kahn(), mode=Parallel(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["recovered synchronously"])
        self.assertEqual(len(calls), 2)   # recovered on the first retry, the third attempt never spent

    async def test_a_subclass_restricts_retries_on_the_event_loop_too(self):
        # The async twin of the seam. retryable cuts through __rerun the same way it does the sync loop.
        class RetryValueErrorOnly(BaseRetry):
            def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
                return isinstance(error, ValueError)

        step = _AsyncFlaky(failures=5)   # raises RuntimeError, which is not selected
        with self.assertRaises(RuntimeError):
            await Reconciler((step,), Kahn(), mode=Parallel(), retry=RetryValueErrorOnly(3)).converge()
        self.assertEqual(step.tries[0], 1)   # cut through after one try, no attempts spent

    async def test_one_retry_can_give_each_step_its_own_budget(self):
        # The reason the seam sees the STEP and the count, not just the error. A single injected Retry
        # serves a run whose steps do not deserve the same number of tries. Construct it with the largest
        # budget and let the seam spend less where less is right.
        class Tiered(BaseRetry):
            def __init__(self, budgets: dict) -> None:
                super().__init__(max(budgets.values()))
                self._budgets = budgets

            def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
                return attempt < self._budgets[step.__class__.__name__]

        class Primary(_FlakyFix):
            pass

        class Sidecar(_FlakyFix):
            pass

        primary, sidecar = Primary(failures=2), Sidecar(failures=5)
        with self.assertRaises(RuntimeError):
            await Reconciler((primary, sidecar), retry=Tiered({"Primary": 3, "Sidecar": 1})).converge()
        self.assertEqual(primary.tries[0], 3)   # healed inside its own larger budget
        self.assertEqual(sidecar.tries[0], 1)   # abandoned after one, so it burns no attempts on a lost cause

    async def test_the_seam_is_asked_with_the_triple_the_observer_announces(self):
        seen: list = []

        class Watching(BaseRetry):
            def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
                seen.append((step.__class__.__name__, attempt, error.__class__.__name__))
                return True

        await Reconciler((_FlakyFix(failures=2),), retry=Watching(4)).converge()
        self.assertEqual(seen, [("_FlakyFix", 1, "RuntimeError"), ("_FlakyFix", 2, "RuntimeError")])

    async def test_a_cancelled_write_is_never_retried(self):
        # A step that raises Cancelled from its own cooperative check. The abort is a decision, not a
        # failure, so Retry cuts through without spending attempts or pacing a backoff.
        backoff = RecordingBackoff()

        class _Aborting(Step):
            def __init__(self):
                self.tries = [0]

            def apply(self, inputs):
                self.tries[0] += 1
                raise Cancelled("step observed the abort")

                return None, {}
        step = _Aborting()
        with self.assertRaises(Cancelled):
            await Reconciler((step,), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(step.tries[0], 1)        # no second attempt
        self.assertEqual(backoff.stalls, [])   # and no pause was paced

    async def test_a_cancelled_coroutine_write_is_never_retried(self):
        # The async twin. A coroutine write raising Cancelled cuts through __rerun the same way.
        backoff = RecordingBackoff()

        class _AsyncAborting(Step):
            def __init__(self):
                self.tries = [0]

            async def apply(self, inputs):
                self.tries[0] += 1
                await asyncio.sleep(0)
                raise Cancelled("step observed the abort")

                return None, {}
        step = _AsyncAborting()
        with self.assertRaises(Cancelled):
            await Reconciler((step,), Kahn(), mode=Parallel(), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(step.tries[0], 1)
        self.assertEqual(backoff.stalls, [])


class ThreadedRetryTests(unittest.IsolatedAsyncioTestCase):
    """Retry composed with the blocking bridge - the pair that was mutually exclusive and unnoticed.

    ThreadDispatcher threaded the WRAPPED callable, which under Retry(n) hands back a coroutine. to_thread
    returned it unawaited and the wave then tried to unpack a coroutine object as an outcome, so the step's
    apply() never ran at all. Every dispatcher had retry tests and every dispatcher had threading tests and
    no test had ever composed the two - which is the only reason a bridge that could not retry shipped.

    The order is the fix. The RAW call is what crosses to the worker thread, while the run's own retry budget is
    laid back over the threaded form. So an attempt covers one whole crossing, while a backoff sleeps on the
    event loop instead of holding a worker idle."""

    def _blocking(self, breaks: int):
        ran: list[str] = []

        class Blocking(Step):
            def assess(self, inputs):
                return Assessment(deviation=[] if len(ran) > breaks else [DriftItem("blocking", "unsettled")]), {}

            def apply(self, inputs):
                ran.append(threading.current_thread().name)
                if len(ran) <= breaks:
                    raise ConnectionError("transient")
                return [DriftItem("blocking", "wrote")], {}

        return Blocking(), ran

    async def test_a_blocking_step_under_a_retry_actually_runs(self):
        step, ran = self._blocking(0)
        residual = await Reconciler((step,), mode=ThreadDispatcher(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([finding.message for finding in residual.applied], ["wrote"])
        self.assertEqual(len(ran), 1)

    async def test_the_write_still_leaves_the_event_loop(self):
        # The whole point of the bridge, plus the thing a fix could quietly undo. Laying the retry outside the
        # threading must not pull the blocking call back onto the loop.
        step, ran = self._blocking(0)
        await Reconciler((step,), mode=ThreadDispatcher(), retry=Retry(3)).converge()
        self.assertNotEqual(ran, [threading.main_thread().name])

    async def test_a_transient_failure_spends_attempts_through_the_bridge(self):
        step, ran = self._blocking(2)
        residual = await Reconciler((step,), mode=ThreadDispatcher(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(len(ran), 3)   # two transients, then the write that stuck

    async def test_exhausting_the_budget_is_one_failure_not_a_mangled_outcome(self):
        step, ran = self._blocking(9)
        residual = await Reconciler((step,), mode=ThreadDispatcher(Parallel(OnError.BestEffort)),
                                    retry=Retry(3)).converge()
        self.assertEqual(len(ran), 3)
        self.assertEqual([finding.message for finding in residual.failures],
                         ["step failed: ConnectionError: transient"])

    async def test_the_retried_hook_still_fires_from_behind_the_bridge(self):
        # The observer must not be able to tell that the work moved to a thread. rewire() lays the SAME
        # observer over the threaded call, so retryable() and retried see the real step exactly as before.
        seen: list[str] = []

        class Watching(Observer):
            def retried(self, step, attempt, exception):
                seen.append(f"{Step.named(step)}#{attempt}")

        step, _ = self._blocking(2)
        await Reconciler((step,), mode=ThreadDispatcher(), retry=Retry(3), observer=Watching()).converge()
        self.assertEqual(seen, ["Blocking#1", "Blocking#2"])

    async def test_a_retry_of_one_needs_no_rewire_and_still_threads(self):
        # Retry(1) hands the raw call straight back, so the bridge must work when there is nothing to lay over
        # it - the branch a fix built only for the wrapped case would miss.
        step, ran = self._blocking(0)
        residual = await Reconciler((step,), mode=ThreadDispatcher(), retry=Retry(1)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(len(ran), 1)
        self.assertNotEqual(ran, [threading.main_thread().name])
