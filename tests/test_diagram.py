"""Diagram - rendering a resolved run plus the seam that keeps a rendering bug out of the run."""
import ast
import os
import pathlib
import shutil
import subprocess
import unittest

from cabaxiom import Components, Dot, Mermaid, Parallel, Pipeline, Reconciler, Step
from cabaxiom.records import Explanation, Reason


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


class DotTests(unittest.TestCase):
    """Graphviz DOT. Groups become clusters, where the `cluster_` prefix is not decoration - it is what
    makes Graphviz draw the box at all."""

    def test_groups_become_clusters_labelled_by_the_shape(self):
        drawn = Dot()(Reconciler((Db(), Cache(), Api()), dispatcher=Parallel()).explain())
        self.assertIn("subgraph cluster_0 {", drawn)
        self.assertIn('label="wave 1";', drawn)

    def test_a_soft_edge_is_dashed_and_a_hard_one_is_not(self):
        drawn = Dot()(Reconciler((Db(), Cache(), Api())).explain())
        self.assertIn('"Cache" -> "Api" [label="expects", style=dashed];', drawn)
        self.assertIn('"Db" -> "Api" [label="demands \'storage\'"];', drawn)

    def test_a_label_cannot_break_out_of_its_own_quotes(self):
        # DOT quotes attribute values, so a double quote inside a label would end it early and produce
        # source that does not parse. A capability label is caller-supplied text, so it gets flattened.
        drawn = Dot()(Explanation((("A",),), (), (Reason("A", "wants", '"odd"', ("B",), False),), "wave"))
        self.assertIn("label=\"wants 'odd'\"", drawn)
        self.assertEqual(drawn.count('"'), drawn.count('"'))

    def test_graphviz_itself_accepts_the_output(self):
        if shutil.which("dot") is None:
            self.skipTest("graphviz not installed")
        drawn = Dot()(Reconciler((Db(), Cache(), Api())).explain())
        run = subprocess.run(["dot", "-Tsvg", "-o", os.devnull], input=drawn, text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)


class BothRenderersDrawTheSameRunTests(unittest.TestCase):
    """The second renderer is what proves the axis was real. The two languages agree on nothing except
    what has to be drawn, so anything both of them get right came from the shared seam and not from luck."""

    def test_both_draw_every_group_and_every_resolved_edge(self):
        told = Reconciler((Db(), Cache(), Api())).explain()
        for drawn in (Mermaid()(told), Dot()(told)):
            for group in told.groups:
                for step in group:
                    self.assertIn(step, drawn)
            for reason in told.reasons:
                for found in reason.matched:
                    self.assertIn(found, drawn)

    def test_both_mark_exactly_the_soft_edges_and_no_others(self):
        told = Reconciler((Db(), Cache(), Api())).explain()
        soft = sum(1 for reason in told.reasons for _ in reason.matched if not reason.hard)
        self.assertEqual(Mermaid()(told).count("-.->"), soft)
        self.assertEqual(Dot()(told).count("style=dashed"), soft)
