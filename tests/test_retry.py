"""Retry guarding the write phase: per-step attempts, paced by a Backoff, spent before OnError."""
import asyncio
import unittest

from cabaxiom import Assessment, Async, Backoff, DriftItem, Kahn, OnError, Parallel, Reconciler, Retry, Serial, Step


class _FlakyFix(Step):
    # Raises on the first `failures` apply() calls, then applies cleanly. Counts every try.
    def __init__(self, failures: int):
        self.__failures = failures
        self.tries = 0
        self.__done = False

    def assess(self) -> list:
        return Assessment(deviation=[] if self.__done else [DriftItem("svc", "needs fix")])

    def apply(self) -> None:
        self.tries += 1
        if self.tries <= self.__failures:
            raise RuntimeError("transient io failure")
        self.__done = True


class _AsyncFlaky(Step):
    # The coroutine twin of _FlakyFix: each attempt awaits, then fails or settles.
    def __init__(self, failures: int):
        self.__failures = failures
        self.tries = 0
        self.__done = False

    def assess(self) -> list:
        return Assessment(deviation=[] if self.__done else [DriftItem("svc", "needs io")])

    async def apply(self) -> None:
        self.tries += 1
        await asyncio.sleep(0)
        if self.tries <= self.__failures:
            raise RuntimeError("transient io failure")
        self.__done = True


class _Recording(Backoff):
    # Records the stall count handed to each pause and pauses for nothing, so a test stays instant.
    def __init__(self):
        self.stalls: list[int] = []

    def delay(self, stalled: int) -> float:
        self.stalls.append(stalled)
        return 0.0


class RetryTests(unittest.TestCase):
    def test_a_flaky_apply_succeeds_within_its_attempts(self):
        step = _FlakyFix(failures=2)
        residual = Reconciler((step,), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries, 3)

    def test_exhausted_attempts_propagate_under_failfast(self):
        step = _FlakyFix(failures=5)
        with self.assertRaises(RuntimeError):
            Reconciler((step,), retry=Retry(2)).converge()
        self.assertEqual(step.tries, 2)   # both tries spent, then the failure aborted the run

    def test_an_exhausted_failure_reaches_best_effort_as_one_residual_entry(self):
        step = _FlakyFix(failures=5)
        residual = Reconciler((step,), executor=Serial(OnError.BestEffort), retry=Retry(2)).converge()
        self.assertEqual(step.tries, 2)
        self.assertEqual(sum("step failed" in item.message for item in residual), 1)

    def test_a_backoff_paces_the_attempts_with_the_stall_count(self):
        backoff = _Recording()
        step = _FlakyFix(failures=2)
        Reconciler((step,), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, [1, 2])   # one pause after each failed try, none after success

    def test_the_neutral_single_try_wraps_nothing(self):
        def do(step):
            return None

        self.assertIs(Retry(1)(do), do)

    def test_attempts_must_be_positive(self):
        for bad in (0, -1):
            with self.subTest(attempts=bad):
                with self.assertRaises(ValueError):
                    Retry(bad)

    def test_reads_are_never_retried(self):
        # The guard covers only the write phase, so a probe that raises does so once, not per attempt.
        class _BrokenProbe(Step):
            def __init__(self):
                self.probes = 0

            def assess(self) -> list:
                self.probes += 1
                raise RuntimeError("probe down")

        step = _BrokenProbe()
        with self.assertRaises(RuntimeError):
            Reconciler((step,), retry=Retry(3)).converge()
        self.assertEqual(step.probes, 1)

    def test_prune_is_guarded_too(self):
        class _FlakyPrune(Step):
            def __init__(self):
                self.tries = 0

            def prune(self) -> list:
                self.tries += 1
                if self.tries == 1:
                    raise RuntimeError("transient teardown failure")
                return []

        step = _FlakyPrune()
        residue = Reconciler((step,), retry=Retry(2)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(step.tries, 2)

    def test_retries_are_uniform_under_a_fanning_executor(self):
        # The retries live inside the write callable, so a pool worker retries its own step inline.
        step = _FlakyFix(failures=1)
        with Parallel() as executor:
            residual = Reconciler((step,), Kahn(), executor=executor, retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries, 2)   # failed once, recovered on the second, third never spent


class AsyncRetryTests(unittest.TestCase):
    def test_a_flaky_coroutine_gets_a_fresh_attempt_on_the_loop(self):
        step = _AsyncFlaky(failures=2)
        residual = Reconciler((step,), Kahn(), executor=Async(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries, 3)

    def test_a_recovery_mid_attempts_stops_the_retrying(self):
        step = _AsyncFlaky(failures=1)
        residual = Reconciler((step,), Kahn(), executor=Async(), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries, 2)   # failed once, recovered on the second, third never spent

    def test_exhausted_coroutine_attempts_propagate(self):
        step = _AsyncFlaky(failures=5)
        with self.assertRaises(RuntimeError):
            Reconciler((step,), Kahn(), executor=Async(), retry=Retry(2)).converge()
        self.assertEqual(step.tries, 2)

    def test_a_backoff_paces_the_attempts_on_the_event_loop(self):
        backoff = _Recording()
        step = _AsyncFlaky(failures=2)
        Reconciler((step,), Kahn(), executor=Async(), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, [1, 2])
