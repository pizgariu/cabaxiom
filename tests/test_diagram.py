"""Diagram - rendering a resolved run plus the seam that keeps a rendering bug out of the run."""
import ast
import pathlib
import unittest

from cabaxiom import Components, Mermaid, Parallel, Pipeline, Reconciler, Step
from cabaxiom.records import Explanation


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


class TheDrawingIsAnAxisTests(unittest.TestCase):
    """A diagram is handed a run that has already been resolved and can reach nothing else. So a rendering
    bug produces an ugly picture and never a wrong run, which is the reason for the seam."""

    def test_the_diagram_module_cannot_reach_the_engine_or_the_declarations(self):
        source = pathlib.Path(__file__).parent.parent / "src" / "cabaxiom" / "diagram.py"
        pulled = set()
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                pulled.add(node.module.lstrip("."))
        self.assertEqual(pulled & {"reconciler", "graph", "step", "partition"}, set())

    def test_a_diagram_renders_from_a_bare_explanation_with_no_run_behind_it(self):
        drawn = Mermaid()(Explanation((("Only",),), (), (), "wave"))
        self.assertIn('subgraph g0["wave 1"]', drawn)
        self.assertIn("Only[Only]", drawn)


class MermaidTests(unittest.TestCase):
    """Groups become subgraphs, so the structure is what a reader sees before any arrow."""

    def test_waves_and_chains_are_named_by_the_shape_that_produced_them(self):
        steps = (Db(), Cache(), Api())
        self.assertIn('subgraph g1["wave 2"]', Mermaid()(Reconciler(steps, dispatcher=Parallel()).explain()))
        chained = Reconciler((Db(), Cache(), Api()), Components(), dispatcher=Pipeline()).explain()
        self.assertIn('subgraph g0["chain 1"]', Mermaid()(chained))

    def test_a_soft_edge_is_dashed_and_a_hard_one_is_solid(self):
        drawn = Mermaid()(Reconciler((Db(), Cache(), Api())).explain())
        self.assertIn("Cache -.->|expects| Api", drawn)
        self.assertIn("Db -->|demands 'storage'| Api", drawn)

    def test_an_arrow_does_not_say_the_name_twice_when_the_name_is_the_target(self):
        # `expects Cache -> Cache` is the same word twice. A capability or an instance is not.
        drawn = Mermaid()(Reconciler((Db(), Cache(), Api())).explain())
        self.assertNotIn("expects Cache|", drawn)

    def test_a_declaration_nothing_answered_draws_no_arrow(self):
        class Hopeful(Step):
            wants = ("nothing-provides-this",)

            async def assess(self):
                return self.verified()

        drawn = Mermaid()(Reconciler((Hopeful(),)).explain())
        self.assertNotIn("-->", drawn)
        self.assertNotIn("-.->", drawn)

    def test_an_empty_run_still_renders_a_flowchart(self):
        self.assertEqual(Mermaid()(Explanation((), ())), "flowchart TD")
