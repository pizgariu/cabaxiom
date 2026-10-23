"""Settle - the outer-loop stop condition, decided across converge() passes. Clean stops on the first
clean pass, Stable(k) only after k CONSECUTIVE clean ones - the difference between "converged once" and
"stayed converged", which is what a flapping world exists to fake."""
import unittest

from cabaxiom import Clean, DriftItem, Stable


class CleanTests(unittest.TestCase):
    def test_it_stops_on_the_first_clean_pass_and_not_before(self):
        loop = Clean().watch()
        self.assertFalse(next(loop))                                  # primed: no pass has run yet
        self.assertFalse(loop.send([DriftItem("svc", "still wrong")]))   # a dirty pass keeps going
        self.assertTrue(loop.send([]))                                # the first clean pass is the stop


class StableTests(unittest.TestCase):
    def test_it_demands_the_streak_and_a_dirty_pass_resets_it(self):
        # The flapping world - clean, then dirty, then clean again. A single clean re-probe is a false
        # all-clear, so the streak starts OVER after the flap instead of resuming where it left off.
        loop = Stable(2).watch()
        self.assertFalse(next(loop))
        self.assertFalse(loop.send([]))                               # clean, streak 1 of 2
        self.assertFalse(loop.send([DriftItem("svc", "flapped")]))    # dirty: streak back to zero
        self.assertFalse(loop.send([]))                               # clean again, streak 1 of 2
        self.assertTrue(loop.send([]))                                # streak 2 of 2: stable, stop

    def test_stable_of_one_is_clean(self):
        # The documented degenerate case, pinned so the boundary cannot drift. One required clean pass is
        # exactly Clean's rule.
        loop = Stable(1).watch()
        self.assertFalse(next(loop))
        self.assertTrue(loop.send([]))

    def test_a_streak_of_less_than_one_is_refused(self):
        with self.assertRaises(ValueError) as refused:
            Stable(0)
        self.assertIn("Stable passes must be >= 1, got 0", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
