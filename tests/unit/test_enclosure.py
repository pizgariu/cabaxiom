"""Enclosure - the guard the fractal claim never had. Each reconciler derives its Graph over its OWN
selection, so a step that leans across an enclave boundary gets a silent dead end - and nothing at either
level can see it. Pure structure, no world touched."""
import unittest

from cabaxiom import Enclave, Enclosure, Reconciler, Step


class Network(Step):
    pass


class Leaning(Step):
    expects = (Network,)


class Thirsty(Step):
    wants = ("database",)


class Database(Step):
    def __init__(self) -> None:
        self.provides = frozenset({"database"})


class Plain(Enclave):
    pass


class SeveredTests(unittest.IsolatedAsyncioTestCase):
    """A leaning that resolves at another level, with nothing ordering the two boundaries."""

    async def test_it_names_the_intent_the_boundary_voids(self):
        top = Reconciler((Network(), Plain(Reconciler((Leaning(),)))))
        severance = Enclosure(top).prove()

        self.assertFalse(severance.airtight)
        self.assertTrue(severance)                      # truthy when something was cut
        self.assertEqual(severance.boundaries, 1)
        cut = severance.severed[0]
        self.assertEqual(cut.leaner, "Plain/Leaning")   # qualified by its level path
        self.assertEqual(cut.slot, "expects")
        self.assertEqual(cut.named, "Network")
        self.assertEqual(cut.resolver, "Network")
        self.assertEqual(cut.boundary, "Plain")         # the two steps to order at the common level
        self.assertEqual(cut.against, "Network")
        self.assertFalse(cut.inverted)

    async def test_declaring_the_boundary_edge_the_record_names_makes_it_airtight(self):
        class Ordered(Enclave):
            expects = (Network,)

        top = Reconciler((Network(), Ordered(Reconciler((Leaning(),)))))
        severance = Enclosure(top).prove()
        self.assertTrue(severance.airtight)
        self.assertFalse(severance)
        self.assertEqual(severance.severed, ())

    async def test_the_parent_ordering_the_pair_backwards_is_the_sharper_finding(self):
        stack = Plain(Reconciler((Leaning(),)))
        network = Network()
        network.needs = (stack,)          # the parent runs the stack FIRST, then the network
        severance = Enclosure(Reconciler((network, stack))).prove()

        self.assertFalse(severance.airtight)
        self.assertEqual(len(severance.inverted), 1)
        self.assertTrue(severance.severed[0].inverted)
        self.assertIn("ordered the other way", repr(severance.severed[0]))

    async def test_a_capability_leaning_across_a_boundary_is_caught_too(self):
        top = Reconciler((Database(), Plain(Reconciler((Thirsty(),)))))
        cut = Enclosure(top).prove().severed[0]
        self.assertEqual((cut.slot, cut.named), ("wants", "'database'"))
        self.assertEqual(cut.resolver, "Database")

    async def test_an_instance_leaning_across_a_boundary_is_caught_too(self):
        network = Network()
        inner = Step()
        inner.uses = (network,)           # a specific instance, living one level up
        top = Reconciler((network, Plain(Reconciler((inner,)))))
        cut = Enclosure(top).prove().severed[0]
        self.assertEqual((cut.slot, cut.named), ("uses", "Network"))
        self.assertEqual(cut.resolver, "Network")


class NotSeveredTests(unittest.IsolatedAsyncioTestCase):
    """What the guard must NOT report, so airtight keeps meaning something."""

    async def test_a_name_resolved_at_its_own_level_is_no_business_of_the_boundary(self):
        top = Reconciler((Plain(Reconciler((Network(), Leaning()))), Network()))
        # The inner Leaning is answered by the inner Network, yet the OUTER Network is still an
        # out-of-level instance that nothing orders, so exactly one cut is reported.
        severance = Enclosure(top).prove()
        self.assertEqual(len(severance.severed), 1)
        self.assertEqual(severance.severed[0].resolver, "Network")

    async def test_a_name_nothing_in_the_tree_answers_is_not_a_cut(self):
        # It leans on the world, which is what a soft edge MEANS. Succession reports that, not Enclosure.
        top = Reconciler((Step(), Plain(Reconciler((Leaning(),)))))
        self.assertTrue(Enclosure(top).prove().airtight)

    async def test_a_partially_resolved_fan_in_still_audits_the_instance_a_level_up(self):
        # The correction that matters. Counting only names that matched NOTHING would miss this, because
        # the inner Network answers locally and the outer one goes silently unordered.
        inner = Reconciler((Network(), Leaning()))
        top = Reconciler((Network(), Plain(inner)))
        severance = Enclosure(top).prove()
        self.assertFalse(severance.airtight)
        self.assertEqual(severance.severed[0].leaner, "Plain/Leaning")


