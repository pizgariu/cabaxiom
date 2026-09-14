"""The edge language as data - rows, pairs, addressings and the invariants a table checks about itself."""
import unittest

from cabaxiom import Misconfigured, Step
from cabaxiom.vocabulary import BY_CLASS, BY_INSTANCE, BY_LABEL, MODES, EdgeKind, Vocabulary


class AddressingTests(unittest.TestCase):

    def test_by_class_admits_a_step_class_and_nothing_else(self):
        class Thing(Step):
            pass

        self.assertTrue(BY_CLASS.admits(Thing))
        self.assertFalse(BY_CLASS.admits(Thing()))     # the classic forgotten instance
        self.assertFalse(BY_CLASS.admits("Thing"))
        self.assertFalse(BY_CLASS.admits(int))         # a class, not one of ours

    def test_by_label_admits_a_string(self):
        self.assertTrue(BY_LABEL.admits("database"))
        self.assertFalse(BY_LABEL.admits(Step))

    def test_by_instance_admits_a_step_instance(self):
        class Thing(Step):
            pass

        self.assertTrue(BY_INSTANCE.admits(Thing()))
        self.assertFalse(BY_INSTANCE.admits(Thing))

    def test_a_class_edge_finds_every_instance_of_it_and_not_the_first(self):
        # Two steps of one kind are two nodes, so a dependent that named the kind meant both.
        class Thing(Step):
            pass

        first, second = Thing(), Thing()
        self.assertEqual(BY_CLASS.found(Thing, {Thing: [first, second]}, {}), (first, second))

    def test_a_capability_fans_in_across_every_provider(self):
        # Duplicate providers are not a conflict. They are several things satisfying one promise, where the
        # kernel matches rather than picks, because picking would be the kernel guessing.
        class One(Step):
            pass

        class Two(Step):
            pass

        one, two = One(), Two()
        self.assertEqual(BY_LABEL.found("db", {}, {"db": [one, two]}), (one, two))

    def test_an_instance_edge_matches_by_identity_and_never_by_equality(self):
        class Thing(Step):
            pass

        held, alike = Thing(), Thing()
        self.assertEqual(BY_INSTANCE.found(held, {Thing: [held]}, {}), (held,))
        self.assertEqual(BY_INSTANCE.found(alike, {Thing: [held]}, {}), ())

    def test_an_absent_name_is_an_empty_match_and_never_an_error(self):
        # Whether absence is fatal is the KIND's business, hard or soft, not the addressing's.
        for mode in MODES:
            with self.subTest(mode=type(mode).__name__):
                self.assertEqual(mode.found("nothing here", {}, {}), ())


class EdgeKindTests(unittest.TestCase):

    def test_a_pair_is_the_two_flavours_of_one_dependency(self):
        soft, hard = EdgeKind.paired("wants", "demands", BY_LABEL)
        self.assertEqual((soft.hard, hard.hard), (False, True))
        self.assertEqual((soft.counterpart, hard.counterpart), ("demands", "wants"))

    def test_a_slot_must_be_a_usable_attribute_name(self):
        with self.assertRaises(Misconfigured):
            EdgeKind("not a name", BY_CLASS, hard=False, counterpart=None)

    def test_a_kind_cannot_be_its_own_counterpart(self):
        with self.assertRaises(Misconfigured):
            EdgeKind("expects", BY_CLASS, hard=False, counterpart="expects")


class VocabularyTests(unittest.TestCase):

    def test_the_shipped_table_says_what_this_release_can_express(self):
        self.assertEqual([kind.slot for kind in Vocabulary.shipped()], ["expects"])

    def test_growing_the_language_is_adding_a_row(self):
        grown = Vocabulary.shipped().grown(*EdgeKind.paired("wants", "demands", BY_LABEL))
        self.assertEqual([kind.slot for kind in grown], ["expects", "wants", "demands"])

    def test_growing_leaves_the_table_it_grew_from_alone(self):
        # A new Vocabulary and not a mutation, so a run already holding the old one keeps reading it.
        shipped = Vocabulary.shipped()
        shipped.grown(EdgeKind("before", BY_CLASS, hard=False, counterpart=None, precedes=True))
        self.assertEqual(len(shipped), 1)

    def test_an_empty_language_is_refused(self):
        with self.assertRaises(Misconfigured):
            Vocabulary()

    def test_a_duplicate_slot_is_refused(self):
        with self.assertRaises(Misconfigured):
            Vocabulary(EdgeKind("expects", BY_CLASS, hard=False, counterpart=None),
                       EdgeKind("expects", BY_LABEL, hard=True, counterpart=None))

    def test_half_a_pair_is_refused(self):
        with self.assertRaises(Misconfigured) as refused:
            Vocabulary(EdgeKind("wants", BY_LABEL, hard=False, counterpart="demands"))
        self.assertIn("both halves", str(refused.exception))

    def test_a_pair_that_is_hard_on_both_sides_is_refused(self):
        with self.assertRaises(Misconfigured):
            Vocabulary(EdgeKind("wants", BY_LABEL, hard=True, counterpart="demands"),
                       EdgeKind("demands", BY_LABEL, hard=True, counterpart="wants"))

    def test_row_order_is_derivation_order(self):
        # A table read twice draws its edges the same way twice, which is what makes a resolved order
        # reproducible rather than merely correct.
        grown = Vocabulary.shipped().grown(*EdgeKind.paired("uses", "needs", BY_INSTANCE))
        self.assertEqual([kind.slot for kind in grown], [kind.slot for kind in grown])


class EachAddressingSpeaksItsOwnNamesTests(unittest.TestCase):
    """`spoken` is what a refusal and an explanation print. It belongs to the addressing rather than to
    the caller, so one name is said one way everywhere it appears."""

    def test_a_class_says_its_own_name_and_anything_else_says_its_repr(self):
        class Thing(Step):
            pass

        self.assertEqual(BY_CLASS.spoken(Thing), "Thing")
        self.assertEqual(BY_CLASS.spoken("Thing"), "'Thing'")    # a misaddressed entry still has to print

    def test_a_label_says_its_quotes_so_a_capability_never_reads_as_a_class(self):
        self.assertEqual(BY_LABEL.spoken("database"), "'database'")

    def test_an_instance_says_its_kind_since_it_carries_no_name_of_its_own(self):
        class Thing(Step):
            pass

        self.assertEqual(BY_INSTANCE.spoken(Thing()), "Thing")


class APairIsCheckedFromBothEndsTests(unittest.TestCase):
    """A pair is the two flavours of one dependency. The table checks it from both halves, since a row
    can name a counterpart that does not name it back."""

    def test_a_pair_whose_halves_name_different_counterparts_is_refused(self):
        # The missing-half case is refused elsewhere. This is the other shape - both halves present, each
        # naming somebody else, which reads as a pair right up until the derivation follows one of them.
        with self.assertRaises(Misconfigured) as refused:
            Vocabulary(EdgeKind("wants", BY_LABEL, hard=False, counterpart="demands"),
                       EdgeKind("demands", BY_LABEL, hard=True, counterpart="after"))
        self.assertIn("disagree about being a pair", str(refused.exception))
