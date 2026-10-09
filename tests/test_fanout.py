"""Fanout. A step that lists its world each pass and converges a graph over what it found."""
import unittest

from cabaxiom import (
    Assessment,
    DriftItem,
    Enclave,
    Enclosure,
    Fanout,
    Fixpoint,
    Idempotence,
    Reconciler,
    Retry,
    Step,
)


class World:
    """The world a fan lists. Deliberately NOT a Step, so nothing here is frozen and a test can grow it
    between passes exactly as a real world grows under a running reconciler."""

    def __init__(self, *pending: str) -> None:
        self.pending = list(pending)
        self.done: list[str] = []
        self.listings = 0
        self.attempts: dict[str, int] = {}


class Settle(Step):
    """One discovered thing, level-triggered. It settles what is pending and no-ops on what is settled."""

    def __init__(self, world: World, item: str, cursed: str | None = None) -> None:
        self.world = world
        self.item = item
        self.cursed = cursed

    @property
    def identifier(self) -> str:
        # What makes a fan readable. Fifty discoveries report under fifty names rather than fifty `Settle#n`.
        return f"settle/{self.item}"

    def assess(self, inputs):
        drifted = [DriftItem(self.item, f"{self.item} unsettled")] if self.item in self.world.pending else []
        return Assessment(deviation=drifted), {}

    def apply(self, inputs):
        if self.item not in self.world.pending:
            return None, {}
        self.world.attempts[self.item] = self.world.attempts.get(self.item, 0) + 1
        if self.item == self.cursed and self.world.attempts[self.item] == 1:
            raise RuntimeError(f"{self.item} was busy")
        self.world.pending.remove(self.item)
        self.world.done.append(self.item)
        return [DriftItem(self.item, f"settled {self.item}")], {}

    def prune(self, inputs):
        if self.item not in self.world.done:
            return None, {}
        self.world.done.remove(self.item)
        return [DriftItem(self.item, f"tore down {self.item}")], {}


class Sweep(Fanout):
    """The fan itself. Everything it knows about the run arrives through its verbs."""

    def __init__(self, world: World, cursed: str | None = None, retry: Retry | None = None) -> None:
        self.world = world
        self.cursed = cursed
        self.retry = retry

    async def explore(self, inputs):
        self.world.listings += 1
        known = sorted(set(self.world.pending) | set(self.world.done))
        return Reconciler([Settle(self.world, item, self.cursed) for item in known], retry=self.retry)


class FanoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_discovered_world_reports_one_finding_per_thing_under_its_own_name(self):
        # The whole point. A declaration naming ONE concern answers for three, where the report is three
        # sentences rather than one, which is what a flat step looping inside itself cannot give.
        world = World("a", "b", "c")
        residual = await Reconciler((Sweep(world),)).converge()

        self.assertEqual(residual, [])                     # empty residual IS the proof
        self.assertEqual([item.message for item in residual.applied],
                         ["settled a", "settled b", "settled c"])
        self.assertEqual([item.name for item in residual.applied], ["a", "b", "c"])
        self.assertEqual(world.done, ["a", "b", "c"])

    async def test_apply_routes_the_inner_applied_channel_never_the_residual(self):
        # The rule the @final wiring exists to make unbreakable. One item stays wrong forever and it must
        # reach the parent through the RE-ASSESSMENT rather than through what apply() handed back. A
        # residual returned here would land a still-wrong item in the parent's applied channel and quietly
        # break Proof.churned.
        world = World("a", "stuck")

        class Stubborn(Settle):
            def apply(self, inputs):
                return (None, {}) if self.item == "stuck" else super().apply(inputs)

        class Half(Sweep):
            async def explore(self, inputs):
                self.world.listings += 1
                return Reconciler([Stubborn(self.world, item) for item in sorted(set(self.world.pending) | set(self.world.done))])

        residual = await Reconciler((Half(world),)).converge()
        self.assertEqual([item.message for item in residual.applied], ["settled a"])
        self.assertEqual([item.message for item in residual], ["stuck unsettled"])

    async def test_a_thing_that_appeared_between_passes_joins_the_next_pass_untouched(self):
        # Level-triggered paying for itself. Nobody edits the declaration and nobody mutates a live graph.
        # The next pass lists the world again, where the newcomer is simply there.
        world = World("a")

        class Growing(Sweep):
            async def explore(self, inputs):
                if self.world.listings == 1:
                    self.world.pending.append("late")
                return await super().explore(inputs)

        residual = await Reconciler((Growing(world),), convergence=Fixpoint(4)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(world.done, ["a", "late"])

    async def test_one_cursed_thing_spends_its_own_retry_budget_and_nobody_elses(self):
        # A flat step looping over the batch would re-run the whole batch per attempt. Here the retry seats
        # itself at each discovery, so the cursed item costs two attempts and its neighbours cost one.
        world = World("a", "b", "cursed")
        residual = await Reconciler((Sweep(world, cursed="cursed", retry=Retry(2)),)).converge()

        self.assertEqual(residual, [])
        self.assertEqual(world.attempts, {"a": 1, "b": 1, "cursed": 2})

    async def test_idempotence_certifies_the_whole_fan_through_the_parent(self):
        # The proof a mutable mid-run graph would have destroyed. The parent knows nothing about the fan and
        # still certifies it, because every pass holds a complete immutable derivation.
        world = World("a", "b")
        proof = await Idempotence(Reconciler((Sweep(world),))).prove()

        self.assertTrue(proof.stable)
        self.assertEqual(proof.churned, ())

    async def test_the_parents_own_read_sees_the_whole_sub_stack(self):
        # assess() lists the world afresh and answers the inner deviation as this one step's deviation, so
        # "empty means verified" survives a level whose shape is only decided at read time.
        world = World("a", "b")
        reading = await Reconciler((Sweep(world),)).assess()

        self.assertEqual([item.message for item in reading], ["a unsettled", "b unsettled"])
        self.assertEqual(world.listings, 1)

    async def test_prune_tears_down_what_is_there_now_rather_than_what_was_declared(self):
        # The only honest answer a teardown of a discovered world can give. The fan was never told what it
        # built, so it looks again.
        world = World("a", "b")
        reconciler = Reconciler((Sweep(world),))
        await reconciler.converge()
        residue = await reconciler.prune()

        # Reverse order, because the inner reconciler walks its own inverse partition. Both discoveries sit
        # in one wave, so the inversion reverses the members.
        self.assertEqual([item.message for item in residue], ["tore down b", "tore down a"])
        self.assertEqual(world.done, [])

    async def test_the_seam_reads_what_the_parents_siblings_produced(self):
        # The one thing a static Enclave cannot do. A fan's declaration is BUILT during the parent's run, so
        # a sibling's output is allowed to say what to list.
        world = World("row-1", "other-1")
        seen: list[str] = []

        class Names(Step):
            provides = frozenset({"names"})

            def apply(self, inputs):
                return None, {"prefix": "row-"}

            def assess(self, inputs):
                return Assessment(), {"prefix": "row-"}

        class Prefixed(Sweep):
            wants = ("names",)

            async def explore(self, inputs):
                seen.append(inputs["prefix"])
                self.world.listings += 1
                known = set(self.world.pending) | set(self.world.done)
                return Reconciler([Settle(self.world, item) for item in sorted(known) if item.startswith(inputs["prefix"])])

        residual = await Reconciler((Prefixed(world), Names())).converge()
        self.assertEqual(residual, [])
        self.assertEqual(world.done, ["row-1"])              # the prefix chose what the fan owns
        self.assertEqual(world.pending, ["other-1"])         # and what it never claimed stayed untouched
        self.assertEqual(set(seen), {"row-"})

    async def test_the_listing_runs_once_per_verb_which_is_the_price_of_asking(self):
        # The documented cost, pinned rather than promised. A fan asks the world instead of remembering it,
        # so every pass pays twice - once for the write and once for the re-probe that proves it. Three
        # passes list the world six times, which is the price of a declaration that is always current.
        world = World("a")
        await Reconciler((Sweep(world),)).converge()
        self.assertEqual(world.listings, 2)

        second = World("a")

        class Growing(Sweep):
            async def explore(self, inputs):
                if self.world.listings == 1:
                    self.world.pending.append("late")
                return await super().explore(inputs)

        await Reconciler((Growing(second),), convergence=Fixpoint(4)).converge()
        self.assertEqual(second.listings, 4)

    async def test_a_fan_is_ordered_like_any_other_step(self):
        # One step to the parent, so every edge kind reaches it unchanged.
        order: list[str] = []

        class Ground(Step):
            def apply(self, inputs):
                order.append("ground")
                return None, {}

        class Later(Sweep):
            expects = (Ground,)

            async def explore(self, inputs):
                order.append("fan")
                return await super().explore(inputs)

        await Reconciler((Later(World("a")), Ground())).converge()
        self.assertEqual(order[:2], ["ground", "fan"])

    async def test_nothing_crosses_back_up_the_artifacts_channel(self):
        # A fan of N producers has no single value to name, so the boundary is sealed. A step that means to
        # publish is an Enclave.
        world = World("a")
        reading = await Reconciler((Sweep(world),)).assess()
        self.assertEqual(list(reading.produced.values()), [{}])


class WiringTests(unittest.IsolatedAsyncioTestCase):
    """The guard and seam pairing, asserted rather than trusted. The verbs hold the applied-not-residual rule
    and the discovery stays open, which is the same shape the seven axes are built in."""

    def test_every_verb_refuses_an_override(self):
        for verb in ("assess", "apply", "prune"):
            with self.subTest(verb=verb):
                self.assertTrue(getattr(getattr(Fanout, verb), "__final__", False),
                                f"Fanout.{verb} holds the wiring and must refuse an override")

    def test_the_discovery_is_the_way_in_and_stays_open(self):
        self.assertIn("explore", Fanout.__abstractmethods__)
        self.assertFalse(getattr(Fanout.explore, "__final__", False))

    async def test_a_seam_that_answers_something_else_is_refused_by_name(self):
        class Listy(Fanout):
            async def explore(self, inputs):
                return [Settle(World("a"), "a")]        # type: ignore[return-value]

        with self.assertRaises(TypeError) as raised:
            await Listy().assess({})
        self.assertIn("must answer a Reconciler", str(raised.exception))
        self.assertIn("got list", str(raised.exception))

    async def test_a_fan_that_answers_a_graph_holding_itself_is_refused(self):
        # Without this the run dies of recursion inside the kernel, listing the world once per level.
        class Ouroboros(Fanout):
            async def explore(self, inputs):
                return Reconciler((self,))

        with self.assertRaises(ValueError) as raised:
            await Ouroboros().apply({})
        self.assertIn("containing the fanout itself", str(raised.exception))

    async def test_the_refusal_names_the_fan_by_its_own_ident(self):
        class Named(Fanout):
            @property
            def identifier(self):
                return "sweep/tenants"

            async def explore(self, inputs):
                return Reconciler((self,))

        with self.assertRaises(ValueError) as raised:
            await Named().prune({})
        self.assertIn("sweep/tenants.explore", str(raised.exception))


class EnclosureBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """Enclosure reads structure, while a fan has no structure until a verb runs. It says so rather than
    reporting airtight over a boundary it never opened."""

    def test_a_tree_of_one_fan_is_refused_and_the_fan_is_named(self):
        with self.assertRaises(ValueError) as raised:
            Enclosure(Reconciler((Sweep(World("a")),)))
        told = str(raised.exception)
        self.assertIn("does hold a fanout (Sweep)", told)
        self.assertIn("built per pass", told)

    def test_a_flat_tree_without_a_fan_still_says_only_what_is_true_of_it(self):
        with self.assertRaises(ValueError) as raised:
            Enclosure(Reconciler((Settle(World("a"), "a"),)))
        self.assertNotIn("fanout", str(raised.exception))

    def test_a_fan_inside_an_enclave_leaves_a_boundary_this_can_read(self):
        # The composition that gives both. The enclave is the standing boundary Enclosure walks, while the fan
        # rides inside it as one step whose insides stay its own business.
        world = World("a")
        enclosed = Enclosure(Reconciler((Enclave(Reconciler((Sweep(world), Settle(world, "a")))),)))
        self.assertTrue(enclosed.prove().airtight)

