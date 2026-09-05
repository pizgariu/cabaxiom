"""Settle - when a standing run is finished, asked once per pass with that pass's residual."""
import unittest

from cabaxiom import Clean, DriftItem, Settle, Stable


class CleanTests(unittest.TestCase):

    def test_one_clean_pass_is_the_whole_proof(self):
        self.assertTrue(Clean().settled([]))

    def test_a_pass_that_left_something_is_not_done(self):
        self.assertFalse(Clean().settled([DriftItem("svc", "still wrong")]))


class StableTests(unittest.TestCase):

    def test_it_waits_for_consecutive_clean_passes(self):
        settle = Stable(2)
        self.assertFalse(settle.settled([]))
        self.assertTrue(settle.settled([]))

    def test_a_dirty_pass_resets_the_streak_rather_than_pausing_it(self):
        # Consecutive means consecutive. A world with slow external actors can give one clean reading in
        # the gap between two writes somebody else is making, which is the case this exists for.
        settle = Stable(2)
        self.assertEqual([settle.settled(reading) for reading in
                          ([], [DriftItem("svc", "moved")], [], [])],
                         [False, False, False, True])

    def test_one_pass_is_refused_rather_than_being_a_synonym(self):
        # Stable(1) is Clean with more ceremony, so it says so instead of quietly agreeing.
        with self.assertRaises(ValueError) as refused:
            Stable(1)
        self.assertIn("Clean()", str(refused.exception))


class TheAxisTests(unittest.TestCase):

    def test_a_domain_can_say_never(self):
        # A monitor is never done and says so by never returning True. That is the reason this is an
        # injected axis and not a flag on the loop.
        class Never(Settle):
            def settled(self, residual):
                return False

        self.assertFalse(Never().settled([]))
