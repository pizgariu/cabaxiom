"""Async executor: fan each wave onto an asyncio event loop, awaiting coroutine steps concurrently."""
import asyncio
import unittest

from cabaxiom import DFS, Assessment, Async, Cancelled, DriftItem, Flag, Kahn, OnError, Reconciler, Step


class _AsyncFix(Step):
    # Async write, sync re-probe: apply() awaits its I/O, drift() is the quick read every executor runs serially.
    def __init__(self) -> None:
        self.__done = [False]

    def assess(self) -> list:
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")])

    async def apply(self) -> None:
        await asyncio.sleep(0)
        self.__done[0] = True


class AsyncTests(unittest.TestCase):
    def test_converge_awaits_a_coroutine_apply_and_clears_the_drift(self):
        residual = Reconciler((_AsyncFix(),), Kahn(), executor=Async()).converge()
        self.assertEqual(residual, [])

    def test_a_sync_apply_still_runs_inline_under_async(self):
        # A plain (non-coroutine) apply() is used as-is, so a sync step drops into Async unchanged.
        log = []

        class _SyncStep(Step):
            def apply(self) -> None:
                log.append("ran")

        Reconciler((_SyncStep(),), Kahn(), executor=Async()).converge()
        self.assertEqual(log, ["ran"])

    def test_a_wave_of_coroutines_runs_concurrently(self):
        # Two independent async steps share one wave. Each appends, yields with sleep(0), then appends again.
        # Both start before either ends, which only a concurrent gather produces. Serial would end P before Q begins.
        log = []

        class _Interleaving(Step):
            async def apply(self):
                log.append(f"{type(self).__name__}-start")
                await asyncio.sleep(0)
                log.append(f"{type(self).__name__}-end")

        class P(_Interleaving):
            pass

        class Q(_Interleaving):
            pass

        Reconciler((P(), Q()), Kahn(), executor=Async()).converge()
        starts = {log.index("P-start"), log.index("Q-start")}
        ends = {log.index("P-end"), log.index("Q-end")}
        self.assertLess(max(starts), min(ends))   # both started before either finished -> concurrent

    def test_the_wave_barrier_preserves_dependency_order(self):
        # Across waves the barrier holds every Step.after edge, exactly as Parallel's does.
        log = []

        class First(Step):
            async def apply(self):
                await asyncio.sleep(0)
                log.append("first")

        class Second(Step):
            after = (First,)

            async def apply(self):
                await asyncio.sleep(0)
                log.append("second")

        Reconciler((Second(), First()), Kahn(), executor=Async()).converge()
        self.assertEqual(log, ["first", "second"])

    def test_failfast_reraises_a_coroutine_failure_on_the_calling_thread(self):
        class _AsyncBoom(Step):
            async def apply(self):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

        with self.assertRaises(RuntimeError):
            Reconciler((_AsyncBoom(),), Kahn(), executor=Async()).converge()

    def test_best_effort_collects_a_coroutine_failure_as_residual_drift(self):
        class _AsyncBoom(Step):
            async def apply(self):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

        residual = Reconciler((_AsyncBoom(),), Kahn(), executor=Async(OnError.BestEffort)).converge()
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_what_apply_returns_is_routed_to_the_applied_channel(self):
        class _Creates(Step):
            async def apply(self):
                await asyncio.sleep(0)
                return [DriftItem("svc", "created")]

        residual = Reconciler((_Creates(),), Kahn(), executor=Async()).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["created"])

    def test_a_flat_only_ordering_is_rejected_at_build(self):
        # DFS yields only the one-wave fallback, which fanned out would ignore after=, so Async refuses it.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((_AsyncFix(),), DFS(), executor=Async())
        self.assertIn("Async", str(ctx.exception))

    def test_cancellation_aborts_before_a_wave(self):
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as ctx:
            Reconciler((_AsyncFix(),), Kahn(), executor=Async(), cancellation=flag).converge()
        self.assertIn("Flag", str(ctx.exception))
