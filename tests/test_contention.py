"""contends - mutual exclusion, which is a seating rule and never an ordering."""
import unittest

from cabaxiom import Step
from cabaxiom.vocabulary import Vocabulary


class ContentionIsNotAnEdgeTests(unittest.TestCase):

    def test_a_step_declares_what_it_contends_for(self):
        class Writer(Step):
            contends = frozenset({"disk"})

        self.assertEqual(Writer().contends, frozenset({"disk"}))

    def test_contention_is_absent_from_the_edge_language(self):
        # The point of the slot. An edge says which of two steps comes first. Contention says neither may
        # run beside the other and does not care which goes first, so a row in this table would force an
        # order the domain never asked for and make the derivation assert something untrue.
        self.assertNotIn("contends", [kind.slot for kind in Vocabulary.shipped()])

    def test_it_is_a_declaration_slot_a_caller_may_still_set(self):
        # Like the edge slots, it is configuration the run reads once before anything executes.
        class Writer(Step):
            pass

        step = Writer()
        step.contends = frozenset({"disk"})
        self.assertEqual(step.contends, frozenset({"disk"}))

    def test_two_steps_may_contend_for_the_same_thing_without_depending_on_each_other(self):
        class Left(Step):
            contends = frozenset({"disk"})

        class Right(Step):
            contends = frozenset({"disk"})

        self.assertEqual(Left().expects, ())
        self.assertEqual(Right().expects, ())
        self.assertTrue(Left().contends & Right().contends)
