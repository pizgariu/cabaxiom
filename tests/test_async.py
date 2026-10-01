"""Parallel executor - fan each wave onto an asyncio event loop, awaiting coroutine steps concurrently."""
import asyncio
import unittest
from typing import Any

from cabaxiom import (
    DFS,
    Assessment,
    Cancelled,
    Changes,
    Deadline,
    Deferred,
    DriftItem,
    Fault,
    Flag,
    Kahn,
    OnError,
    Parallel,
    Reconciler,
    Settled,
    Skew,
    Step,
    Supervised,
)


class SettledSeamTests(unittest.IsolatedAsyncioTestCase):
    def test_the_wave_seam_triple_is_published(self):
        # run_wave is a public seam on an open base, where a seam's types are part of the seam. A custom
        # waves executor names its own signature with Settled instead of importing an underscored name.
        # A declared alias (the `type` statement), so the triple it names sits behind __value__. The
        # artifacts a step produced ride the seam too, between the changes and the error.
        #
        # The error channel is `Fault`, which names the THREE BaseException cut-throughs apart from an
        # ordinary failure - a channel that carries one must say so, spoken once rather than
        # in the eight signatures that used to spell the union by hand.
        self.assertEqual(Settled.__value__, tuple[Step, Changes, dict[str, Any], Fault | None])
        self.assertEqual(Fault.__value__, Exception | Cancelled | Skew | Deferred)


class _AsyncFix(Step):
    # Parallel write, sync re-probe. apply() awaits its I/O, assess() is the quick read fanned per wave.
    def __init__(self) -> None:
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")]), {}

    async def apply(self, inputs):
        await asyncio.sleep(0)
        self.__done[0] = True
        return None, {}
