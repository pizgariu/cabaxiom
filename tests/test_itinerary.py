"""Itinerary - a world walked through a path of declarations, one proof-gated Transition per hop."""
import asyncio
import unittest

from cabaxiom import Assessment, Cutover, DriftItem, Itinerary, Passage, Residual, Step


class _Flag(Step):
    # One key of a shared world. Drift reads it, apply sets it, prune clears it and reports clean.
    def __init__(self, world: dict, key: str) -> None:
        self._world = world
        self._key = key

    def assess(self, inputs):
        return Assessment(deviation=[] if self._world.get(self._key) else [DriftItem(self._key, "missing")]), {}

    def apply(self, inputs):
        self._world[self._key] = True

        return None, {}
    def prune(self, inputs):
        self._world.pop(self._key, None)
        return [], {}


class ItineraryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_full_walk_arrives_and_proves_every_hop(self):
        # From scratch (the empty first waypoint) through baseline to canary. Every hop mints a clean
        # Cutover, the Passage is truthy and the world holds exactly the last waypoint's declaration.
        world: dict = {}
        base = _Flag(world, "base")
        canary = _Flag(world, "canary")
        passage = await Itinerary(((), (base,), (base, canary))).converge()
        self.assertTrue(passage)
        self.assertEqual(passage.reached, 2)
        self.assertEqual(len(passage.legs), 2)
        self.assertTrue(all(leg.clean for leg in passage.legs))
        self.assertEqual(world, {"base": True, "canary": True})

    async def test_the_walk_stops_at_the_first_unclean_hop(self):
        # A hop that cannot prove arrival stops the walk. The later waypoints are never touched, so the
        # Passage says the world never verifiably left the path's start.
        world: dict = {}

        class _Stuck(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("stuck", "never clears")]), {}

        stuck = _Stuck()
        later = _Flag(world, "later")
        passage = await Itinerary(((), (stuck,), (stuck, later))).converge()
        self.assertFalse(passage)
        self.assertEqual(passage.reached, 0)
        self.assertEqual(len(passage.legs), 1)   # the second hop never ran
        self.assertNotIn("later", world)         # its waypoint was never touched

    async def test_rerunning_resumes_where_the_world_stands(self):
        # The level-triggered promise. After a blocked walk the caller fixes the world and re-runs the
        # SAME itinerary. The settled hop no-ops (its leg applies nothing) and the walk picks up at the
        # hop that refused, arriving this time.
        world: dict = {}
        base = _Flag(world, "base")

        class _Gated(Step):
            def assess(self, inputs):
                return Assessment(deviation=[] if world.get("gate") else [DriftItem("gate", "missing")]), {}

            def apply(self, inputs):
                if world.get("enabled"):
                    world["gate"] = True

                return None, {}
        itinerary = Itinerary(((), (base,), (base, _Gated())))
        blocked = await itinerary.converge()
        self.assertFalse(blocked)
        self.assertEqual(blocked.reached, 1)     # stood verifiably at the baseline waypoint

        world["enabled"] = True                  # the world changes, the declaration does not
        resumed = await itinerary.converge()
        self.assertTrue(resumed)
        self.assertEqual(resumed.reached, 2)
        self.assertEqual(list(resumed.legs[0].residual.applied), [])   # the settled hop was a no-op

    async def test_reversed_is_the_same_path_walked_back_to_a_full_teardown(self):
        # The empty far end makes reversal symmetric. reversed([(), base, canary]) ends at (), so the
        # rollback IS a full teardown, with zero extra declarations and the same strategy knobs.
        world: dict = {}
        base = _Flag(world, "base")
        canary = _Flag(world, "canary")
        itinerary = Itinerary(((), (base,), (base, canary)))
        self.assertTrue(await itinerary.converge())

        rollback = await reversed(itinerary).converge()
        self.assertTrue(rollback)
        self.assertEqual(rollback.reached, 2)
        self.assertEqual(world, {})              # the world reads as before the walk ever started

    async def test_rollback_from_a_partial_walk_noops_above_the_standing_waypoint(self):
        # The rollout stopped at the canary hop, so the world holds only the baseline. The reversed walk
        # still starts from the path's far end. The hops above where the world stands read clean and
        # no-op (a leaver that was never built prunes as a no-op), until the walk meets the real world.
        world: dict = {}
        base = _Flag(world, "base")

        class _Refused(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("canary", "refused")]), {}

        forward = Itinerary(((), (base,), (base, _Refused())))
        self.assertFalse(await forward.converge())
        self.assertEqual(world, {"base": True})  # stood at the baseline

        rollback = await reversed(forward).converge()
        self.assertTrue(rollback)
        self.assertEqual(world, {})              # torn down from where it really stood

    async def test_waypoints_share_instances_for_the_steps_that_persist(self):
        # The kernel's dependency addressing is instance identity. The SAME instance carried between
        # waypoints is no leaver, so the hop never prunes it - while a fresh instance of the same class
        # reads as a leaver plus a joiner, torn down and rebuilt across the hop.
        world: dict = {}
        pruned: list = []

        class _Counted(_Flag):
            def prune(self, inputs):
                pruned.append(self._key)
                return super().prune(inputs)

        carried = _Counted(world, "carried")
        await Itinerary(((carried,), (carried,))).converge()
        self.assertEqual(pruned, [])             # the persisting instance was carried, never torn down

        await Itinerary(((_Counted(world, "swapped"),), (_Counted(world, "swapped"),))).converge()
        self.assertEqual(pruned, ["swapped"])    # the fresh instance made the old one a leaver

    def test_a_path_needs_at_least_two_waypoints(self):
        with self.assertRaises(ValueError) as ctx:
            Itinerary(((),))
        self.assertIn("at least two waypoints", str(ctx.exception))
        self.assertIn("empty declaration", str(ctx.exception))

    def test_an_empty_passage_never_left_the_start(self):
        passage = Passage(())
        self.assertFalse(passage)
        self.assertEqual(passage.reached, 0)
        self.assertEqual(repr(passage), "Passage(arrived=False, reached=0, legs=0)")

    def test_a_minted_passage_cannot_be_rewritten(self):
        # The verdict is a RECORD: the legs sit behind a read-only property, so a walk cannot be
        # rewritten after the world took it.
        passage = Passage((Cutover([], Residual([])),))
        self.assertTrue(passage)
        with self.assertRaises(AttributeError):
            passage.legs = ()


