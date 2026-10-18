"""Transition - prune what left the declaration, converge what remains - the stateless cutover."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Reconciler, Step, Transition


class _Owned(Step):
    """A resource that exists once applied and reports its own teardown. Its existence lives in a shared
    world set, not on the frozen step, so a caller seeds it by adding the name to that world."""

    def __init__(self, name: str, log: list, world: set):
        self.name = name
        self.log = log
        self.world = world

    def assess(self, inputs):
        return Assessment(deviation=[] if self.name in self.world else [DriftItem(self.name, "missing")]), {}

    def apply(self, inputs):
        self.world.add(self.name)
        self.log.append(f"apply:{self.name}")
        return None, {}

    def prune(self, inputs):
        self.world.discard(self.name)
        self.log.append(f"prune:{self.name}")
        return [], {}


class TransitionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_step_removed_from_the_declaration_is_pruned_and_the_rest_converges(self):
        # The gap Transition closes. `leaver` stopped being declared, so nothing would ever tear it down.
        log: list = []
        world = {"leaver", "stayer"}   # the previous declaration is converged and live
        leaver, stayer, newcomer = _Owned("leaver", log, world), _Owned("stayer", log, world), _Owned("new", log, world)

        cutover = await Transition((leaver, stayer), (stayer, newcomer)).converge()
        self.assertTrue(cutover.clean)
        self.assertIn("prune:leaver", log)      # the leaver was torn down...
        self.assertNotIn("prune:stayer", log)   # ...the stayer was NOT (it is still declared)
        self.assertIn("apply:new", log)         # and the newcomer converged
        self.assertNotIn("leaver", world)
        self.assertIn("stayer", world)

    async def test_teardown_runs_before_the_converge_makes_room(self):
        # A leaver may hold what the desired set must claim (a port, a path), so prune comes first.
        log: list = []
        world = {"old"}
        leaver, newcomer = _Owned("old", log, world), _Owned("new", log, world)
        await Transition((leaver,), (newcomer,)).converge()
        self.assertEqual(log, ["prune:old", "apply:new"])

    async def test_leavers_tear_down_in_their_own_reverse_dependency_order(self):
        log: list = []

        class Ground(_Owned):
            pass

        class Tower(_Owned):
            expects = (Ground,)

        world = {"ground", "tower"}
        ground, tower = Ground("ground", log, world), Tower("tower", log, world)
        cutover = await Transition((ground, tower), ()).converge()   # everything leaves
        self.assertTrue(cutover.clean)
        self.assertEqual(log, ["prune:tower", "prune:ground"])   # dependent down first

    async def test_a_surviving_residue_makes_the_cutover_dirty(self):
        class Stubborn(Step):
            def prune(self, inputs):
                return [DriftItem("stubborn", "still holding a lock")], {}

        cutover = await Transition((Stubborn(),), ()).converge()
        self.assertFalse(cutover.clean)
        self.assertFalse(cutover)                                # truthy exactly when clean
        self.assertEqual([item.message for item in cutover.pruned], ["still holding a lock"])
        self.assertIn("clean=False", repr(cutover))

    async def test_an_unconverged_desired_set_makes_the_cutover_dirty_via_the_residual(self):
        class Stuck(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "never clears")]), {}

        cutover = await Transition((), (Stuck(),)).converge()
        self.assertFalse(cutover.clean)
        self.assertEqual(cutover.pruned, ())                     # nothing left, nothing to tear down
        self.assertEqual([item.message for item in cutover.residual], ["never clears"])

    async def test_a_minted_cutover_cannot_be_falsified_in_place(self):
        # The verdict is a RECORD: pruned is a tuple and both channels sit behind read-only properties,
        # so a dirty cutover cannot be flipped clean after it was minted.
        class Stubborn(Step):
            def prune(self, inputs):
                return [DriftItem("stubborn", "still holding a lock")], {}

        cutover = await Transition((Stubborn(),), ()).converge()
        self.assertFalse(cutover.clean)
        with self.assertRaises(AttributeError):
            cutover.pruned = ()
        with self.assertRaises(AttributeError):
            cutover.residual = ()

    async def test_the_applied_channel_rides_the_residual_out(self):
        class Creates(Step):
            def __init__(self) -> None:
                self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "missing")]), {}

            def apply(self, inputs):
                self.__done[0] = True
                return [DriftItem("svc", "created")], {}

        cutover = await Transition((), (Creates(),)).converge()
        self.assertTrue(cutover.clean)
        self.assertEqual([item.message for item in cutover.residual.applied], ["created"])

    async def test_an_unchanged_declaration_prunes_nothing(self):
        log: list = []
        world = {"stayer"}
        stayer = _Owned("stayer", log, world)
        cutover = await Transition((stayer,), (stayer,)).converge()
        self.assertTrue(cutover.clean)
        self.assertEqual(log, ["apply:stayer"])   # the idempotent re-apply of a converge - but NO prune


class _Rebuilt(_Owned):
    """The same resource assembled from data, so it names itself and survives being built twice."""

    @property
    def identifier(self) -> str:
        return self.name


class NamedIdentityTests(unittest.IsolatedAsyncioTestCase):
    """WHO IS A LEAVER is Step.paired's answer, so a successor may be REBUILT rather than shared.

    Matching by instance alone, a declaration reassembled from data made every step a leaver, so the teardown
    half tore the whole world down and the converge half rebuilt it. For a real prune that is not a misreading,
    it is a demolition."""

    async def test_a_rebuilt_named_declaration_tears_down_nothing(self):
        log: list = []
        world = {"kept"}
        cutover = await Transition((_Rebuilt("kept", log, world),), (_Rebuilt("kept", log, world),)).converge()

        self.assertTrue(cutover.clean)
        self.assertEqual(log, ["apply:kept"])   # the converge half runs, nothing torn down first
        self.assertEqual(world, {"kept"})

    async def test_an_unnamed_rebuild_still_demolishes_because_nothing_can_tell(self):
        # The older rule, unchanged where there is no name to read. Two unnamed instances of one kind are the
        # same picture as a genuine swap, which is why this is reported by Succession and not refused here.
        log: list = []
        world = {"kept"}
        await Transition((_Owned("kept", log, world),), (_Owned("kept", log, world),)).converge()
        self.assertEqual(log, ["prune:kept", "apply:kept"])

    async def test_a_named_step_dropped_from_the_declaration_is_still_a_leaver(self):
        log: list = []
        world = {"gone", "kept"}
        cutover = await Transition((_Rebuilt("gone", log, world), _Rebuilt("kept", log, world)),
                                   (_Rebuilt("kept", log, world),)).converge()

        self.assertTrue(cutover.clean)
        self.assertEqual(log, ["prune:gone", "apply:kept"])   # exactly the one leaver, nothing else
        self.assertEqual(world, {"kept"})


class AsyncStepTransitionTests(unittest.IsolatedAsyncioTestCase):
    class _AsyncOwned(Step):
        def __init__(self, name: str, log: list, world: set):
            self.name = name
            self.log = log
            self.world = world

        async def assess(self, inputs):
            await asyncio.sleep(0)
            return Assessment(deviation=[] if self.name in self.world else [DriftItem(self.name, "missing")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.world.add(self.name)
            self.log.append(f"apply:{self.name}")
            return None, {}

        async def prune(self, inputs):
            await asyncio.sleep(0)
            self.world.discard(self.name)
            self.log.append(f"prune:{self.name}")
            return [], {}

    async def test_the_cutover_awaits_both_halves_on_the_loop(self):
        log: list = []
        world = {"old"}
        leaver = self._AsyncOwned("old", log, world)
        newcomer = self._AsyncOwned("new", log, world)

        cutover = await Transition((leaver,), (newcomer,)).converge()
        self.assertTrue(cutover.clean)
        self.assertEqual(log, ["prune:old", "apply:new"])        # teardown first, awaited end to end

    def test_both_halves_are_reconcilers(self):
        # The knobs thread through to the two Reconcilers, so a coroutine step is first-class in each half.
        transition = Transition((), (self._AsyncOwned("n", [], set()),))
        self.assertIsInstance(transition._converge, Reconciler)
        self.assertIsInstance(transition._teardown, Reconciler)
        self.assertIsInstance(Transition((), ())._converge, Reconciler)