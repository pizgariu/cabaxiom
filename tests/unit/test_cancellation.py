"""Cancellation signals and Quorum composition."""
import asyncio
import time
import unittest

from cabaxiom import (
    Assessment,
    Cancelled,
    Deadline,
    DriftItem,
    Every,
    Flag,
    Kahn,
    OnError,
    Parallel,
    Reconciler,
    Step,
    Supervised,
    ThreadDispatcher,
)
from cabaxiom.core.declaration import AllOf, AnyOf, Cancellation, Majority, Most, Quorum
from support import A, B, C


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    """The injected Cancellation. The executor checks it before each step (Parallel) or level (Parallel)
    and raises Cancelled. The default never cancels, so an un-configured Reconciler is unaffected."""

    class _CancelAfter(Cancellation):
        # Cancels once it has been checked more than `checks_allowed` times.
        def __init__(self, checks_allowed: int):
            self.__allowed = checks_allowed
            self.__seen = 0

        def cancelled(self) -> bool:
            self.__seen += 1
            return self.__seen > self.__allowed

    async def test_default_never_cancels(self):
        log = []
        await Reconciler((A(log), B(log), C(log))).converge()
        self.assertEqual(log, ["A", "B", "C"])

    async def test_cancellation_aborts_a_run_before_the_next_step(self):
        log = []
        with self.assertRaises(Cancelled):
            await Reconciler((A(log), B(log), C(log)), cancellation=self._CancelAfter(2)).converge()
        self.assertEqual(log, ["A", "B"])   # checked before C, raised, C never ran

    async def test_cancellation_is_consulted_before_each_step_of_a_wave(self):
        log = []
        with self.assertRaises(Cancelled):
            await Reconciler((A(log), B(log), C(log)), Kahn(), mode=Parallel(),
                             cancellation=self._CancelAfter(1)).converge()
        self.assertEqual(log, ["A"])   # A ran, checked before B, raised

    async def test_deadline_zero_cancels_before_the_first_step(self):
        log = []
        with self.assertRaises(Cancelled):
            await Reconciler((A(log),), cancellation=Deadline(0)).converge()
        self.assertEqual(log, [])

    def test_deadline_rejects_negative_seconds(self):
        # Deadline validates its budget the way Fixpoint validates max_passes - a negative deadline is a bug.
        with self.assertRaises(ValueError):
            Deadline(-1)

    def test_deadline_clock_starts_once_and_reuses_it_across_checks(self):
        # The clock starts on the FIRST check, so construction-to-run latency is not billed. A second check
        # within budget reuses that started stamp instead of restarting it - the already-started branch.
        deadline = Deadline(1000)
        self.assertFalse(deadline.cancelled())   # first check starts the clock, well within budget
        self.assertFalse(deadline.cancelled())   # second check reuses the started stamp, still within budget

    async def test_flag_cancels_when_set(self):
        flag = Flag()
        flag.cancel()
        log = []
        with self.assertRaises(Cancelled):
            await Reconciler((A(log),), cancellation=flag).converge()
        self.assertEqual(log, [])

    async def test_cancelled_names_the_cancellation_that_fired(self):
        # The executor knows WHICH cancellation it consulted - the exception says so, for any consumer
        # that lets it reach a traceback or a log.
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as caught:
            await Reconciler((A([]),), cancellation=flag).converge()
        self.assertIn("Flag", str(caught.exception))

    async def test_partial_run_is_idempotent_and_resumes(self):
        # After a cancelled converge, a clean re-run completes the rest - steps are idempotent.
        log = []
        steps = (A(log), B(log), C(log))
        with self.assertRaises(Cancelled):
            await Reconciler(steps, cancellation=self._CancelAfter(2)).converge()
        await Reconciler(steps).converge()   # resume, no cancellation
        self.assertEqual(log.count("C"), 1)


class StepRaisedCancelledTests(unittest.IsolatedAsyncioTestCase):
    """A step-raised Cancelled cuts through BestEffort. An abort is a decision, not a failure, so it must
    never be swallowed into the residual as 'step failed: Cancelled'. It holds for a sync apply run inline
    and for an async apply the wave awaits."""

    class _Aborting(Step):
        # A step observing its own cooperative abort mid-write.
        def apply(self, inputs):
            raise Cancelled("step observed the abort")

    class _AsyncAborting(Step):
        async def apply(self, inputs):
            await asyncio.sleep(0)
            raise Cancelled("step observed the abort")

    async def test_cancelled_cuts_through_best_effort_on_the_default_dispatcher(self):
        with self.assertRaises(Cancelled):
            await Reconciler((self._Aborting(),), mode=Parallel(OnError.BestEffort)).converge()

    async def test_cancelled_cuts_through_best_effort_under_explicit_kahn(self):
        with self.assertRaises(Cancelled):
            await Reconciler((self._Aborting(),), Kahn(), mode=Parallel(OnError.BestEffort)).converge()

    async def test_cancelled_cuts_through_best_effort_for_an_async_apply(self):
        with self.assertRaises(Cancelled):
            await Reconciler((self._AsyncAborting(),), Kahn(), mode=Parallel(OnError.BestEffort)).converge()


