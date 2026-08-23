"""The four named constructors a hook hands its answer back through."""
import unittest

from cabaxiom import DriftItem, Step


class Quiet(Step):
    pass


class TheReadHandsBackTests(unittest.TestCase):

    def test_verified_is_the_empty_assessment(self):
        self.assertEqual(list(Quiet().verified().deviation), [])

    def test_a_bare_message_is_named_after_the_step(self):
        # The whole point. The name written at such a site is overwhelmingly the step's own kind, so a
        # declaration that already knows what it is called is no longer asked for it twice.
        # Compared field by field, because DriftItem carries no value equality at this release - two
        # identical items are still two objects. That is a later tag's problem and not this one's.
        found = list(Quiet().drifted("config file is missing").deviation)
        self.assertEqual([(item.name, item.message) for item in found],
                         [("Quiet", "config file is missing")])

    def test_a_drift_of_your_own_passes_through_untouched(self):
        # A subject that is not this step keeps its own name, and a domain's richer carrier stays
        # first-class - the kernel reads two fields and never asks which class exposed them.
        mine = DriftItem("/etc/hosts", "unreadable")
        self.assertIs(list(Quiet().drifted(mine).deviation)[0], mine)

    def test_several_are_reported_in_the_order_given(self):
        reading = Quiet().drifted("first", DriftItem("elsewhere", "second"), "third")
        self.assertEqual([item.name for item in reading.deviation], ["Quiet", "elsewhere", "Quiet"])
        self.assertEqual([item.message for item in reading.deviation], ["first", "second", "third"])

    def test_finding_nothing_lands_exactly_where_verified_does(self):
        # Not a loophole - the axiom holding. A hook that spreads a computed sequence in here tells the
        # truth at both lengths, which is what lets one call site serve the clean and the dirty world.
        found: list[str] = []
        self.assertEqual(Quiet().drifted(*found), Quiet().verified())


class TheWriteHandsBackTests(unittest.TestCase):

    def test_unchanged_is_the_clean_no_op(self):
        self.assertIsNone(Quiet().unchanged())

    def test_changed_names_its_report_after_the_step_too(self):
        made = list(Quiet().changed("config file written") or ())
        self.assertEqual([(item.name, item.message) for item in made],
                         [("Quiet", "config file written")])

    def test_a_declaration_needs_no_carrier_imported_to_write_a_hook(self):
        # The sell. Nothing a domain writes below names Assessment or DriftItem, which is why the
        # constructors are methods rather than helpers sitting beside the class.
        class Config(Step):
            def drift(self):
                return list(self.drifted("missing").deviation)

            def apply(self):
                return self.changed("written")

        self.assertEqual(Config().drift()[0].name, "Config")
        self.assertEqual(list(Config().apply() or ())[0].message, "written")
