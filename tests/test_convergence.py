"""Once single pass versus Fixpoint loop-to-settle versus Shrinking loop-while-smaller versus Budget
loop-while-there-is-time."""
import unittest

from cabaxiom import Assessment, Budget, DriftItem, Fixpoint, Reconciler, Shrinking, Step
from support import RecordingBackoff, Staged


class ConvergenceTests(unittest.IsolatedAsyncioTestCase):
    """The injected Convergence: Once (default, single pass) vs Fixpoint (loop to a fixed point)."""

    async def test_once_is_the_default_single_pass(self):
        step = Staged(3)
        residual = await Reconciler((step,)).converge()    # one apply only
        self.assertEqual(step.remaining, 2)
        self.assertEqual(len(residual), 1)

    async def test_fixpoint_loops_until_clean(self):
        step = Staged(3)
        residual = await Reconciler((step,), convergence=Fixpoint()).converge()
        self.assertEqual(step.remaining, 0)
        self.assertEqual(residual, [])

    async def test_applied_accumulates_across_fixpoint_passes(self):
        # The applied channel carries EVERY productive pass, not just the last (the accumulator is closed
        # over the cycle closure), while a settled apply() that returns None adds nothing - so no overcount.
        class StagedRecording(Step):
            def __init__(self, passes):
                self.__remaining = [passes]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__remaining[0] == 0 else [DriftItem("staged", "more to do")]), {}

            def apply(self, inputs):
                if self.__remaining[0] == 0:
                    return None, {}
                self.__remaining[0] -= 1
                return [DriftItem("staged", "did a pass")], {}

        residual = await Reconciler((StagedRecording(2),), convergence=Fixpoint()).converge()
        self.assertEqual(residual, [])               # settled clean
        self.assertEqual(len(residual.applied), 2)   # both productive passes accumulated, no overcount

    async def test_fixpoint_stops_early_when_a_pass_changes_nothing(self):
        # A stuck step settles after the SECOND pass shows no change, not after every max_pass.
        applies = []

        class Stuck(Step):
            def apply(self, inputs):
                applies.append(1)

                return None, {}
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "stuck")]), {}

        residual = await Reconciler((Stuck(),), convergence=Fixpoint(max_passes=10)).converge()
        self.assertEqual(len(applies), 2)            # stopped at 2, not 10
        self.assertEqual(len(residual), 1)

    async def test_fixpoint_respects_the_max_passes_ceiling(self):
        # Residual changes every pass (never settles) -> Fixpoint stops at the ceiling, guaranteed.
        applies = []

        class NeverSettles(Step):
            def apply(self, inputs):
                applies.append(1)

                return None, {}
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("n", f"pass {len(applies)}")]), {}   # always a different message

        await Reconciler((NeverSettles(),), convergence=Fixpoint(max_passes=4)).converge()
        self.assertEqual(len(applies), 4)

    async def test_fixpoint_stops_on_an_oscillation_a_stall_check_would_miss(self):
        # The residual flips between two states forever (A, B, A, B, ...), so no two adjacent passes match
        # and the stall check never fires. Remembering every state seen catches the return to A and stops,
        # instead of spinning all the way to max_passes.
        applies = []

        class Oscillator(Step):
            def apply(self, inputs):
                applies.append(1)

                return None, {}
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("x", "odd" if len(applies) % 2 else "even")]), {}   # alternates, never clean

        residual = await Reconciler((Oscillator(),), convergence=Fixpoint(max_passes=10)).converge()
        self.assertEqual(len(applies), 3)    # A, B, then A again -> loop caught at pass 3, not 10
        self.assertEqual(len(residual), 1)   # still non-empty: an oscillation never converges

    def test_fixpoint_max_passes_must_be_positive(self):
        for bad in (0, -1):
            with self.subTest(max_passes=bad):
                with self.assertRaises(ValueError):
                    Fixpoint(max_passes=bad)