class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_converge_awaits_a_coroutine_apply_and_clears_the_drift(self):
        residual = await Reconciler((_AsyncFix(),), Kahn(), mode=Parallel()).converge()
        self.assertEqual(residual, [])

    async def test_a_sync_apply_still_runs_inline_under_async(self):
        # A plain (non-coroutine) apply() is used as-is, so a sync step drops into Parallel unchanged.
        log = []

        class _SyncStep(Step):
            def apply(self, inputs):
                log.append("ran")

                return None, {}
        await Reconciler((_SyncStep(),), Kahn(), mode=Parallel()).converge()
        self.assertEqual(log, ["ran"])

    async def test_a_wave_of_coroutines_runs_concurrently(self):
        # Two independent async steps share one wave. Each appends, yields with sleep(0), then appends again.
        # Both start before either ends, which only a concurrent gather produces. Parallel would end P before Q begins.
        log = []

        class _Interleaving(Step):
            async def apply(self, inputs):
                log.append(f"{self.__class__.__name__}-start")
                await asyncio.sleep(0)
                log.append(f"{self.__class__.__name__}-end")

                return None, {}
        class P(_Interleaving):
            pass

        class Q(_Interleaving):
            pass

        await Reconciler((P(), Q()), Kahn(), mode=Parallel()).converge()
        starts = {log.index("P-start"), log.index("Q-start")}
        ends = {log.index("P-end"), log.index("Q-end")}
        self.assertLess(max(starts), min(ends))   # both started before either finished -> concurrent

    async def test_the_wave_barrier_preserves_dependency_order(self):
        # Across waves the barrier holds every Step.expects edge, exactly as Parallel's does.
        log = []

        class First(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                log.append("first")

                return None, {}
        class Second(Step):
            expects = (First,)

            async def apply(self, inputs):
                await asyncio.sleep(0)
                log.append("second")

                return None, {}
        await Reconciler((Second(), First()), Kahn(), mode=Parallel()).converge()
        self.assertEqual(log, ["first", "second"])

    async def test_failfast_reraises_a_coroutine_failure_on_the_calling_thread(self):
        class _AsyncBoom(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

                return None, {}
        with self.assertRaises(RuntimeError):
            await Reconciler((_AsyncBoom(),), Kahn(), mode=Parallel()).converge()

    async def test_best_effort_collects_a_coroutine_failure_as_residual_drift(self):
        class _AsyncBoom(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

                return None, {}
        residual = await Reconciler((_AsyncBoom(),), Kahn(), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    async def test_best_effort_blocks_the_dependent_of_a_failed_wave_mate(self):
        # The async family blocks like the sync one. A dependent in a later wave is reported, not awaited.
        ran: list = []

        class _AsyncBoom(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

                return None, {}
        class _Dependent(Step):
            expects = (_AsyncBoom,)

            async def apply(self, inputs):
                ran.append("dependent")

                return None, {}
        residual = await Reconciler((_AsyncBoom(), _Dependent()), Kahn(), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])
        self.assertEqual(sum("step blocked" in item.message for item in residual), 1)

    async def test_what_apply_returns_is_routed_to_the_applied_channel(self):
        class _Creates(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                return [DriftItem("svc", "created")], {}

        residual = await Reconciler((_Creates(),), Kahn(), mode=Parallel()).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["created"])

    def test_a_flat_only_ordering_is_rejected_at_build(self):
        # DFS yields only the one-wave fallback, which fanned out would ignore expects=, so Parallel's Waves shape refuses it.
        # The arranger runs during construction, so the reject fires before converge is ever awaited.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((_AsyncFix(),), DFS(), mode=Parallel())
        self.assertIn("Waves", str(ctx.exception))

    async def test_cancellation_aborts_before_a_wave(self):
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as ctx:
            await Reconciler((_AsyncFix(),), Kahn(), mode=Parallel(), cancellation=flag).converge()
        self.assertIn("Flag", str(ctx.exception))


class AsyncSupervisedTests(unittest.IsolatedAsyncioTestCase):
    """Supervised runs the same waves as Parallel, yet polls the Cancellation WHILE a wave is in
    flight, so a Deadline can bound a hung apply() instead of blocking on it forever."""

    async def test_a_wave_that_settles_converges_like_asyncparallel(self):
        residual = await Reconciler((_AsyncFix(),), Kahn(), mode=Supervised(poll=0.005)).converge()
        self.assertEqual(residual, [])

    async def test_a_deadline_bounds_a_hung_wave_that_asyncparallel_would_block_on(self):
        # The headline - an apply() that never returns. Under Parallel the wave's gather would block forever
        # and the Deadline could never fire. Supervised polls the Deadline mid-wave, cancels the hung
        # coroutine and raises Cancelled. wait_for is only a suite safety net - a working supervisor raises in
        # ~0.02s, long before it. A regression that blocks turns into a TimeoutError (a failure, not a hang).
        class Hangs(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("h", "hung")]), {}

            async def apply(self, inputs):
                await asyncio.Event().wait()   # never set - blocks its wave

                return None, {}
        async def drive():
            reconciler = Reconciler((Hangs(),), Kahn(), mode=Supervised(poll=0.005),
                                         cancellation=Deadline(0.02))
            return await asyncio.wait_for(reconciler.converge(), timeout=2.0)

        with self.assertRaises(Cancelled) as ctx:
            await drive()
        self.assertIn("Deadline", str(ctx.exception))

    def test_rejects_a_non_positive_poll(self):
        with self.assertRaises(ValueError):
            Supervised(poll=0)

    def test_rejects_a_non_positive_grace(self):
        with self.assertRaises(ValueError):
            Supervised(grace=0)

    async def test_the_drain_is_bounded_by_grace_when_a_cleanup_hangs(self):
        # The drain trade, pinned. A step that catches its cancel into a cleanup that ITSELF hangs used to
        # re-hang the aborted wave forever, after the Deadline had already fired - the supervisor's headline
        # broken by exactly the misbehaving step it exists to contain. The drain now waits `grace` and
        # abandons the straggler. A detached pathological task beats an abort that never returns.
        class _HangsInCleanup(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("h", "hung")]), {}

            async def apply(self, inputs):
                try:
                    await asyncio.Event().wait()   # never set - blocks its wave
                except asyncio.CancelledError:
                    await asyncio.Event().wait()   # the cleanup itself hangs, swallowing the cancel

                return None, {}
        async def drive():
            reconciler = Reconciler((_HangsInCleanup(),), Kahn(),
                                         mode=Supervised(poll=0.005, grace=0.02),
                                         cancellation=Deadline(0.02))
            try:
                return await asyncio.wait_for(reconciler.converge(), timeout=2.0)
            finally:
                # Test hygiene. The abandoned straggler is put down before the loop closes. Its cleanup is
                # not shielded, so the second cancel ends it.
                for task in (t for t in asyncio.all_tasks() if t is not asyncio.current_task()):
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

        with self.assertRaises(Cancelled) as ctx:
            await drive()
        self.assertIn("Deadline", str(ctx.exception))

    async def test_a_self_cancelling_step_is_recorded_as_its_own_failure(self):
        # A step that ends cancelled UN-ASKED (nothing cancelled the run, no Cancellation fired) is a step
        # defect, a value for the ONE Ledger rule - not an abort. It used to surface as a CancelledError
        # nobody requested, vaporising the wave-mates' settled outcomes from the record. BestEffort now
        # keeps the record - the defect named, the mate's outcome kept.
        ran: list = []

        class _SelfCancels(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("s", "broken")]), {}

            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise asyncio.CancelledError()

                return None, {}
        class _Mate(Step):
            async def apply(self, inputs):
                ran.append("mate")

                return None, {}
        residual = await Reconciler((_SelfCancels(), _Mate()), Kahn(), mode=Supervised(OnError.BestEffort, poll=0.005)).converge()
        self.assertEqual(ran, ["mate"])
        self.assertEqual(sum("ended cancelled although the run was not" in item.message for item in residual), 1)

    async def test_a_bounded_wave_drains_its_cancelled_coroutines(self):
        # When the Deadline fires mid-wave, the outstanding coroutines are not just cancelled and abandoned -
        # they are awaited so their cancellation settles here, leaving no orphaned tasks behind (which a
        # long-lived supervised Controller would otherwise accumulate). Proven by the step observing its own
        # CancelledError before Cancelled surfaces to the caller.
        class Hangs(Step):
            def __init__(self) -> None:
                self.__saw_cancel = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            @property
            def saw_cancel(self) -> bool:
                return self.__saw_cancel[0]

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("h", "hung")]), {}

            async def apply(self, inputs):
                try:
                    await asyncio.Event().wait()   # never set
                except asyncio.CancelledError:
                    self.__saw_cancel[0] = True
                    raise

                return None, {}
        hangs = Hangs()

        async def drive():
            reconciler = Reconciler((hangs,), Kahn(), mode=Supervised(poll=0.005),
                                         cancellation=Deadline(0.02))
            return await asyncio.wait_for(reconciler.converge(), timeout=2.0)

        with self.assertRaises(Cancelled):
            await drive()
        self.assertTrue(hangs.saw_cancel)   # the coroutine was awaited through its cancellation, not orphaned

    async def test_a_sync_apply_still_runs_inline_under_supervision(self):
        # A plain (non-coroutine) apply() is used as-is. The outcome is not awaitable, so it is taken directly.
        log = []

        class _SyncStep(Step):
            def apply(self, inputs):
                log.append("ran")

                return None, {}
        await Reconciler((_SyncStep(),), Kahn(), mode=Supervised(poll=0.005)).converge()
        self.assertEqual(log, ["ran"])

    async def test_cancellation_aborts_before_a_wave(self):
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as ctx:
            await Reconciler((_AsyncFix(),), Kahn(), mode=Supervised(poll=0.005), cancellation=flag).converge()
        self.assertIn("Flag", str(ctx.exception))

    async def test_failfast_reraises_a_coroutine_failure(self):
        class _AsyncBoom(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

                return None, {}
        with self.assertRaises(RuntimeError):
            await Reconciler((_AsyncBoom(),), Kahn(), mode=Supervised(poll=0.005)).converge()

    async def test_best_effort_collects_a_coroutine_failure_as_residual_drift(self):
        class _AsyncBoom(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("async io failure")

                return None, {}
        residual = await Reconciler((_AsyncBoom(),), Kahn(), mode=Supervised(OnError.BestEffort, poll=0.005)).converge()
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    async def test_what_apply_returns_is_routed_to_the_applied_channel(self):
        class _Creates(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                return [DriftItem("svc", "created")], {}

        residual = await Reconciler((_Creates(),), Kahn(), mode=Supervised(poll=0.005)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["created"])


class AsyncNativeCancellationTests(unittest.IsolatedAsyncioTestCase):
    """asyncio-native cancellation (task.cancel(), a wait_for firing) against an IN-FLIGHT wave - the seam
    the kernel's cooperative Cancellation never exercises, where detached tasks used to hide. Neither
    asyncio.wait nor a bare gather cancels its input tasks. Both wave executors must keep the wave a barrier
    through it - cancel what still flies, settle it here, then let the abort continue - so no attempt task
    outlives the run it belonged to."""

    class _Hangs(Step):
        # A well-behaved hung step. It blocks forever, observes its cancel, re-raises. The flag is the proof
        # the wave was drained rather than abandoned.
        def __init__(self) -> None:
            self.__saw_cancel = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        @property
        def saw_cancel(self) -> bool:
            return self.__saw_cancel[0]

        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("h", "hung")]), {}

        async def apply(self, inputs):
            try:
                await asyncio.Event().wait()   # never set
            except asyncio.CancelledError:
                self.__saw_cancel[0] = True
                raise

            return None, {}
    async def test_supervised_drains_the_wave_when_the_run_itself_is_cancelled(self):
        # No Cancellation fires here. The CALLER cancels converge mid-wave (the wait_for firing). This pins
        # the supervisor's native-cancellation drain. The hung step observes its cancel BEFORE the abort
        # surfaces and no attempt task is left pending on the loop.
        hangs = self._Hangs()
        leftovers: list = []

        async def drive():
            reconciler = Reconciler((hangs,), Kahn(), mode=Supervised(poll=0.005))
            try:
                await asyncio.wait_for(reconciler.converge(), timeout=0.05)
            finally:
                leftovers.extend(task for task in asyncio.all_tasks() if task is not asyncio.current_task())

        with self.assertRaises(asyncio.TimeoutError):
            await drive()
        self.assertTrue(hangs.saw_cancel)
        self.assertEqual(leftovers, [])

    async def test_parallel_drains_the_wave_when_the_run_itself_is_cancelled(self):
        # The same external abort against the unsupervised executor. The gather is cancelled from outside,
        # and the barrier must still settle every wave-mate before the abort continues out.
        hangs = self._Hangs()
        leftovers: list = []

        async def drive():
            reconciler = Reconciler((hangs,), Kahn(), mode=Parallel())
            try:
                await asyncio.wait_for(reconciler.converge(), timeout=0.05)
            finally:
                leftovers.extend(task for task in asyncio.all_tasks() if task is not asyncio.current_task())

        with self.assertRaises(asyncio.TimeoutError):
            await drive()
        self.assertTrue(hangs.saw_cancel)
        self.assertEqual(leftovers, [])

    async def test_parallel_records_a_leaked_cancellederror_as_the_steps_own_failure(self):
        # A misbehaving write raises bare CancelledError - the one exception attempt() does not catch into a
        # triple. The TaskGroup does not treat a cancelled child as an abort. The wave settles (the mate
        # runs to its end), so the leak surfaces from the collection as the leaker's OWN failure for the
        # Ledger - not as a cancellation nobody requested. FailFast then re-raises it after the barrier.
        ran: list = []

        class _Leaks(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise asyncio.CancelledError()

                return None, {}
        class _Mate(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0.01)
                ran.append("mate")

                return None, {}
        with self.assertRaises(RuntimeError) as ctx:
            await Reconciler((_Leaks(), _Mate()), Kahn(), mode=Parallel()).converge()
        self.assertIn("ended cancelled although the run was not", str(ctx.exception))
        self.assertEqual(ran, ["mate"])   # the wave settled before the defect was classified


class AsyncHaltTests(unittest.IsolatedAsyncioTestCase):
    """OnError.Halt on the event loop. The waves inherit the policy from the same Ledger rule, so the
    failing wave settles, the later wave is skipped and the coroutine returns the record instead of
    raising."""

    async def test_halt_returns_the_record_on_the_event_loop(self):
        ran = []

        class _Fails(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("io dies")

                return None, {}
        class _WaveMate(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0)
                ran.append("mate")

                return None, {}
        class _Later(Step):
            expects = (_WaveMate,)

            async def apply(self):  # pragma: no cover - the halt must keep this from running
                ran.append("later")

        residual = await Reconciler((_Fails(), _WaveMate(), _Later()), Kahn(), mode=Parallel(OnError.Halt)).converge()
        self.assertEqual(ran, ["mate"])   # the wave settled, the later wave never started
        messages = [item.message for item in residual]
        self.assertEqual(sum("step failed" in message for message in messages), 1)
        self.assertEqual(sum("step skipped: the run halted after _Fails failed" in message for message in messages), 1)