class TreeShapeTests(unittest.IsolatedAsyncioTestCase):
    """The walk itself - siblings, depth and duplicate kinds at one level."""

    async def test_a_resolver_inside_a_sibling_enclave_is_judged_at_their_common_level(self):
        class Left(Enclave):
            pass

        class Right(Enclave):
            pass

        top = Reconciler((Left(Reconciler((Leaning(),))), Right(Reconciler((Network(),)))))
        cut = Enclosure(top).prove().severed[0]
        self.assertEqual(cut.leaner, "Left/Leaning")
        self.assertEqual(cut.resolver, "Right/Network")
        self.assertEqual((cut.boundary, cut.against), ("Left", "Right"))   # both stand in at the root

    async def test_it_walks_arbitrary_depth(self):
        class Outer(Enclave):
            pass

        deep = Reconciler((Leaning(),))
        top = Reconciler((Network(), Outer(Reconciler((Plain(deep),)))))
        severance = Enclosure(top).prove()
        self.assertEqual(severance.boundaries, 2)
        cut = severance.severed[0]
        self.assertEqual(cut.leaner, "Outer/Plain/Leaning")
        self.assertEqual(cut.boundary, "Outer")        # the root only holds the outermost enclave

    async def test_cousins_are_judged_at_the_enclave_that_holds_them_both(self):
        # Neither the root nor either sibling. The deepest common level is the enclave in the middle and
        # that is the Graph that must carry the fixing edge.
        class Outer(Enclave):
            pass

        class Left(Enclave):
            pass

        class Right(Enclave):
            pass

        middle = Reconciler((Left(Reconciler((Leaning(),))), Right(Reconciler((Network(),)))))
        severance = Enclosure(Reconciler((Outer(middle),))).prove()

        cut = severance.severed[0]
        self.assertEqual(cut.leaner, "Outer/Left/Leaning")
        self.assertEqual(cut.resolver, "Outer/Right/Network")
        self.assertEqual((cut.boundary, cut.against), ("Outer/Left", "Outer/Right"))

    async def test_two_enclaves_of_one_kind_at_a_level_read_apart(self):
        top = Reconciler((Network(), Plain(Reconciler((Leaning(),))), Plain(Reconciler((Leaning(),)))))
        leaners = sorted(cut.leaner for cut in Enclosure(top).prove().severed)
        self.assertEqual(leaners, ["Plain#2/Leaning", "Plain/Leaning"])

    def test_a_flat_reconciler_is_refused_at_construction(self):
        with self.assertRaises(ValueError) as ctx:
            Enclosure(Reconciler((Network(), Leaning())))
        self.assertIn("at least one Enclave", str(ctx.exception))


class VerdictShapeTests(unittest.IsolatedAsyncioTestCase):
    """The record discipline every kernel verdict keeps."""

    async def test_the_channels_are_frozen_and_the_reprs_count_what_they_carry(self):
        top = Reconciler((Network(), Plain(Reconciler((Leaning(),)))))
        severance = Enclosure(top).prove()

        self.assertIsInstance(severance.severed, tuple)
        with self.assertRaises(AttributeError):
            severance.severed = ()
        self.assertIn("Severance(airtight=False, severed=1, inverted=0, boundaries=1", repr(severance))
        self.assertIn("Plain/Leaning.expects Network -> Network", repr(severance.severed[0]))
        self.assertIn("unordered against Network", repr(severance.severed[0]))

    async def test_an_airtight_tree_reports_no_inverted_subset(self):
        class Ordered(Enclave):
            expects = (Network,)

        top = Reconciler((Network(), Ordered(Reconciler((Leaning(),)))))
        self.assertEqual(Enclosure(top).prove().inverted, ())