class QuorumTests(unittest.IsolatedAsyncioTestCase):
    """Quorum is a composite Cancellation that fires when an injected Rule is met across its members:
    Some (any fired, the default), Every (all fired), Most (strict majority). Quorum is itself a
    Cancellation, so it nests and drops straight into a Reconciler."""

    @staticmethod
    def __fired() -> Flag:
        flag = Flag()
        flag.cancel()
        return flag

    def test_some_is_the_default_and_fires_on_any(self):
        self.assertTrue(Quorum(Cancellation(), self.__fired()).cancelled())    # one member fired -> cancel
        self.assertFalse(Quorum(Cancellation(), Cancellation()).cancelled())   # none fired -> continue

    def test_every_fires_only_when_all_fired(self):
        self.assertFalse(Quorum(self.__fired(), Cancellation(), rule=Every()).cancelled())
        self.assertTrue(Quorum(self.__fired(), self.__fired(), rule=Every()).cancelled())

    def test_most_needs_a_strict_majority(self):
        self.assertTrue(Quorum(self.__fired(), self.__fired(), Cancellation(), rule=Most()).cancelled())   # 2 of 3
        self.assertFalse(Quorum(self.__fired(), Cancellation(), rule=Most()).cancelled())                  # 1 of 2, a tie does not cancel

    def test_some_short_circuits_over_a_generator(self):
        # Quorum polls members lazily, so Some stops at the first that fired without touching the rest.
        polled = []

        class Watching(Cancellation):
            def __init__(self, name, fires):
                self.__name = name
                self.__fires = fires

            def cancelled(self) -> bool:
                polled.append(self.__name)
                return self.__fires

        self.assertTrue(Quorum(Watching("a", True), Watching("b", True)).cancelled())
        self.assertEqual(polled, ["a"])   # b never polled - short-circuited on a

    def test_empty_quorum_is_rejected(self):
        with self.assertRaises(ValueError):
            Quorum()

    async def test_quorum_is_a_cancellation_that_nests_and_threads_into_a_run(self):
        log = []
        with self.assertRaises(Cancelled):
            await Reconciler((A(log),), cancellation=Quorum(Deadline(30), self.__fired())).converge()
        self.assertEqual(log, [])


class CombinatorTests(unittest.IsolatedAsyncioTestCase):
    """AnyOf, AllOf and Majority are named Quorum shortcuts with a rule baked in. Each is a Cancellation
    itself, so it nests into a tree exactly as a raw Quorum does."""

    @staticmethod
    def __fired() -> Flag:
        flag = Flag()
        flag.cancel()
        return flag

    def test_anyof_fires_when_any_member_fires(self):
        self.assertTrue(AnyOf(Cancellation(), self.__fired()).cancelled())
        self.assertFalse(AnyOf(Cancellation(), Cancellation()).cancelled())

    def test_allof_fires_only_when_every_member_fires(self):
        self.assertFalse(AllOf(self.__fired(), Cancellation()).cancelled())
        self.assertTrue(AllOf(self.__fired(), self.__fired()).cancelled())

    def test_majority_needs_a_strict_majority(self):
        self.assertTrue(Majority(self.__fired(), self.__fired(), Cancellation()).cancelled())   # 2 of 3
        self.assertFalse(Majority(self.__fired(), Cancellation()).cancelled())                  # 1 of 2, a tie holds

    def test_combinators_nest_into_a_tree(self):
        # The inner AllOf is a member of the outer AnyOf, so the outer fires when the inner does.
        self.assertTrue(AnyOf(Cancellation(), AllOf(self.__fired(), self.__fired())).cancelled())
        self.assertFalse(AnyOf(Cancellation(), AllOf(self.__fired(), Cancellation())).cancelled())

    def test_an_empty_combinator_is_rejected(self):
        with self.assertRaises(ValueError):
            AnyOf()



class AbortIsABaseExceptionTests(unittest.IsolatedAsyncioTestCase):
    """Cancelled re-parents under BaseException, the KeyboardInterrupt precedent. An abort is a decision,
    so a domain hook's ordinary `except Exception` structurally cannot swallow it any more."""

    async def test_a_hook_catching_exception_cannot_swallow_an_abort(self):
        # The whole point of the re-parent, measured. This step tries to eat every failure, where the
        # abort still cuts through it.
        class Swallows(Step):
            def apply(self, inputs):
                try:
                    raise Cancelled("the run is being stopped")
                except Exception:   # the greedy domain catch that used to eat the abort
                    pass

                return None, {}
        with self.assertRaises(Cancelled):
            await Reconciler((Swallows(),)).converge()
    def test_a_wave_abort_leaves_the_group_as_the_abort_itself(self):
        # A step raising Cancelled under the async wave cancels its wave-mates eagerly, so what reaches
        # the caller is Cancelled - the caller's contract - never a group wrapping one.
        class Aborts(Step):
            async def apply(self, inputs):
                raise Cancelled("step observed the abort")

                return None, {}
        with self.assertRaises(Cancelled):
            asyncio.run(Reconciler((Aborts(),)).converge())

    def test_a_foreign_base_exception_keeps_its_group(self):
        # Only a PURE abort unwraps. A BaseException that is not the kernel's abort is not the kernel's
        # protocol, so it propagates as the group the TaskGroup made - nothing is guessed about it.
        class Escapes(BaseException):
            pass

        class Raises(Step):
            async def apply(self, inputs):
                raise Escapes()

                return None, {}
        with self.assertRaises(BaseExceptionGroup) as caught:
            asyncio.run(Reconciler((Raises(),)).converge())
        self.assertIsInstance(caught.exception.exceptions[0], Escapes)


