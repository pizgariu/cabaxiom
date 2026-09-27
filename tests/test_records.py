"""Records - what a run hands back plus the one-way arrow that keeps them readable without the engine."""
import ast
import pathlib
import unittest

from cabaxiom import Explanation, Reconciler, Residual, Step, Unresolvable
from cabaxiom.drift import DriftItem
from support import A, B


class TheRecordsStandWithoutTheEngineTests(unittest.TestCase):
    """A record answers a question about a run that has already happened. It holds what it was handed and
    does no work, so it outlives the Reconciler that made it - and the arrow has to point one way for that
    to stay true. The engine imports the records. Nothing here imports the engine."""

    def test_the_records_module_imports_nothing_from_the_engine(self):
        source = pathlib.Path(__file__).parent.parent / "src" / "cabaxiom" / "records.py"
        pulled = set()
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                pulled.add(node.module)
            elif isinstance(node, ast.Import):
                pulled.update(alias.name for alias in node.names)
        self.assertNotIn("reconciler", pulled)
        self.assertNotIn("cabaxiom.reconciler", pulled)

    def test_a_residual_is_a_list_and_carries_what_was_applied_beside_it(self):
        # The whole reason it subclasses list. A caller testing truthiness or comparing against [] is
        # asking "did it converge", which has to keep working.
        stuck, done = DriftItem("Disk", "still full"), DriftItem("Cache", "cleared")
        record = Residual([stuck], [done])
        self.assertTrue(record)
        self.assertEqual(list(record), [stuck])
        self.assertEqual(record.applied, [done])
        self.assertEqual(Residual([], []), [])

    def test_a_residual_shows_both_channels_because_the_list_repr_hides_one(self):
        self.assertIn("applied=", repr(Residual([], [DriftItem("Cache", "cleared")])))

    def test_an_explanation_reads_as_the_flow_the_dispatcher_walks(self):
        self.assertEqual(repr(Explanation((("A",), ("B",)), ())), "Explanation((A) -> (B))")
        self.assertEqual(repr(Explanation((), ())), "Explanation(())")

    def test_the_reconciler_hands_back_the_records_and_re_resolves_nothing(self):
        reconciler = Reconciler((A([]), B([])))
        self.assertIsInstance(reconciler.explain(), Explanation)
        self.assertEqual(reconciler.explain().groups, reconciler.explain().groups)


class Db(Step):
    provides = frozenset({"storage"})

    async def assess(self):
        return self.verified()


class Cache(Step):
    async def assess(self):
        return self.verified()


class Api(Step):
    expects = (Cache,)
    demands = ("storage",)

    async def assess(self):
        return self.verified()


class Hopeful(Step):
    wants = ("nothing-provides-this",)

    async def assess(self):
        return self.verified()


class AnExplanationCarriesTheDeclarationsBehindItTests(unittest.TestCase):
    """`edges` says Api depends on Db. With eight slots in the language that is not enough to act on -
    a class named hardly, a capability named softly and an instance named by identity are three different
    situations with three different fixes, yet flattened they all read the same."""

    def test_each_reason_names_the_slot_the_name_and_what_it_resolved_to(self):
        told = Reconciler((Db(), Cache(), Api())).explain()
        self.assertEqual([str(reason) for reason in told.because("Api")],
                         ["Api.expects Cache -> Cache", "Api.demands 'storage' -> Db"])

    def test_a_reason_says_whether_the_declaration_was_hard(self):
        soft, hard = Reconciler((Db(), Cache(), Api())).explain().because("Api")
        self.assertFalse(soft.hard)      # expects trusts the world
        self.assertTrue(hard.hard)       # demands does not

    def test_a_soft_declaration_nothing_answered_still_shows_up_as_a_miss(self):
        # The shape worth seeing. A hard miss is refused before a run reaches here, so an empty `matched`
        # in an explanation is always a step that quietly ordered against nothing.
        miss, = Reconciler((Hopeful(),)).explain().because("Hopeful")
        self.assertEqual(miss.matched, ())
        self.assertIn("-> nothing", str(miss))

    def test_the_reasons_and_the_edges_describe_the_same_run(self):
        told = Reconciler((Db(), Cache(), Api())).explain()
        drawn = {step: set(needs) for step, needs in told.edges}
        for reason in told.reasons:
            self.assertTrue(set(reason.matched) <= drawn[reason.step])

    def test_a_step_that_declared_nothing_has_no_reasons(self):
        self.assertEqual(Reconciler((Db(), Cache(), Api())).explain().because("Cache"), ())

    def test_a_name_this_run_never_resolved_is_refused_rather_than_answered_with_nothing(self):
        # The defect this closes. A typo and a step that declared nothing both came back as (), so the
        # read that exists to explain a run quietly explained a step that was never in it.
        told = Reconciler((Db(), Cache(), Api())).explain()
        with self.assertRaises(Unresolvable) as refused:
            told.because("Cahce")
        self.assertIn("Cahce", str(refused.exception))
        self.assertEqual(told.because("Cache"), ())
