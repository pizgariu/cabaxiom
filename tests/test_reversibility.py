"""Reversibility - the converge -> prune round trip must return the world to its first observed reading."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Reconciler, Step
from cabaxiom.laboratory import Reversibility, Roundtrip


class _Lifecycle(Step):
    # The full honest lifecycle. Builds, tears down completely and reads the world truthfully throughout.
    def __init__(self) -> None:
        self.__exists = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__exists[0] else [DriftItem("svc", "missing")]), {}

    def apply(self, inputs):
        self.__exists[0] = True

        return None, {}
    def prune(self, inputs):
        self.__exists[0] = False
        return [], {}


class ReversibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_honest_lifecycle_proves_reversible(self):
        roundtrip = await Reversibility(Reconciler((_Lifecycle(),))).prove()
        self.assertTrue(roundtrip)
        self.assertEqual(roundtrip.built, ())
        self.assertEqual(roundtrip.erased, ())
        self.assertEqual(roundtrip.restored, ())

    async def test_a_prune_that_claims_clean_while_the_artifact_stands_fails_restored(self):
        # The lie the erased channel alone can never catch. prune returns [] (a clean claim), yet the
        # artifact stays standing, so the closing reading no longer holds the opening's "missing" item.
        # Comparing against the OPENING reading, not emptiness, is what convicts it.
        class _Squatter(Step):
            def __init__(self) -> None:
                self.__exists = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__exists[0] else [DriftItem("svc", "missing")]), {}

            def apply(self, inputs):
                self.__exists[0] = True

                return None, {}
            def prune(self, inputs):
                return [], {}   # claims a clean teardown, removes nothing

        roundtrip = await Reversibility(Reconciler((_Squatter(),))).prove()
        self.assertFalse(roundtrip)
        self.assertEqual(roundtrip.erased, ())                                         # the claim reads clean...
        self.assertEqual([item.message for item in roundtrip.restored], ["missing"])   # ...the world does not

    async def test_a_run_that_tears_down_somebody_elses_world_fails_restored_honestly(self):
        # The other direction of the same comparison. The artifact PRE-EXISTS (built by someone else), so
        # the opening reading is clean. The round trip then removes it, so the closing reading carries a
        # "missing" the opening never had - the certificate refuses, because undo means THE FIRST reading.
        squatted = _Lifecycle()
        squatted.apply({})   # somebody else built it before the kernel ever looked

        roundtrip = await Reversibility(Reconciler((squatted,))).prove()
        self.assertFalse(roundtrip)
        self.assertEqual(roundtrip.built, ())
        self.assertEqual(roundtrip.erased, ())
        self.assertEqual([item.message for item in roundtrip.restored], ["missing"])

    async def test_a_world_that_never_converges_fails_built_and_only_built(self):
        # The round trip still runs to the end. An unreachable desired state dirties `built`, while the
        # unbuilt world comes back reading exactly as first observed, so `restored` stays clean.
        class _Stuck(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("stuck", "never clears")]), {}

        roundtrip = await Reversibility(Reconciler((_Stuck(),))).prove()
        self.assertFalse(roundtrip)
        self.assertEqual([item.message for item in roundtrip.built], ["never clears"])
        self.assertEqual(roundtrip.erased, ())
        self.assertEqual(roundtrip.restored, ())

    async def test_a_surviving_residue_fails_erased_and_only_erased(self):
        # An honest partial teardown. The artifact goes (the closing reading matches the opening), yet the
        # prune reports what survived - the lock it could not release dirties `erased` alone.
        class _Stubborn(Step):
            def __init__(self) -> None:
                self.__exists = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__exists[0] else [DriftItem("svc", "missing")]), {}

            def apply(self, inputs):
                self.__exists[0] = True

                return None, {}
            def prune(self, inputs):
                self.__exists[0] = False
                return [DriftItem("svc", "still holding a lock")], {}

        roundtrip = await Reversibility(Reconciler((_Stubborn(),))).prove()
        self.assertFalse(roundtrip)
        self.assertEqual(roundtrip.built, ())
        self.assertEqual([item.message for item in roundtrip.erased], ["still holding a lock"])
        self.assertEqual(roundtrip.restored, ())

    async def test_the_comparison_is_a_multiset_so_multiplicity_is_evidence(self):
        # Two steps read the SAME (name, message) at the opening. One restores honestly, one squats, so
        # the closing holds ONE of the pair - and restored carries exactly the one unbalanced item, not
        # zero (a set would blur them) and not two.
        class _Twin(Step):
            def __init__(self) -> None:
                self.__exists = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__exists[0] else [DriftItem("svc", "missing")]), {}

            def apply(self, inputs):
                self.__exists[0] = True

                return None, {}
            def prune(self, inputs):
                self.__exists[0] = False
                return [], {}

        class _SquattingTwin(_Twin):
            def prune(self, inputs):
                return [], {}   # keeps the artifact: its "missing" never comes back

        roundtrip = await Reversibility(Reconciler((_Twin(), _SquattingTwin()))).prove()
        self.assertEqual([item.message for item in roundtrip.restored], ["missing"])

    def test_a_minted_roundtrip_cannot_be_falsified_in_place(self):
        # The certificate is a RECORD: tuple channels behind read-only properties, so an irreversible
        # round trip cannot be flipped reversible after it was minted.
        roundtrip = Roundtrip([], [], [DriftItem("svc", "missing")])
        self.assertFalse(roundtrip)
        with self.assertRaises(AttributeError):
            roundtrip.restored = ()
        with self.assertRaises(AttributeError):
            roundtrip.built = ()

    async def test_the_repr_carries_the_verdict_and_all_three_channels(self):
        roundtrip = await Reversibility(Reconciler((_Lifecycle(),))).prove()
        self.assertIn("reversible=True", repr(roundtrip))
        self.assertIn("built=()", repr(roundtrip))
        self.assertIn("erased=()", repr(roundtrip))
        self.assertIn("restored=()", repr(roundtrip))

    async def test_the_harness_is_open_for_a_stricter_check(self):
        # Reversibility is the open base now the twin collapsed onto it. A custom harness subclasses it,
        # inheriting the wrapped reconciler, the comparison rule and the shared _verdict, then shapes its own.
        class TwiceAround(Reversibility):
            # A stricter harness. Two full round trips, judged against the one opening reading.
            async def prove(self) -> Roundtrip:
                opening = await self._reconciler.assess()
                await self._reconciler.converge()
                await self._reconciler.prune()
                built = await self._reconciler.converge()
                erased = await self._reconciler.prune()
                return self._verdict(built, erased, opening, await self._reconciler.assess())

        self.assertTrue(issubclass(TwiceAround, Reversibility))
        self.assertTrue((await TwiceAround(Reconciler((_Lifecycle(),))).prove()).reversible)


class AsyncReversibilityTests(unittest.IsolatedAsyncioTestCase):
    """The coroutine twin awaits the same four verbs and closes through the same shared _verdict."""

    class _AsyncLifecycle(Step):
        def __init__(self) -> None:
            self.__exists = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        def assess(self, inputs):
            return Assessment(deviation=[] if self.__exists[0] else [DriftItem("svc", "missing")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.__exists[0] = True

            return None, {}
        async def prune(self, inputs):
            await asyncio.sleep(0)
            self.__exists[0] = False
            return [], {}

    async def test_an_honest_async_lifecycle_proves_reversible(self):
        roundtrip = await Reversibility(Reconciler((self._AsyncLifecycle(),))).prove()
        self.assertTrue(roundtrip)
        self.assertEqual((roundtrip.built, roundtrip.erased, roundtrip.restored), ((), (), ()))

    async def test_the_async_certificate_refuses_the_same_squat(self):
        class _AsyncSquatter(self._AsyncLifecycle):
            async def prune(self, inputs):
                await asyncio.sleep(0)
                return [], {}   # claims clean, removes nothing

        roundtrip = await Reversibility(Reconciler((_AsyncSquatter(),))).prove()
        self.assertFalse(roundtrip)
        self.assertEqual([item.message for item in roundtrip.restored], ["missing"])