class AsyncStepItineraryTests(unittest.IsolatedAsyncioTestCase):
    """The same plotted walk over steps whose apply() and prune() genuinely await I/O - the engine drives
    the coroutines and the Passage reads identically."""

    class _AsyncFlag(Step):
        def __init__(self, world: dict, key: str) -> None:
            self._world = world
            self._key = key

        def assess(self, inputs):
            return Assessment(deviation=[] if self._world.get(self._key) else [DriftItem(self._key, "missing")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self._world[self._key] = True

            return None, {}
        async def prune(self, inputs):
            await asyncio.sleep(0)
            self._world.pop(self._key, None)
            return [], {}

    async def test_the_async_walk_arrives_and_its_reversal_tears_down(self):
        world: dict = {}
        base = self._AsyncFlag(world, "base")
        canary = self._AsyncFlag(world, "canary")
        itinerary = Itinerary(((), (base,), (base, canary)))
        self.assertTrue(await itinerary.converge())
        self.assertEqual(world, {"base": True, "canary": True})
        self.assertTrue(await reversed(itinerary).converge())
        self.assertEqual(world, {})

    async def test_the_async_walk_stops_at_the_first_unclean_hop(self):
        class _AsyncStuck(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("stuck", "never clears")]), {}

        passage = await Itinerary(((), (_AsyncStuck(),))).converge()
        self.assertFalse(passage)
        self.assertEqual(passage.reached, 0)

