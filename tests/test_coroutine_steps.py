"""A step whose write is a coroutine, on the one engine there is.

These used to be the Async executor's tests. There is no Async executor now - the kernel is async native,
so a coroutine apply() needs no special dispatcher and these cases belong to whichever dispatcher is
driving. They are kept because the SHAPE they exercise is still real, not because the executor was."""
import asyncio
import unittest

from cabaxiom import DFS, Assessment, Cancelled, DriftItem, Flag, Kahn, OnError, Parallel, Reconciler, Step


class _AsyncFix(Step):
    # Parallel write, sync re-probe. apply() awaits its I/O, drift() is the quick read every dispatcher runs serially.
    def __init__(self) -> None:
        self.__done = [False]

    def assess(self) -> list:
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")])

    async def apply(self) -> None:
        await asyncio.sleep(0)
        self.__done[0] = True


class AsyncTests(unittest.TestCase):
    def test_converge_awaits_a_coroutine_apply_and_clears_the_drift(self):
        residual = asyncio.run(Reconciler((_AsyncFix(),), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(residual, [])

    def test_a_sync_apply_still_runs_inline_under_async(self):
        # A plain (non-coroutine) apply() is used as-is, so a sync step drops into Parallel unchanged.
        log = []

        class _SyncStep(Step):
            def apply(self) -> None:
                log.append("ran")

        asyncio.run(Reconciler((_SyncStep(),), Kahn(), dispatcher=Parallel()).converge())
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

        asyncio.run(Reconciler((P(), Q()), Kahn(), dispatcher=Parallel()).converge())
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

        asyncio.run(Reconciler((Second(), First()), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(log, ["first", "second"])

    def test_failfast_reraises_a_coroutine_failure_on_the_calling_thread(self):
        class _AsyncBoom(Step):
            async def apply(self):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((_AsyncBoom(),), Kahn(), dispatcher=Parallel()).converge())

    def test_best_effort_collects_a_coroutine_failure_as_residual_drift(self):
        class _AsyncBoom(Step):
            async def apply(self):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

        residual = asyncio.run(Reconciler((_AsyncBoom(),), Kahn(), dispatcher=Parallel(OnError.BestEffort)).converge())
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_what_apply_returns_is_routed_to_the_applied_channel(self):
        class _Creates(Step):
            async def apply(self):
                await asyncio.sleep(0)
                return [DriftItem("svc", "created")]

        residual = asyncio.run(Reconciler((_Creates(),), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["created"])

    def test_a_flat_only_ordering_is_rejected_at_build(self):
        # DFS yields only the one-wave fallback, which fanned out would ignore after=, so Parallel refuses it.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((_AsyncFix(),), DFS(), dispatcher=Parallel())
        self.assertIn("Parallel", str(ctx.exception))

    def test_cancellation_aborts_before_a_wave(self):
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as ctx:
            asyncio.run(Reconciler((_AsyncFix(),), Kahn(), dispatcher=Parallel(), cancellation=flag).converge())
        self.assertIn("Flag", str(ctx.exception))
