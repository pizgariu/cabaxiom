"""Backoff pacing for Fixpoint: Fixed and Exponential turn a stalled pass into a paced retry."""
import random
import unittest
from unittest.mock import AsyncMock, patch

from cabaxiom import (
    Assessment,
    DriftItem,
    Exponential,
    Fibonacci,
    Fixed,
    Fixpoint,
    Jitter,
    Linear,
    Reconciler,
    Step,
)
from support import RecordingBackoff


class _ClearsAfter(Step):
    # Reports the same drift until drift() has been probed `stalls` times, then clears. Models a step
    # waiting on external state. apply() does nothing new, the world settles on its own after a while.
    def __init__(self, stalls: int):
        self.__stalls = stalls
        self.__probes = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        self.__probes[0] += 1
        return Assessment(deviation=[] if self.__probes[0] > self.__stalls else [DriftItem("svc", "settling")]), {}

    def apply(self, inputs):
        return None, {}


class BackoffTests(unittest.IsolatedAsyncioTestCase):
    async def test_backoff_turns_a_stalled_pass_into_a_paced_retry(self):
        backoff = RecordingBackoff()
        residual = await Reconciler((_ClearsAfter(3),), convergence=Fixpoint(backoff=backoff)).converge()
        self.assertEqual(residual, [])             # cleared once the retries gave it time
        self.assertEqual(backoff.stalls, [1, 2])   # two consecutive stalls, each paced in turn

    async def test_without_a_backoff_the_same_stall_is_terminal(self):
        # The identical step, with no backoff, stops at the first unchanged pass instead of waiting.
        residual = await Reconciler((_ClearsAfter(3),), convergence=Fixpoint()).converge()
        self.assertEqual(len(residual), 1)

    async def test_progress_resets_the_stall_streak(self):
        # A pass that moves the residual resets the streak, so a later stall backs off from 1, not 2.
        class _TwoStalls(Step):
            def __init__(self):
                self.__probes = [0]   # a cell, since the frozen Step forbids reassigning an attribute
                self.__script = ["a", "a", "b", "b", "c"]   # stall, move, stall, move, then clear

            def assess(self, inputs):
                self.__probes[0] += 1
                if self.__probes[0] > len(self.__script):
                    return Assessment(deviation=[]), {}
                return Assessment(deviation=[DriftItem("svc", self.__script[self.__probes[0] - 1])]), {}

            def apply(self, inputs):
                return None, {}

        backoff = RecordingBackoff()
        await Reconciler((_TwoStalls(),), convergence=Fixpoint(backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, [1, 1])   # each stall episode restarts at 1, proving the reset

    async def test_a_positive_delay_is_awaited_on_the_event_loop(self):
        # A positive delay makes the engine pause before each retry (patched to stay instant), so the wait
        # the policy yields is what gets awaited on the loop, not swallowed.
        with patch("cabaxiom.reconciler.asyncio.sleep", new_callable=AsyncMock) as slept:
            residual = await Reconciler((_ClearsAfter(3),), convergence=Fixpoint(backoff=Fixed(2.5))).converge()
        self.assertEqual(residual, [])
        self.assertEqual([call.args[0] for call in slept.call_args_list], [2.5, 2.5])

    def test_fixed_waits_a_constant_duration(self):
        backoff = Fixed(2.5)
        with patch("cabaxiom.convergence.time.sleep") as slept:
            backoff.wait(1)
            backoff.wait(6)
        self.assertEqual([call.args[0] for call in slept.call_args_list], [2.5, 2.5])

    def test_exponential_doubles_each_stall_then_holds_at_the_cap(self):
        backoff = Exponential(base=1, cap=8)
        with patch("cabaxiom.convergence.time.sleep") as slept:
            for stall in range(1, 6):
                backoff.wait(stall)
        self.assertEqual([call.args[0] for call in slept.call_args_list], [1, 2, 4, 8, 8])

    def test_linear_ramps_by_a_constant_step_then_holds_at_the_cap(self):
        backoff = Linear(step=2, cap=7)
        with patch("cabaxiom.convergence.time.sleep") as slept:
            for stall in range(1, 6):
                backoff.wait(stall)
        self.assertEqual([call.args[0] for call in slept.call_args_list], [2, 4, 6, 7, 7])

    def test_fibonacci_ramps_by_the_sequence_then_holds_at_the_cap(self):
        backoff = Fibonacci(base=1, cap=8)
        with patch("cabaxiom.convergence.time.sleep") as slept:
            for stall in range(1, 8):
                backoff.wait(stall)
        self.assertEqual([call.args[0] for call in slept.call_args_list], [1, 2, 3, 5, 8, 8, 8])

    def test_fibonacci_sits_between_linear_and_exponential(self):
        # The claim the class is named for, measured rather than asserted in prose. Against the same
        # step, every Fibonacci pause is at least Linear's and at most Exponential's. The cap is put
        # out of reach so the three ramps are compared, not three flat lines at their ceiling.
        linear = Linear(step=1, cap=10**9)
        fibonacci = Fibonacci(base=1, cap=10**9)
        exponential = Exponential(base=1, cap=10**9)
        for stall in range(1, 13):
            with self.subTest(stalled=stall):
                self.assertGreaterEqual(fibonacci.delay(stall), linear.delay(stall))
                self.assertLessEqual(fibonacci.delay(stall), exponential.delay(stall))

    def test_fibonacci_reaches_the_cap_a_stall_after_exponential(self):
        # The gap that makes it worth having. With the same base and cap, the doubling is flat from its
        # fourth stall on and the sequence is still climbing, so the ramp still says something there.
        fibonacci = Fibonacci(base=1, cap=8)
        exponential = Exponential(base=1, cap=8)
        self.assertEqual(exponential.delay(4), 8)   # doubling is on the cap
        self.assertEqual(fibonacci.delay(4), 5)     # the sequence has one climb left
        self.assertEqual(fibonacci.delay(5), 8)

    def test_fibonacci_holds_a_far_stall_at_the_cap_without_walking_there(self):
        # A stall count no loop would ever reach still answers the cap, because the walk stops the
        # moment the ramp has met it instead of generating terms that cannot change the answer.
        self.assertEqual(Fibonacci(base=1, cap=8).delay(10_000), 8)

    def test_fixed_rejects_a_negative_delay(self):
        with self.assertRaises(ValueError):
            Fixed(-1)

    def test_exponential_rejects_a_negative_base(self):
        with self.assertRaises(ValueError):
            Exponential(base=-1, cap=10)

    def test_exponential_rejects_a_cap_below_base(self):
        with self.assertRaises(ValueError):
            Exponential(base=5, cap=1)

    def test_linear_rejects_a_negative_step(self):
        with self.assertRaises(ValueError):
            Linear(step=-1, cap=10)

    def test_linear_rejects_a_cap_below_step(self):
        with self.assertRaises(ValueError):
            Linear(step=5, cap=1)

    def test_fibonacci_rejects_a_negative_base(self):
        with self.assertRaises(ValueError):
            Fibonacci(base=-1, cap=10)

    def test_fibonacci_rejects_a_cap_below_base(self):
        with self.assertRaises(ValueError):
            Fibonacci(base=5, cap=1)

    async def test_fibonacci_paces_a_stalled_fixpoint(self):
        # It is a Backoff like any other, so Fixpoint takes it and a stalled pass becomes a paced retry.
        with patch("cabaxiom.reconciler.asyncio.sleep", new_callable=AsyncMock) as slept:
            residual = await Reconciler((_ClearsAfter(3),),
                                        convergence=Fixpoint(backoff=Fibonacci(base=1, cap=8))).converge()
        self.assertEqual(residual, [])
        self.assertEqual([call.args[0] for call in slept.call_args_list], [1, 2])


class JitterTests(unittest.IsolatedAsyncioTestCase):
    def test_jitter_spreads_within_the_wrapped_ceiling(self):
        inner = Exponential(base=1, cap=8)
        jitter = Jitter(inner, rng=random.Random(1234))
        for stall in range(1, 6):
            drawn = jitter.delay(stall)
            self.assertGreaterEqual(drawn, 0.0)
            self.assertLessEqual(drawn, inner.delay(stall))   # never exceeds the wrapped policy's ceiling

    def test_jitter_is_deterministic_under_a_seeded_rng(self):
        # Same seed, same draw. A test (or a reproducible run) can pin the jitter.
        first = Jitter(Fixed(1.0), rng=random.Random(7)).delay(1)
        second = Jitter(Fixed(1.0), rng=random.Random(7)).delay(1)
        self.assertEqual(first, second)

    def test_jitter_defaults_to_its_own_rng(self):
        drawn = Jitter(Fixed(2.0)).delay(1)   # no rng given -> a fresh random.Random()
        self.assertGreaterEqual(drawn, 0.0)
        self.assertLessEqual(drawn, 2.0)

