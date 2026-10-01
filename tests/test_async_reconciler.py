"""The async-native engine. converge(), prune() and assess() are coroutines run on the caller's own event
loop, awaiting coroutine step hooks and fanning them across each wave."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cabaxiom import (
    Assessment,
    Cancelled,
    DriftItem,
    Fixed,
    Fixpoint,
    OnError,
    Only,
    Parallel,
    Reconciler,
    RunMode,
    Step,
    Waves,
    WavesDispatcher,
)
from support import Staged


class _Stuck(Step):
    # Drift never clears and apply() is a no-op, so every pass leaves the same residual.
    def __init__(self) -> None:
        self.__applies = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    @property
    def applies(self) -> int:
        return self.__applies[0]

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("svc", "stuck")]), {}

    def apply(self, inputs):
        self.__applies[0] += 1
        return None, {}


class ConvergeTests(unittest.IsolatedAsyncioTestCase):
    """converge() awaited on the caller's loop, with coroutine and plain applies alike."""

    async def test_the_default_clears_the_drift_in_one_pass(self):
        # Parallel + Once (the defaults). The wave's async execute and Once.passes, one pass.
        step = Staged(1)
        residual = await Reconciler((step,), mode=Parallel()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.remaining, 0)

    async def test_a_coroutine_apply_is_awaited_on_the_callers_loop(self):
        # A coroutine apply() is awaited on the caller's loop, it really runs and what it returns lands on
        # the applied channel while the residual comes back clean.
        ran = []

        class _AsyncCreates(Step):
            def __init__(self) -> None:
                self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")]), {}

            async def apply(self, inputs):
                await asyncio.sleep(0)
                ran.append("apply")
                self.__done[0] = True
                return [DriftItem("svc", "created")], {}

        residual = await Reconciler((_AsyncCreates(),), mode=Parallel()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(ran, ["apply"])                                       # the coroutine actually ran
        self.assertEqual([item.message for item in residual.applied], ["created"])

    async def test_fixpoint_loops_until_the_residual_settles_clean(self):
        step = Staged(2)
        residual = await Reconciler((step,), mode=Parallel(), convergence=Fixpoint()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.remaining, 0)

    async def test_fixpoint_without_backoff_stops_on_the_first_unchanged_pass(self):
        step = _Stuck()
        residual = await Reconciler((step,), convergence=Fixpoint(max_passes=10)).converge()
        self.assertEqual(len(residual), 1)
        self.assertEqual(step.applies, 2)   # the opening pass plus one more, then the unchanged break

    async def test_fixpoint_with_backoff_paces_a_stalling_step_up_to_max_passes(self):
        # A zero backoff turns the unchanged pass into a paced retry bounded by max_passes.
        step = _Stuck()
        residual = await Reconciler((step,), convergence=Fixpoint(max_passes=3, backoff=Fixed(0))).converge()
        self.assertEqual(len(residual), 1)
        self.assertEqual(step.applies, 3)   # the opening pass plus two paced retries, no early break

    async def test_a_positive_backoff_awaits_the_loops_own_sleep(self):
        # A positive delay is awaited on the event loop (patched instant) rather than blocking it, so a
        # pause never stalls the coroutines sharing the loop.
        step = _Stuck()
        with patch("cabaxiom.reconciler.asyncio.sleep", new_callable=AsyncMock) as slept:
            residual = await Reconciler((step,), convergence=Fixpoint(max_passes=3, backoff=Fixed(2.5))).converge()
        self.assertEqual(len(residual), 1)
        self.assertEqual(step.applies, 3)   # the opening pass plus two paced retries
        self.assertEqual([call.args[0] for call in slept.call_args_list], [2.5])


class PruneTests(unittest.IsolatedAsyncioTestCase):
    """prune() as a coroutine teardown in reverse resolved order on the caller's loop."""

    async def test_prune_awaits_coroutines_in_reverse_of_build_order(self):
        log = []

        class PA(Step):
            async def prune(self, inputs):
                await asyncio.sleep(0)
                log.append("A")

                return None, {}
        class PB(Step):
            expects = (PA,)

            async def prune(self, inputs):
                await asyncio.sleep(0)
                log.append("B")

                return None, {}
        await Reconciler((PA(), PB())).prune()
        self.assertEqual(log, ["B", "A"])   # the dependent torn down before what it depends on

    async def test_prune_concatenates_residue_and_failures(self):
        # A step that reports residue and, under BestEffort, a sibling whose prune() blows up. Both land in
        # the returned proof set.
        class Survivor(Step):
            async def prune(self, inputs):
                await asyncio.sleep(0)
                return [DriftItem("vol", "external volume survives teardown")], {}

        class Breaks(Step):
            async def prune(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("teardown io failure")

        residue = await Reconciler((Survivor(), Breaks()), mode=Parallel(OnError.BestEffort)).prune()
        messages = sorted(item.message for item in residue)
        self.assertEqual(len(residue), 2)
        self.assertIn("external volume survives teardown", messages[0])
        self.assertIn("step failed", messages[1])


class ReadProbeTests(unittest.IsolatedAsyncioTestCase):
    """The read is a coroutine too. A coroutine assess() is awaited on the caller's loop and fanned across
    its wave, so the re-probe that proves a converge overlaps its I/O exactly as the writes do."""

    class _AsyncEyes(Step):
        # A fully async step. assess and apply are coroutines the read verbs and converge must serve.
        def __init__(self) -> None:
            self.__fixed = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        @property
        def fixed(self) -> bool:
            return self.__fixed[0]

        async def assess(self, inputs):
            await asyncio.sleep(0)
            return Assessment(deviation=[] if self.__fixed[0] else [DriftItem("eyes", "unconverged")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.__fixed[0] = True

            return None, {}
    async def test_assess_awaits_the_coroutine_read(self):
        drift = await Reconciler((self._AsyncEyes(),)).assess()
        self.assertEqual([item.message for item in drift], ["unconverged"])

    async def test_converge_reprobes_through_the_coroutine_assess(self):
        # The self-verifying loop awaits the async read. apply, then the awaited re-probe proves clean.
        step = self._AsyncEyes()
        residual = await Reconciler((step,)).converge()
        self.assertEqual(residual, [])
        self.assertTrue(step.fixed)

    async def test_a_waves_probe_overlaps_coroutine_reads_within_a_group(self):
        # Two independent async reads share one wave. Both start before either ends, which only a
        # concurrent gather produces - the read fan is real, not a serial await.
        log: list = []

        class _Peek(Step):
            async def assess(self, inputs):
                log.append(f"{self.__class__.__name__}-start")
                await asyncio.sleep(0)
                log.append(f"{self.__class__.__name__}-end")
                return Assessment(deviation=[]), {}

        class P(_Peek):
            pass

        class Q(_Peek):
            pass

        await Reconciler((P(), Q())).assess()
        starts = {log.index("P-start"), log.index("Q-start")}
        ends = {log.index("P-end"), log.index("Q-end")}
        self.assertLess(max(starts), min(ends))

    async def test_a_plain_sync_read_still_runs_inline_under_the_engine(self):
        class _PlainEyes(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("plain", "still sync")]), {}

        drift = await Reconciler((_PlainEyes(),)).assess()
        self.assertEqual([d.message for d in drift], ["still sync"])

    async def test_a_custom_waves_dispatcher_inherits_the_concurrent_probe(self):
        # A custom dispatcher composing the Waves shape gets a working coroutine read fan for free. It
        # overrides only execute, while the inherited probe awaits a coroutine read and a plain one alike.
        class Custom(WavesDispatcher):
            async def run_wave(self, level_payloads, attempt, cancellation):
                return [await attempt(payload) for payload in level_payloads]

        class _PlainEyes(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("plain", "still sync")]), {}

        drift = await Reconciler((self._AsyncEyes(), _PlainEyes()), mode=RunMode(Waves(), Custom())).assess()
        self.assertEqual(sorted(d.message for d in drift), ["still sync", "unconverged"])

    async def test_a_broken_read_waits_for_its_wave_mates_then_raises_the_group(self):
        # The read fan is a barrier even for a failure. The slow sibling read settles first (nothing left
        # running detached on the loop), THEN the wave's failures raise together as one native ExceptionGroup.
        settled = []

        class _BrokenEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("read one dies")

        class _SlowEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0.02)
                settled.append("slow settled")
                return Assessment(deviation=[]), {}

        with self.assertRaises(ExceptionGroup) as ctx:
            await Reconciler((_BrokenEyes(), _SlowEyes()), mode=Parallel()).assess()
        self.assertEqual([str(error) for error in ctx.exception.exceptions], ["read one dies"])
        self.assertEqual(settled, ["slow settled"])   # the wave settled before the raise - no detached task

    async def test_every_broken_read_in_the_wave_surfaces_in_the_one_group(self):
        # BOTH failures of one wave arrive together, resolved order inside, instead of the first-raised
        # hiding the second until the next run.
        class _FirstEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("first read dies")

        class _SecondEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0.01)
                raise TimeoutError("second read dies")

        with self.assertRaises(ExceptionGroup) as ctx:
            await Reconciler((_FirstEyes(), _SecondEyes()), mode=Parallel()).assess()
        self.assertEqual([str(error) for error in ctx.exception.exceptions],
                         ["first read dies", "second read dies"])
        self.assertIn("2 of the wave's 2 reads failed", str(ctx.exception))

    async def test_a_cancelled_abort_cuts_through_the_probe_group(self):
        # The Ledger promise holds on the read path too. A read cooperating with an abort raises the
        # kernel's Cancelled, so the abort CUTS THROUGH instead of being folded into the diagnosis.
        class _BrokenEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0)
                raise RuntimeError("read one dies")

        class _AbortingEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0.01)
                raise Cancelled("the read cooperates with an abort")

        with self.assertRaises(Cancelled):
            await Reconciler((_BrokenEyes(), _AbortingEyes()), mode=Parallel()).assess()

    async def test_a_bare_cancellederror_from_a_read_is_not_folded_into_the_group(self):
        # The cancellation protocol is not a broken read. Sifted out, it propagates as itself and a group
        # of ordinary failures stays a plain ExceptionGroup, deterministically.
        class _LeakingEyes(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0)
                raise asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            await Reconciler((_LeakingEyes(),), mode=Parallel()).assess()


class HookColourTests(unittest.IsolatedAsyncioTestCase):
    """The one engine admits both hook colours. A coroutine apply() is awaited and a plain apply() runs
    inline, side by side in one run, so a domain step is never forced to write a coroutine it does not need."""

    class _AsyncApply(Step):
        async def apply(self, inputs):
            return [], {}

    async def test_both_colours_converge_in_one_run(self):
        class PlainApply(Step):
            pass

        await Reconciler((self._AsyncApply(), PlainApply())).converge()

    def test_a_step_the_scope_narrowed_away_is_never_run(self):
        # The run reads the POST-SCOPE selection. A step narrowed out never runs whatever colour it is.
        class Kept(Step):
            pass

        reconciler = Reconciler((Kept(), self._AsyncApply()), scope=Only(Kept))
        self.assertEqual(reconciler.explain().groups, (("Kept",),))

