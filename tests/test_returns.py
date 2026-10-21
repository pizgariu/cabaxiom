"""The named constructors a hook hands its answer back through, one per sentence a read or write says.

Before these existed, saying "nothing is out of desired state" cost a record, a keyword, a list and a
trailing empty dict, which the repository spelled 176 times. The tests below pin the two
things the ceremony never gave for free. The step NAMES its own report and a domain never has to meet
Assessment or DriftItem to write a declaration."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Reconciler, Step


class Quiet(Step):
    pass


class Loud(Step):
    @property
    def identifier(self) -> str | None:
        return "the-quartermaster"


class TheReadHandsBackTests(unittest.TestCase):

    def test_verified_is_the_empty_assessment_and_no_artifacts(self):
        reading, produced = Quiet().verified()
        self.assertEqual(list(reading.deviation), [])
        self.assertEqual(produced, {})

    def test_verified_carries_what_the_read_produced(self):
        _reading, produced = Quiet().verified(produced={"dsn": "postgres://x"})
        self.assertEqual(produced, {"dsn": "postgres://x"})

    def test_a_bare_message_is_named_after_the_step(self):
        # The whole point. The name written at those call sites was overwhelmingly the step's own class,
        # so a declaration that already knows what it is called is no longer asked for it twice.
        reading, _produced = Quiet().drifted("config file is missing")
        self.assertEqual(list(reading.deviation), [DriftItem("Quiet", "config file is missing")])

    def test_a_declared_identifier_wins_over_the_class_name(self):
        reading, _produced = Loud().drifted("gone")
        self.assertEqual(list(reading.deviation), [DriftItem("the-quartermaster", "gone")])

    def test_a_drift_of_your_own_passes_through_untouched(self):
        # A subject that is not this step keeps its own name, while a domain's richer carrier stays
        # first-class - the kernel reads two fields and never asks which class exposed them.
        mine = DriftItem("/etc/hosts", "unreadable")
        reading, _produced = Quiet().drifted(mine)
        self.assertIs(list(reading.deviation)[0], mine)

    def test_several_are_reported_in_the_order_given(self):
        reading, _produced = Quiet().drifted("first", DriftItem("elsewhere", "second"), "third")
        self.assertEqual([item.name for item in reading.deviation], ["Quiet", "elsewhere", "Quiet"])
        self.assertEqual([item.message for item in reading.deviation], ["first", "second", "third"])

    def test_finding_nothing_lands_exactly_where_verified_does(self):
        # Not a loophole - the axiom holding. A hook that spreads a computed sequence in here tells the
        # truth at both lengths, which is what lets one call site serve the clean and dirty world.
        found: list[str] = []
        self.assertEqual(Quiet().drifted(*found), Quiet().verified())

    def test_advised_reaches_the_advisory_channel_and_never_the_proof(self):
        # The difference from drifted() IS the axiom. Advice must never dirty the proof, so the deviation
        # channel stays empty and a run reading this still verifies clean.
        reading, produced = Quiet().advised("a newer git could use native hooks")
        self.assertEqual(list(reading.advisory), [DriftItem("Quiet", "a newer git could use native hooks")])
        self.assertEqual(list(reading.deviation), [])
        self.assertEqual(produced, {})

    def test_owns_reaches_the_footprint_channel_and_never_the_proof(self):
        reading, produced = Quiet().owns("the AD account", produced={"username": "j.kowalski"})
        self.assertEqual(list(reading.footprint), [DriftItem("Quiet", "the AD account")])
        self.assertEqual(list(reading.deviation), [])
        self.assertEqual(produced, {"username": "j.kowalski"})

    def test_the_new_pair_names_and_passes_through_like_drifted(self):
        # Same __reported seam, asserted once per constructor rather than re-proven per rule - a declared
        # identifier wins, while a domain's own Drift keeps its subject.
        mine = DriftItem("/etc/krb5.conf", "kerberos owns this")
        self.assertEqual([item.name for item in Loud().advised("tip")[0].advisory], ["the-quartermaster"])
        self.assertIs(list(Quiet().owns(mine)[0].footprint)[0], mine)

    def test_reporting_no_ownership_or_advice_lands_where_verified_does(self):
        self.assertEqual(Quiet().owns(), Quiet().verified())
        self.assertEqual(Quiet().advised(), Quiet().verified())


class TheWriteHandsBackTests(unittest.TestCase):

    def test_unchanged_is_the_clean_no_op(self):
        changes, produced = Quiet().unchanged()
        self.assertIsNone(changes)
        self.assertEqual(produced, {})

    def test_changed_names_its_report_after_the_step_too(self):
        changes, _produced = Quiet().changed("config file written")
        self.assertEqual(list(changes or ()), [DriftItem("Quiet", "config file written")])

    def test_a_write_carries_what_it_produced_for_its_dependents(self):
        changes, produced = Quiet().changed("written", produced={"dsn": "postgres://x"})
        self.assertEqual(list(changes or ()), [DriftItem("Quiet", "written")])
        self.assertEqual(produced, {"dsn": "postgres://x"})

    def test_reporting_nothing_reads_as_unchanged_does(self):
        # The kernel has never told None from empty apart - it reads a write's report as `changes or ()`
        # - so a spread that came out empty is the same answer, said the other way.
        made: list[str] = []
        self.assertEqual(len(Quiet().changed(*made)[0] or ()), len(Quiet().unchanged()[0] or ()))


class TheDeclarationNeedsNoCarrierTests(unittest.TestCase):

    def test_a_whole_run_converges_with_no_carrier_imported(self):
        # The sell, end to end. Nothing below names Assessment or DriftItem, which is the point - those
        # are the kernel's carriers, so a first declaration should not have to meet one to say a file
        # is missing. Reconciler and Step are the entire import.
        written: list[str] = []

        class CreateConfig(Step):
            produces = frozenset({"dsn"})

            def assess(self, inputs: dict[str, object]) -> object:
                # The READ produces too and has to. A converge re-probes, so on that pass the write
                # never runs, so a dependent reading only what apply() produced would find nothing and
                # report drift against a world that is actually right.
                if written:
                    return self.verified(produced={"dsn": "postgres://x"})
                return self.drifted("config file is missing")

            def apply(self, inputs: dict[str, object]) -> object:
                written.append("dsn")
                return self.changed("config file written", produced={"dsn": "postgres://x"})

        class Verify(Step):
            expects = (CreateConfig,)
            consumes = frozenset({"dsn"})

            def assess(self, inputs: dict[str, object]) -> object:
                return self.verified() if inputs.get("dsn") else self.drifted("no connection string")

        residual = asyncio.run(Reconciler((CreateConfig(), Verify())).converge())
        self.assertEqual(list(residual), [])   # empty means verified, written the short way

    def test_the_default_hooks_answer_through_the_same_constructors(self):
        # The kernel eats its own cooking - a step that overrides nothing returns these, not the ceremony.
        self.assertEqual(Quiet().assess({}), (Assessment(), {}))
        self.assertEqual(Quiet().apply({}), (None, {}))
        self.assertEqual(Quiet().prune({}), (None, {}))

    def test_a_subclass_cannot_redefine_what_a_hook_hands_back(self):
        # @final on all four, so the shape of an answer is the kernel's to decide. Checked by the type
        # checkers rather than at runtime, which is why this asserts the marking and not a raise.
        for name in ("verified", "drifted", "unchanged", "changed"):
            with self.subTest(constructor=name):
                self.assertTrue(getattr(getattr(Step, name), "__final__", False))
