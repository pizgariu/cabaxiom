"""Isolation - shrink a failing declaration to the smallest edge-closed subset that still shows the charge."""
import asyncio
import unittest

from cabaxiom import Assessment, Charge, Churn, DriftItem, Indictment, Isolation, Proof, Stall, Step


class _Innocent(Step):
    # Settles cleanly and stays settled - one drift, one apply, idempotent ever after.
    def __init__(self) -> None:
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("innocent", "needs one fix")]), {}

    def apply(self, inputs):
        self.__done[0] = True
        return None, {}
class _Churner(Step):
    # The non-idempotent tell. Drift always reads clean, yet apply reports work on every converge.
    def assess(self, inputs):
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        return [DriftItem("cache", "rebuilt again")], {}


class _Stuck(Step):
    # Never converges. The drift no apply clears.
    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("stuck", "never clears")]), {}

    def apply(self, inputs):
        return None, {}


class IsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_hunt_convicts_the_churner_and_dismisses_the_innocent(self):
        # Three steps, one guilty. The hunt dismisses both innocents (the charge kept showing without
        # them) and cannot shrink past the churner, whose own trial is attached as the evidence.
        indictment = await Isolation((_Innocent(), _Churner(), _Innocent())).isolate()
        self.assertTrue(indictment)
        self.assertEqual(indictment.accused, ("_Churner",))
        self.assertEqual(indictment.dismissed, ("_Innocent", "_Innocent#2"))
        self.assertFalse(indictment.evidence.stable)
        self.assertEqual([item.message for item in indictment.evidence.churned], ["rebuilt again"])
        self.assertEqual(indictment.trials, 4)   # the full set, then three shrink attempts

    async def test_a_dependent_travels_with_its_prerequisite_so_every_trial_is_a_legal_world(self):
        # The down-set rule, end to end. The rider declares edges into BOTH other steps, so dismissing
        # either prerequisite pulls the rider out with it, so no trial ever runs the rider without what
        # it stands on. The rider dismissed mid-pass is then skipped as a suspect of its own.
        class _Rider(Step):
            expects = (_Churner, _Innocent)

        indictment = await Isolation((_Churner(), _Innocent(), _Rider())).isolate()
        self.assertEqual(indictment.accused, ("_Churner",))
        self.assertEqual(indictment.dismissed, ("_Innocent", "_Rider"))
        self.assertEqual(indictment.trials, 3)   # the full set, the failed churner dismissal, the innocent's

    async def test_the_stall_charge_names_the_step_that_never_settles(self):
        indictment = await Isolation((_Innocent(), _Stuck()), charge=Stall()).isolate()
        self.assertTrue(indictment)
        self.assertEqual(indictment.accused, ("_Stuck",))
        self.assertEqual(indictment.dismissed, ("_Innocent",))
        self.assertEqual([item.message for item in indictment.evidence.residual], ["never clears"])

    async def test_an_innocent_declaration_returns_a_falsy_indictment_with_the_proof(self):
        # No charge, no case. One trial over the full set, nobody accused, where the evidence is that
        # innocent Proof - the isolation doubles as the idempotence check it generalises.
        indictment = await Isolation((_Innocent(), _Innocent())).isolate()
        self.assertFalse(indictment)
        self.assertEqual(indictment.accused, ())
        self.assertEqual(indictment.dismissed, ())
        self.assertEqual(indictment.trials, 1)
        self.assertTrue(indictment.evidence.stable)

    async def test_the_charge_axis_is_open(self):
        # A custom charge hunts its own failure shape. Here, a specific drift name surviving the trial.
        class _NamedGrudge(Charge):
            def shows(self, proof: Proof) -> bool:
                return any(item.name == "stuck" for item in proof.residual)

        indictment = await Isolation((_Stuck(), _Churner()), charge=_NamedGrudge()).isolate()
        self.assertEqual(indictment.accused, ("_Stuck",))   # the churner churns, yet that is not the charge
        self.assertEqual(indictment.dismissed, ("_Churner",))

    def test_a_minted_indictment_cannot_be_falsified_in_place(self):
        # The verdict is a RECORD: tuples behind read-only properties, so a conviction cannot be rewritten
        # after the hunt that minted it.
        indictment = Indictment(("Guilty",), (), Proof([DriftItem("cache", "rebuilt again")], []), 1)
        self.assertTrue(indictment)
        with self.assertRaises(AttributeError):
            indictment.accused = ()
        with self.assertRaises(AttributeError):
            indictment.evidence = None

    async def test_the_indictment_repr_carries_the_whole_case(self):
        indictment = await Isolation((_Churner(),)).isolate()
        self.assertIn("accused=('_Churner',)", repr(indictment))
        self.assertIn("trials=1", repr(indictment))
        self.assertIn("Proof(", repr(indictment))


class AsyncStepIsolationTests(unittest.IsolatedAsyncioTestCase):
    """The hunt over steps whose apply() awaits I/O, so a coroutine write is first-class in a trial."""

    class _AsyncChurner(Step):
        def assess(self, inputs):
            return Assessment(deviation=[]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            return [DriftItem("cache", "rebuilt again")], {}

    class _AsyncInnocent(Step):
        def __init__(self) -> None:
            self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        def assess(self, inputs):
            return Assessment(deviation=[] if self.__done[0] else [DriftItem("innocent", "needs one fix")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.__done[0] = True
            return None, {}

    async def test_the_async_hunt_convicts_the_same_churner(self):
        # Supplied churner-first, so the hunt also walks a FAILED dismissal (dropping the churner makes
        # the charge vanish, the suspect stays) before the innocent is dismissed.
        indictment = await Isolation((self._AsyncChurner(), self._AsyncInnocent())).isolate()
        self.assertTrue(indictment)
        self.assertEqual(indictment.accused, ("_AsyncChurner",))
        self.assertEqual(indictment.dismissed, ("_AsyncInnocent",))
        self.assertEqual(indictment.trials, 3)
        self.assertFalse(indictment.evidence.stable)

    async def test_the_async_falsy_case_matches_the_sync_one(self):
        indictment = await Isolation((self._AsyncInnocent(),), charge=Churn()).isolate()
        self.assertFalse(indictment)
        self.assertEqual(indictment.trials, 1)

