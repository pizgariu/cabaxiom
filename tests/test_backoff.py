"""Backoff pacing for Fixpoint: Fixed and Exponential turn a stalled pass into a paced retry."""
import random
import unittest
from unittest.mock import patch

from cabaxiom import Assessment, Backoff, DriftItem, Exponential, Fixed, Fixpoint, Jitter, Reconciler, Step


class _ClearsAfter(Step):
    # Reports the same drift until drift() has been probed `stalls` times, then clears. Models a step
    # waiting on external state: apply() does nothing new, the world settles on its own after a while.
    def __init__(self, stalls: int):
        self.__stalls = stalls
        self.__probes = [0]

    def assess(self) -> list:
        self.__probes[0] += 1
        return Assessment(deviation=[] if self.__probes[0] > self.__stalls else [DriftItem("svc", "settling")])

    def apply(self) -> None:
        return None


class _Recording(Backoff):
    # Records the stall count handed to each pause and pauses for nothing, so a test stays instant.
    def __init__(self):
        self.waits: list[int] = []

    def delay(self, stalled: int) -> float:
        self.waits.append(stalled)
        return 0.0


class BackoffTests(unittest.TestCase):
    def test_backoff_turns_a_stalled_pass_into_a_paced_retry(self):
        backoff = _Recording()
        residual = Reconciler((_ClearsAfter(3),), convergence=Fixpoint(backoff=backoff)).converge()
        self.assertEqual(residual, [])              # cleared once the retries gave it time
        self.assertEqual(backoff.waits, [1, 2])     # two consecutive stalls, each paced in turn

    def test_without_a_backoff_the_same_stall_is_terminal(self):
        # The identical step, with no backoff, stops at the first unchanged pass instead of waiting.
        residual = Reconciler((_ClearsAfter(3),), convergence=Fixpoint()).converge()
        self.assertEqual(len(residual), 1)

    def test_progress_resets_the_stall_streak(self):
        # A pass that moves the residual resets the streak, so a later stall backs off from 1, not 2.
        class _TwoStalls(Step):
            def __init__(self):
                self.__probes = [0]
                self.__script = [["a", "a", "b", "b", "c"]]   # stall, move, stall, move, then clear

            def assess(self) -> list:
                self.__probes[0] += 1
                if self.__probes[0] > len(self.__script[0]):
                    return Assessment(deviation=[])
                return Assessment(deviation=[DriftItem("svc", self.__script[0][self.__probes[0] - 1])])

            def apply(self) -> None:
                return None

        backoff = _Recording()
        Reconciler((_TwoStalls(),), convergence=Fixpoint(backoff=backoff)).converge()
        self.assertEqual(backoff.waits, [1, 1])   # each stall episode restarts at 1, proving the reset

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

    def test_fixed_rejects_a_negative_delay(self):
        with self.assertRaises(ValueError):
            Fixed(-1)

    def test_exponential_rejects_a_negative_base(self):
        with self.assertRaises(ValueError):
            Exponential(base=-1, cap=10)

    def test_exponential_rejects_a_cap_below_base(self):
        with self.assertRaises(ValueError):
            Exponential(base=5, cap=1)


class JitterTests(unittest.TestCase):
    def test_jitter_spreads_within_the_wrapped_ceiling(self):
        inner = Exponential(base=1, cap=8)
        jitter = Jitter(inner, rng=random.Random(1234))
        for stall in range(1, 6):
            drawn = jitter.delay(stall)
            self.assertGreaterEqual(drawn, 0.0)
            self.assertLessEqual(drawn, inner.delay(stall))   # never exceeds the wrapped policy's ceiling

    def test_jitter_is_deterministic_under_a_seeded_rng(self):
        # Same seed, same draw: a test (or a reproducible run) can pin the jitter.
        first = Jitter(Fixed(1.0), rng=random.Random(7)).delay(1)
        second = Jitter(Fixed(1.0), rng=random.Random(7)).delay(1)
        self.assertEqual(first, second)

    def test_jitter_defaults_to_its_own_rng(self):
        drawn = Jitter(Fixed(2.0)).delay(1)   # no rng given -> a fresh random.Random()
        self.assertGreaterEqual(drawn, 0.0)
        self.assertLessEqual(drawn, 2.0)