class ShrinkingTests(unittest.IsolatedAsyncioTestCase):
    """Shrinking loops only while the residual COUNT keeps falling. It converges a strictly reducible
    world, stopping the instant a pass buys no ground (a plateau or a growth) rather than churning on."""

    class Melting(Step):
        """Reports `size` drift items and removes exactly one per apply(), so the residual count falls
        by one each pass - the strictly reducible world Shrinking is for."""

        def __init__(self, size: int):
            self.__size = [size]   # a cell, since the frozen Step forbids reassigning an attribute

        @property
        def size(self) -> int:
            return self.__size[0]

        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("melt", f"item {i}") for i in range(self.__size[0])]), {}

        def apply(self, inputs):
            if self.__size[0]:
                self.__size[0] -= 1
            return None, {}
    async def test_shrinking_loops_while_the_residual_gets_smaller(self):
        step = self.Melting(3)
        residual = await Reconciler((step,), convergence=Shrinking()).converge()
        self.assertEqual(step.size, 0)
        self.assertEqual(residual, [])          # a strictly falling count runs all the way to clean

    async def test_shrinking_stops_when_the_count_plateaus_even_as_the_set_churns(self):
        # Two drift items whose messages advance every probe. The SET changes each pass but the COUNT
        # holds at two. Fixpoint would churn on (never an equal pass). Shrinking stops at the plateau.
        applies = []

        class Churning(Step):
            def __init__(self):
                self.__n = [0]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("c", f"a{self.__n[0]}"), DriftItem("c", f"b{self.__n[0]}")]), {}

            def apply(self, inputs):
                self.__n[0] += 1
                applies.append(1)

                return None, {}
        residual = await Reconciler((Churning(),), convergence=Shrinking(max_passes=10)).converge()
        self.assertEqual(len(applies), 2)    # first pass, then one plateau pass -> stop, not to 10
        self.assertEqual(len(residual), 2)   # the count never fell, so the drift is still there

    async def test_shrinking_stops_when_the_residual_grows(self):
        # A residual that gets bigger is terminal. Progress went backwards, so another pass is not trusted.
        applies = []

        class Growing(Step):
            def __init__(self):
                self.__size = [2]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("g", f"item {i}") for i in range(self.__size[0])]), {}

            def apply(self, inputs):
                self.__size[0] += 1
                applies.append(1)

                return None, {}
        residual = await Reconciler((Growing(),), convergence=Shrinking(max_passes=10)).converge()
        self.assertEqual(len(applies), 2)    # first pass, then a bigger one -> stop
        self.assertEqual(len(residual), 4)   # 2 -> 3 (first apply) -> 4 (second apply), then terminal

    async def test_shrinking_respects_the_max_passes_ceiling(self):
        # A count that keeps falling but has further to go than the ceiling stops at max_passes, guaranteed.
        step = self.Melting(20)
        residual = await Reconciler((step,), convergence=Shrinking(max_passes=4)).converge()
        self.assertEqual(step.size, 16)         # 20 -> 16 across exactly four passes
        self.assertEqual(len(residual), 16)

    def test_shrinking_max_passes_must_be_positive(self):
        for bad in (0, -1):
            with self.subTest(max_passes=bad):
                with self.assertRaises(ValueError):
                    Shrinking(max_passes=bad)


class _Ticking:
    """A scripted monotonic clock. Every read hands back the next tick, so each pass costs exactly `step`
    seconds of the window and a test pins how many passes a budget buys without sleeping through one.
    Budget reads it once to open the window and once before every further pass."""

    def __init__(self, step=1.0):
        self.__step = step
        self.__now = 0.0

    def __call__(self) -> float:
        now = self.__now
        self.__now += self.__step
        return now


