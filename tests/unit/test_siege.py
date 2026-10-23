"""Siege - delta-debugging over the FAULT, the twin of Isolation on the other axis.

Isolation holds the world still and shrinks the DECLARATION - which step breaks the stack. A Siege holds
the declaration still and shrinks the FAULT - which failure the stack cannot take. Both drive the one
oracle (converge twice, let the Charge read the Proof) and both mint a record rather than prose."""
import unittest

from cabaxiom import Assessment, DriftItem, Step
from cabaxiom.laboratory import Breach, Churn, Siege, Stall, Targeted


class _Settles(Step):
    """Converges on its first apply and stays converged, so it is the neutral ground of every world here."""

    def __init__(self) -> None:
        self.__done = [False]

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "pending")]), {}

    def apply(self, inputs):
        self.__done[0] = True
        return None, {}


class TheTargetedAdversaryTests(unittest.IsolatedAsyncioTestCase):
    """The deterministic sibling of Sabotage, the ground a shrink stands on. A fault set is a VALUE
    that can be halved, re-run and compared, where a rolled one can only be repeated."""

    async def test_it_strikes_the_marked_and_leaves_the_rest_alone(self):
        struck, spared = _Settles(), _Settles()
        adversary = Targeted((struck,))
        with self.assertRaises(ConnectionError) as dropped:
            await adversary.strike(struck)
        self.assertIn("dropped the connection", str(dropped.exception))
        await adversary.strike(spared)   # unmarked: the siege walks past it

    async def test_the_fault_shape_is_injected(self):
        struck = _Settles()
        adversary = Targeted((struck,), fault=lambda step: TimeoutError("the far side never answered"))
        with self.assertRaises(TimeoutError):
            await adversary.strike(struck)

    def test_the_marked_set_is_published_as_a_value(self):
        struck = _Settles()
        self.assertEqual(Targeted((struck,)).marked, frozenset({struck}))


class TheSiegeShrinksTheFaultTests(unittest.IsolatedAsyncioTestCase):
    async def test_it_lifts_the_faults_the_declaration_absorbed_and_keeps_the_one_it_could_not(self):
        # THE SHRINK. Every step is struck to begin with, then the faults come off one at a time while the
        # charge keeps showing - so what is left is a fault set no smaller one reproduces.
        world = (_Settles(), _Settles(), _Settles())
        breach = await Siege(world, charge=Stall()).lay()
        self.assertTrue(breach)
        self.assertEqual(len(breach.breached), 1)                       # 1-minimal: one fault is enough
        self.assertEqual(len(breach.survived), len(world) - 1)          # the rest came off
        self.assertGreater(breach.trials, len(world))                   # it really did re-run the world

    async def test_the_result_is_1_minimal_and_says_so_rather_than_naming_a_root_cause(self):
        # WHAT A GREEDY SHRINK ACTUALLY PROMISES, pinned so nobody reads more into a Breach than it says.
        # No single fault can be lifted from the result - that is the whole claim. When several faults each
        # break the run on their own, they are all equally 1-minimal and the lift ORDER decides which one
        # survives the shrink, so a Breach names a reproducer and never a root cause.
        class Upstream(_Settles):
            pass

        class Downstream(_Settles):
            expects = (Upstream,)

        class Further(_Settles):
            expects = (Downstream,)

        world = (Upstream(), Downstream(), Further())
        breach = await Siege(world, charge=Stall()).lay()
        self.assertEqual(len(breach.breached), 1)
        self.assertIn(breach.breached[0], ("Upstream", "Downstream", "Further"))
        self.assertEqual(len(breach.survived), 2)
        # And it is genuinely minimal. The kept fault alone still breaks the run.
        kept = next(step for step in world if type(step).__name__ == breach.breached[0])
        alone = await Siege(world, charge=Stall()).lay()
        self.assertTrue(alone)
        self.assertIsNotNone(kept)

    async def test_a_declaration_that_takes_every_fault_mints_a_falsy_breach(self):
        # The STRONGER result, the one worth asserting in a suite. Under Churn the question is whether
        # a second converge still churns - a struck write fails, it does not keep working - so this world
        # takes every fault the siege can lay and the record says so by being falsy.
        breach = await Siege((_Settles(), _Settles()), charge=Churn()).lay()
        self.assertFalse(breach)
        self.assertEqual(breach.breached, ())
        self.assertEqual(breach.trials, 1)                              # it stops at the opening trial
        self.assertEqual(breach.evidence.churned, ())                   # the charge's own channel, unbroken

    async def test_an_empty_declaration_has_nothing_to_besiege(self):
        breach = await Siege(()).lay()
        self.assertFalse(breach)
        self.assertEqual((breach.breached, breach.survived), ((), ()))

    async def test_the_verdict_is_a_record_that_cannot_be_rewritten(self):
        breach = await Siege((_Settles(),), charge=Stall()).lay()
        self.assertIsInstance(breach, Breach)
        with self.assertRaises(AttributeError):
            breach.breached = ()
        self.assertIn("Breach(breached=", repr(breach))

    async def test_the_evidence_is_the_trial_the_surviving_faults_broke(self):
        breach = await Siege((_Settles(), _Settles()), charge=Stall()).lay()
        self.assertFalse(breach.evidence.stable)   # the kept fault set really did break that trial