class CancellableProbeTests(unittest.IsolatedAsyncioTestCase):
    """The probe as a first-class citizen of cancellation, which it was not.

    execute() checked the Cancellation between waves and Supervised watched a write wave in flight, while
    probe() took no Cancellation at all - so a Deadline bounded the work and never the proof, so a converge
    under Supervised could hang forever in its own re-probe. Single-try is the read side's contract because
    the probe is the run's proof, yet single-try was never supposed to mean uncancellable. These pin the
    citizenship at each of the places it now exists."""

    async def test_a_deadline_bounds_a_hung_read_under_supervised(self):
        # THE hole. A read that never returns, a Deadline that fires, where before this the probe's fan waited
        # on the read forever - the deadline had nothing to interrupt it with.
        class Hung(Step):
            async def assess(self, inputs):
                await asyncio.Event().wait()   # never set, never returns

            def apply(self, inputs):
                return None, {}

        run = Reconciler((Hung(),), mode=Supervised(poll=0.01, grace=0.05),
                         cancellation=Deadline(0.05))
        started = time.monotonic()
        with self.assertRaises(Cancelled):
            await run.assess()
        self.assertLess(time.monotonic() - started, 5.0)   # bounded, not eternal

    async def test_a_cancellation_between_read_waves_stops_the_later_wave(self):
        # The between-wave check, same as the write side's. The first wave's read flips the flag, so the
        # dependent wave never reads at all.
        flag = Flag()
        seen: list[str] = []

        class First(Step):
            def assess(self, inputs):
                seen.append("first")
                flag.cancel()
                return Assessment(), {}

            def apply(self, inputs):
                return None, {}

        class Second(Step):
            expects = (First,)

            def assess(self, inputs):
                seen.append("second")
                return Assessment(), {}

            def apply(self, inputs):
                return None, {}

        with self.assertRaises(Cancelled):
            await Reconciler((First(), Second()), cancellation=flag).assess()
        self.assertEqual(seen, ["first"])

    async def test_the_bridges_carry_the_cancellation_through(self):
        # ThreadDispatcher and the chaos decorator both delegate, so a flag already up refuses the probe
        # before any read runs - through however many layers are composed.
        from cabaxiom.laboratory import ChaosDispatcher, Sabotage

        class Quiet(Step):
            def assess(self, inputs):
                return Assessment(), {}

            def apply(self, inputs):
                return None, {}

        raised = Flag()
        raised.cancel()
        for dispatcher in (ThreadDispatcher(), ChaosDispatcher(Parallel(), Sabotage(abort_rate=0.0, drop_rate=0.0))):
            with self.subTest(mode=type(dispatcher).__name__):
                with self.assertRaises(Cancelled):
                    await Reconciler((Quiet(),), mode=dispatcher, cancellation=raised).assess()

    async def test_an_async_read_under_the_thread_bridge_is_awaited_not_mangled(self):
        # The bug found while wiring this. The write bridge tolerated both colours and the read bridge did
        # not, so an async step's assess() under ThreadDispatcher came back as an unawaited coroutine and
        # the probe fell over unpacking it.
        class Both(Step):
            async def assess(self, inputs):
                await asyncio.sleep(0)
                return Assessment(deviation=[DriftItem("both", "unsettled")]), {}

            def apply(self, inputs):
                return None, {}

        reading = await Reconciler((Both(),), mode=ThreadDispatcher()).assess()
        self.assertEqual([item.message for item in reading], ["unsettled"])

    async def test_a_supervised_probe_still_raises_broken_reads_together(self):
        # The read side's own error contract survives the supervision. Two broken reads in one wave arrive
        # as ONE ExceptionGroup, not as the first one to settle - supervision changed who watches the wave,
        # never what a broken read means.
        class BrokenA(Step):
            def assess(self, inputs):
                raise RuntimeError("a broke")

            def apply(self, inputs):
                return None, {}

        class BrokenB(Step):
            def assess(self, inputs):
                raise RuntimeError("b broke")

            def apply(self, inputs):
                return None, {}

        with self.assertRaises(BaseExceptionGroup) as raised:
            await Reconciler((BrokenA(), BrokenB()), mode=Supervised(poll=0.01)).assess()
        self.assertEqual(len(raised.exception.exceptions), 2)