class _NeverSettles(Step):
    """Drift that never clears and never changes - the world Budget is for, where a stall means the
    external state has not caught up yet rather than that the run is finished. `applies` counts passes."""

    def __init__(self):
        self.__applies = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    @property
    def applies(self) -> int:
        return self.__applies[0]

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("svc", "waiting on the world")]), {}

    def apply(self, inputs):
        self.__applies[0] += 1
        return None, {}


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    """Budget loops while there is time left on an injected clock - a bound in SECONDS, the complement to
    Fixpoint's bound in passes. It always buys one pass, never stops on a stall and never claims
    to bound the pass already in flight."""

    async def test_budget_loops_while_there_is_time_left(self):
        step = Staged(3)
        residual = await Reconciler((step,), convergence=Budget(10, clock=_Ticking(1.0))).converge()
        self.assertEqual(step.remaining, 0)
        self.assertEqual(residual, [])          # a window with room to spare converges like Fixpoint

    async def test_budget_stops_the_moment_the_residual_is_clean(self):
        # Clean ends the loop before the window does, so a settled world does not burn the remaining time
        # re-probing itself. Staged(1) clears on its first apply, so one pass is all it takes.
        clock = _Ticking(1.0)
        residual = await Reconciler((Staged(1),), convergence=Budget(1000, clock=clock)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(clock(), 1.0)          # opened the window, then never looked at the clock again

    async def test_budget_stops_when_the_window_closes(self):
        # Three seconds at a second a pass buys three passes, then the window shuts on drift that is
        # still there. The residual is returned, never raised - a Convergence reports, it does not abort.
        step = _NeverSettles()
        residual = await Reconciler((step,), convergence=Budget(3, clock=_Ticking(1.0))).converge()
        self.assertEqual(step.applies, 3)
        self.assertEqual(len(residual), 1)

    async def test_budget_does_not_stop_on_a_stall_the_way_fixpoint_does(self):
        # The semantic that separates the two. An unchanged pass is terminal for Fixpoint (settled or
        # stuck) and is merely a pass for Budget, whose case is drift that clears once the world catches
        # up. Same step, same run, the count of passes is the whole difference.
        paced = _NeverSettles()
        await Reconciler((paced,), convergence=Budget(4, clock=_Ticking(1.0))).converge()
        settling = _NeverSettles()
        await Reconciler((settling,), convergence=Fixpoint(max_passes=10)).converge()
        self.assertEqual(paced.applies, 4)      # spent the window
        self.assertEqual(settling.applies, 2)   # stopped at the first unchanged pass

    async def test_budget_takes_one_pass_even_on_a_zero_budget(self):
        # A window of zero degrades to Once, not to nothing. The pass is taken BEFORE the clock is
        # consulted, so a budget computed from a schedule that arrives at zero still looks at the world
        # instead of reporting a clean residual for a world nobody probed. The real clock is used here on
        # purpose, since zero seconds of it elapse and the semantics must hold for the shipped default.
        step = Staged(3)
        residual = await Reconciler((step,), convergence=Budget(0)).converge()
        self.assertEqual(step.remaining, 2)     # exactly one apply, the same as Once
        self.assertEqual(len(residual), 1)

    def test_budget_rejects_a_negative_window(self):
        # A negative window is a caller bug rather than a policy, refused the way Deadline and max_passes
        # refuse theirs, instead of being quietly rounded up to the one free pass.
        for bad in (-1, -0.5):
            with self.subTest(seconds=bad):
                with self.assertRaises(ValueError):
                    Budget(bad)

    async def test_budget_paces_its_passes_with_a_backoff(self):
        # Without a pace the loop re-probes as fast as the machine allows and spends the window hammering.
        # With one, each further pass is paced by the number of passes already taken, there being no stall
        # streak here to count. The pause before the second pass is delay(1).
        backoff = RecordingBackoff()
        await Reconciler((_NeverSettles(),), convergence=Budget(3, backoff=backoff, clock=_Ticking(1.0))).converge()
        self.assertEqual(backoff.stalls, [1, 2])

    async def test_the_window_is_fresh_for_every_run(self):
        # The clock is read inside passes(), which is asked for once per converge(), so one Budget instance
        # gives every run its own full window. A Deadline reused this way cancels every run after the first.
        budget = Budget(2, clock=_Ticking(1.0))
        first = _NeverSettles()
        await Reconciler((first,), convergence=budget).converge()
        second = _NeverSettles()
        await Reconciler((second,), convergence=budget).converge()
        self.assertEqual((first.applies, second.applies), (2, 2))
