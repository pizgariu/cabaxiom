"""The guard/seam pairing, asserted as a structure rather than trusted as a convention.

Seven axes are built the same way. A PUBLIC concrete guard holds an invariant and calls an abstract seam
the subclass implements. The guard is `typing.final`, so a type checker refuses an override of it while the
seam stays open. Without this test the marking is a decorator anyone can quietly drop, which is exactly the
kind of promise this kernel refuses to leave as prose - a four-line Arranger once skipped the hard-presence
rule because its guard was abstract. That is the class of hole the pairing closes."""
import ast
import dataclasses
import inspect
import pathlib
import unittest
from collections.abc import Sequence
from unittest import mock

import cabaxiom.core
import cabaxiom.laboratory  # never arrives on `import cabaxiom` alone, which is the point
from cabaxiom import Assessment
from cabaxiom.core.declaration.vocabulary import BY_CLASS, BY_INSTANCE, BY_LABEL, EdgeKind, Vocabulary
from cabaxiom.core.plan.partition import Placement
from cabaxiom.core.record.diagram import STYLING

# The default language, minted once for these assertions - the kernel itself mints it per derivation.
SHIPPED = Vocabulary.shipped()

# (owner, the guard that must be final, the seam that must stay open)
#
# Every seam is abstract, because an engine has no business guessing its policy - the kernel cannot guess
# how you narrow a selection or shape a partition. Where an honest default EXISTS it ships as a @final
# LEAF instead of a defaulted method body (Retry under BaseRetry retries every failure), so the family
# still works as handed while ABCMeta refuses a policy that forgot to answer the question at all. This
# table once carried a fourth column marking the one defaulted seam, which the leaf split deleted.
# The dispatcher axis stays in the table: ThreadDispatcher is a DECORATOR over an underlying dispatcher
# rather than a WavesDispatcher subclass, so nothing overrides WavesDispatcher.execute and it keeps its
# @final guard over the run_wave seam - the async collapse cost the doctrine nothing here.
GUARDED = (
    ("BaseNamed", "select", "narrow"),
    ("BaseTagged", "select", "keeps"),
    ("BaseLooping", "passes", "deciding"),
    ("BaseRetry", "around", "retryable"),
    ("Partition", "verify", "placement"),
    ("WavesDispatcher", "execute", "run_wave"),
    ("Arranger", "arrange", "shape"),
)


class GuardAndSeamTests(unittest.IsolatedAsyncioTestCase):
    def test_every_guard_is_final(self):
        for owner, guard, _ in GUARDED:
            with self.subTest(guard=f"{owner}.{guard}"):
                held = getattr(getattr(cabaxiom.core, owner), guard)
                self.assertTrue(getattr(held, "__final__", False),
                                f"{owner}.{guard} holds an invariant and must refuse an override")

    def test_every_seam_stays_open(self):
        # The other half of the pairing. Closing the guard is only honest while the seam it guards is
        # implementable, which is what makes the axis extensible at all.
        for owner, _, seam in GUARDED:
            with self.subTest(seam=f"{owner}.{seam}"):
                cls = getattr(cabaxiom.core, owner)
                self.assertFalse(getattr(getattr(cls, seam), "__final__", False),
                                 f"{owner}.{seam} is the way in, so it must stay open")

    def test_every_seam_is_abstract_and_the_honest_default_ships_as_a_leaf(self):
        for owner, _, seam in GUARDED:
            with self.subTest(seam=f"{owner}.{seam}"):
                self.assertIn(seam, getattr(cabaxiom.core, owner).__abstractmethods__)
        # The one family with an honest default ships it as the @final Retry leaf, usable as handed, so
        # the abstract seam costs nothing - except the silent inherit a forgotten policy used to get.
        self.assertTrue(cabaxiom.core.Retry(2).retryable(cabaxiom.core.Step(), 1, RuntimeError("x")))

    def test_a_seam_is_never_the_axis_protocol_itself(self):
        # Marking the ABSTRACT axis method final instead of the guard would close the axis outright. The two
        # easy to confuse: Convergence.passes is the axis, BaseLooping.passes is its guard; and Dispatcher.
        # execute is the axis's abstract entry while WavesDispatcher.execute is the @final wave guard above
        # run_wave - so the axis method itself must stay open.
        for axis, method in (("Convergence", "passes"), ("Dispatcher", "execute")):
            with self.subTest(axis=f"{axis}.{method}"):
                self.assertFalse(getattr(getattr(getattr(cabaxiom.core, axis), method), "__final__", False))


# Every verb along the spine takes the run's Graph and NOTHING beside it. The membership used to travel as a
# second argument next to the derivation over it, where nothing checked that the two described the same world.
# a mismatched pair surfaced as a raw KeyError from inside a placement check or as a coverage error blaming
# an Ordering for a fault that was never its own. Reading the membership off the derivation makes the
# disagreement unexpressible rather than merely unlikely, which is the same move as a shape declaring its
# rule by the Partition it returns. This test is what keeps it that way, since re-adding the parameter is a
# one-line edit that every other test in the suite would happily accept.
SPINE = (
    ("Ordering", "flat", ("self", "graph")),
    ("Ordering", "waves", ("self", "graph")),
    ("Ordering", "chains", ("self", "graph")),
    ("Kahn", "flat", ("self", "graph")),
    ("Kahn", "waves", ("self", "graph")),
    ("DFS", "flat", ("self", "graph")),
    ("Priority", "flat", ("self", "graph")),
    ("Components", "flat", ("self", "graph")),
    ("Components", "chains", ("self", "graph")),
    ("Arranger", "arrange", ("self", "ordering", "graph")),
    ("Arranger", "shape", ("self", "ordering", "graph")),
    ("BaseFan", "shape", ("self", "ordering", "graph")),
    ("Walk", "shape", ("self", "ordering", "graph")),
    ("RunMode", "resolve", ("self", "ordering", "graph")),
)


class DerivationIsTheWholeInputTests(unittest.IsolatedAsyncioTestCase):
    def test_every_spine_verb_takes_the_graph_alone(self):
        for owner, verb, expected in SPINE:
            with self.subTest(verb=f"{owner}.{verb}"):
                taken = tuple(inspect.signature(getattr(getattr(cabaxiom.core, owner), verb)).parameters)
                self.assertEqual(taken, expected,
                                 f"{owner}.{verb} must take the Graph alone, so its membership and its "
                                 f"edges cannot describe different worlds")

    def test_the_graph_publishes_the_membership_it_was_derived_over(self):
        # What makes the second argument removable at all. The derivation already held the set, in supplied
        # order and had held it since construction. It was published, not computed.
        steps = (cabaxiom.core.Step(), cabaxiom.core.Step())
        self.assertEqual(cabaxiom.core.Graph(steps).steps, steps)

    def test_the_executor_answers_for_the_shape_it_walks(self):
        # RunMode.resolve is sealed delegation to the arranger it composes, then the pairing guard on the
        # partition returned. The arranger is held privately by the RunMode - a component nobody downstream
        # drives, so a caller cannot pair one mode's shape with another worker. The component stays composed
        # and private, so the RunMode answers.
        self.assertTrue(getattr(cabaxiom.core.RunMode.resolve, "__final__", False),
                        "RunMode.resolve must refuse an override or a subclass could answer with a "
                        "partition its own arranger did not build and verify")
        self.assertFalse(hasattr(cabaxiom.core.Parallel(), "arranger"),
                         "the composed arranger is the RunMode's own, not a published handle")


class DiagramAxisTests(unittest.IsolatedAsyncioTestCase):
    """The drawing is an axis like any other - a sealed walk, an open seam and final leaves. The walk is
    what makes it worth being one - which nodes exist, which group each sits in, what identity each is
    given and in what order the arrows come are facts about the RUN, so no format may answer them
    differently."""

    def test_the_walk_is_sealed_and_every_syntax_seam_is_open(self):
        self.assertTrue(getattr(cabaxiom.core.Diagram.render, "__final__", False))
        self.assertEqual(set(cabaxiom.core.Diagram.__abstractmethods__),
                         {"opening", "grouped", "arrow", "closing"})

    def test_both_shipped_formats_are_final_leaves(self):
        for leaf in (cabaxiom.core.Dot, cabaxiom.core.Mermaid):
            with self.subTest(leaf=leaf.__name__):
                self.assertTrue(getattr(leaf, "__final__", False))
                self.assertTrue(issubclass(leaf, cabaxiom.core.Diagram))

    def test_a_custom_format_inherits_the_walk_it_never_writes(self):
        # Four small methods buy the whole run - identity, grouping, ordering and the per-kind arrows.
        class Plain(cabaxiom.core.Diagram):
            def opening(self): return ("RUN",)
            def grouped(self, title, index, members):
                return (title,) + tuple(f"{node}={label}" for node, label, _ in members)
            def arrow(self, prerequisite, dependent, slot, tone): return f"{prerequisite}<{slot}<{dependent}"
            def closing(self, used): return ("END",)

        class Db(cabaxiom.core.Step):
            pass

        class Api(cabaxiom.core.Step):
            expects = (Db,)

        drawn = Plain().render(cabaxiom.core.Reconciler((Api(), Db())).explain()).splitlines()
        self.assertEqual(drawn, ["RUN", "wave 0", "n0=Db", "wave 1", "n1=Api", "n0<expects<n1", "END"])

    def test_a_casualty_paints_the_run_it_forecasts(self):
        # The forecast and its picture are one value seen twice. Marks come straight off the Casualty,
        # so a drawing cannot claim a step survives while the forecast says it is blocked.
        class Db(cabaxiom.core.Step):
            pass

        class Api(cabaxiom.core.Step):
            expects = (Db,)

        steps = (Db(), Api())
        reconciler = cabaxiom.core.Reconciler(steps, mode=cabaxiom.core.Parallel())
        casualty = reconciler.foresee(steps[0])
        self.assertEqual(casualty.marks, {"Db": "failed", "Api": "blocked"})
        drawn = reconciler.explain().mermaid(casualty.marks)
        self.assertIn("class n0 failed", drawn)
        self.assertIn("class n1 blocked", drawn)
        self.assertIn("classDef failed", drawn)
        self.assertIn("classDef blocked", drawn)
        self.assertNotIn("classDef skipped", drawn)   # only the marks this drawing actually used

    def test_a_halt_forecast_paints_every_channel_it_reports(self):
        # Halt gates by run POSITION, so the same failure has two more readings the graph alone cannot
        # give. The group-mates that settle plus everything a later group never starts. Both reach the
        # drawing, where DOT fills a marked node inline and Mermaid declares a class for it.
        class Db(cabaxiom.core.Step):
            pass

        class Cache(cabaxiom.core.Step):
            pass

        class Api(cabaxiom.core.Step):
            expects = (Db,)

        db, cache, api = Db(), Cache(), Api()
        reconciler = cabaxiom.core.Reconciler((db, cache, api), mode=cabaxiom.core.Parallel())
        casualty = reconciler.foresee(db)
        self.assertEqual(casualty.marks,
                         {"Db": "failed", "Cache": "settling", "Api": "blocked"})
        drawn = reconciler.explain().dot(casualty.marks)
        self.assertIn('n0 [label="Db", fillcolor="#ffc9c9"', drawn)      # the culprit, filled red
        self.assertIn('n1 [label="Cache", fillcolor="#ffec99"', drawn)   # indeterminate, filled amber
        self.assertIn('n2 [label="Api", fillcolor="#ffd8a8"', drawn)     # blocked, filled orange

    def test_an_unmarked_run_draws_no_paint_at_all(self):
        # The everyday case stays clean - no marks, no fills, no class declarations.
        class Solo(cabaxiom.core.Step):
            pass

        explanation = cabaxiom.core.Reconciler((Solo(),)).explain()
        self.assertNotIn("fillcolor", explanation.dot())
        self.assertNotIn("classDef", explanation.mermaid())


class TheProofCannotBeForgedTests(unittest.IsolatedAsyncioTestCase):
    """An empty residual is this kernel's whole claim, so nothing that merely WATCHES a run may rewrite it,
    and no verdict may change after the run that minted it. Both of these were open until they were caught
    reading the surface for what a later major would have to break - and neither needed a major."""

    async def test_an_observer_is_handed_a_tuple_it_cannot_rewrite(self):
        # A trace that can alter what it traces is not a trace. An observer appending to the list it was
        # handed once made a verified-clean run come back dirty, while a Chorus relayed the same object
        # onward, so one member could alter what a later one saw. An earlier fix closed that with a copy, which
        # DISCARDED the mutation in silence - the hooks now receive a tuple under a Sequence annotation,
        # so the same code is refused with an AttributeError instead of quietly doing nothing.
        witnessed: list[type] = []

        class Settled(cabaxiom.core.Step):
            pass

        class Witness(cabaxiom.core.Observer):
            def acted(self, applied: Sequence[cabaxiom.core.Drift]) -> None:
                witnessed.append(type(applied))

            def remained(self, residual: Sequence[cabaxiom.core.Drift]) -> None:
                witnessed.append(type(residual))

            def pruned(self, residual: Sequence[cabaxiom.core.Drift]) -> None:
                witnessed.append(type(residual))

        reconciler = cabaxiom.core.Reconciler((Settled(),), observer=Witness())
        self.assertEqual(await reconciler.converge(), [])
        self.assertEqual(await reconciler.prune(), [])
        self.assertEqual(witnessed, [tuple, tuple, tuple])
        with self.assertRaises(AttributeError):
            tuple().append   # noqa: B018 - the refusal every hook now inherits, spelled out

    async def test_a_cutover_verdict_settles_when_it_is_minted(self):
        # `clean` used to be computed from the held Residual on every read, so appending to
        # `cutover.residual` after the fact flipped a clean transition to dirty - while the record's own
        # docstring promised a caller could not falsify it in place.
        class Arrived(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        cutover = await cabaxiom.core.Transition([], [Arrived()]).converge()
        self.assertTrue(cutover.clean)
        with self.assertRaises(AttributeError):
            cutover.residual.append(cabaxiom.core.DriftItem("forged", "after the fact"))   # type: ignore[attr-defined]
        self.assertTrue(cutover.clean, "the verdict must say what was true when the run ended")
        self.assertTrue(cutover)

    async def test_a_retry_takes_the_whole_trace_like_every_other_axis(self):
        # It used to be handed `observer.retried`, one hook plucked off another axis by the composer, which
        # put the knowledge of WHICH hook a retry fires in the reconciler rather than in the retry.
        taken = tuple(inspect.signature(cabaxiom.core.BaseRetry.around).parameters)
        self.assertEqual(taken, ("self", "do", "observer"))

        seen: list[tuple[str, int]] = []

        class Watching(cabaxiom.core.Observer):
            def retried(self, step: cabaxiom.core.Step, attempt: int, error: Exception) -> None:
                seen.append((step.__class__.__name__, attempt))

        class Flaky(cabaxiom.core.Step):
            tries = 0

            def assess(self, inputs):
                return Assessment(deviation=[] if Flaky.tries >= 2 else [cabaxiom.core.DriftItem("Flaky", "absent")]), {}

            def apply(self, inputs):
                Flaky.tries += 1
                if Flaky.tries < 2:
                    raise RuntimeError("not yet")
                return [], {}

        await cabaxiom.core.Reconciler((Flaky(),), observer=Watching(), retry=cabaxiom.core.Retry(3)).converge()
        self.assertEqual(seen, [("Flaky", 1)])


class PartitionIsComposedTests(unittest.IsolatedAsyncioTestCase):
    """Composition over inheritance, for the one payoff that matters here. The old tuple base defeated the
    ABC it stood under, because tuple's C-level __new__ skips the abstractmethod instantiate-check - an
    incomplete custom shape constructed happily and failed at its first verify(). ABCMeta's refusal is
    real now, so the fail-at-construction doctrine reaches the run structure itself."""

    def test_a_shape_that_forgot_its_placement_cannot_be_constructed(self):
        class Shapeless(cabaxiom.core.Partition):
            pass

        with self.assertRaises(TypeError) as refused:
            Shapeless((("a",),))
        self.assertIn("placement", str(refused.exception))

    def test_the_groups_stay_reachable_all_three_ways(self):
        walked = cabaxiom.core.WalkPartition((("a", "b"), ("c",)))
        self.assertEqual(walked.groups, (("a", "b"), ("c",)))   # the executor hand-off, a plain tuple
        self.assertEqual(len(walked), 2)                        # and len()
        self.assertEqual(tuple(walked), walked.groups)          # and iteration
        self.assertNotIsInstance(walked, tuple)                 # but the partition IS not its storage


class VocabularyIsTheOneHomeTests(unittest.IsolatedAsyncioTestCase):
    """The edge kinds are DATA - the Type Object pattern - and every consumer reads the one table. The
    proof is the experiment that motivated the recut, rerun as a regression. A seventh kind used to break
    SIX places at once (underived, invisible to matching, uncarried by explain, unvetted at class
    definition, undrawable and misclassified by Match.soft - wrong without a sound). Now it is one row."""

    def test_the_shipped_table_is_the_vocabulary_the_docs_teach(self):
        self.assertEqual([kind.slot for kind in SHIPPED],
                         ["expects", "requires", "prepares", "mandates", "wants", "demands", "uses", "needs"])
        self.assertEqual([kind.slot for kind in SHIPPED if kind.precedes], ["prepares", "mandates"])
        by_slot = {kind.slot: kind for kind in SHIPPED}
        for kind in SHIPPED:
            if kind.counterpart is None:
                continue
            with self.subTest(pair=f"{kind.slot}/{kind.counterpart}"):
                self.assertEqual(by_slot[kind.counterpart].counterpart, kind.slot)        # pairs both ways
                self.assertNotEqual(by_slot[kind.counterpart].hard, kind.hard)            # and differ in hardness
                self.assertEqual(by_slot[kind.counterpart].addressing, kind.addressing)   # over one addressing

    def test_each_addressing_speaks_a_whole_refusal(self):
        # The refusal vocabulary is part of the contract, including the words no shipped kind uses yet. A
        # future hard instance-kind must arrive already able to say what is missing.
        self.assertEqual(BY_CLASS.absent("Db"), "but no Db is in the run")
        self.assertEqual(BY_LABEL.absent("'db'"), "but no step in the run provides it")
        self.assertEqual(BY_INSTANCE.absent("Db"), "but that instance is not in the run")
        for addressing in (BY_CLASS, BY_LABEL, BY_INSTANCE):
            with self.subTest(addressing=addressing.__class__.__name__):
                self.assertTrue(addressing.takes and addressing.stray and addressing.noun and addressing.vow)

    def test_a_match_carries_its_kinds_own_record(self):
        class Db(cabaxiom.core.Step):
            provides = frozenset({"db"})

        class Api(cabaxiom.core.Step):
            wants = ("db",)

        db, api = Db(), Api()
        match = cabaxiom.core.Graph((db, api)).matching(api)[0]
        self.assertEqual(match.kind.slot, "wants")
        self.assertFalse(match.kind.hard)
        self.assertEqual(match.kind.counterpart, "demands")
        self.assertTrue(match.soft)   # read off the record, never a hardcoded name list

    def test_a_grown_kind_lands_as_one_row(self):
        # The morning experiment, inverted - and no patching left. The vocabulary is an INJECTED axis now,
        # so a domain grows the language the way it injects anything else, with every consumer following with
        # no edit - the derivation, the per-name view, the softness read and the structural explain.
        grown = SHIPPED.grown(EdgeKind("also_after", BY_CLASS, hard=False, counterpart=None, colour="#123456"))

        class Anchor(cabaxiom.core.Step):
            pass

        class Rider(cabaxiom.core.Step):
            also_after = (Anchor,)   # unknown at class definition, vetted at derivation - the second gate

        anchor, rider = Anchor(), Rider()
        graph = cabaxiom.core.Graph((anchor, rider), grown)
        self.assertEqual(graph.dependencies(rider), (anchor,))            # 1. derived
        match = graph.matching(rider)[0]
        self.assertEqual(match.slot, "also_after")   # 2. visible per name
        self.assertTrue(match.soft)                  # 3. classified right
        explanation = cabaxiom.core.Reconciler((rider, anchor), vocabulary=grown).explain()
        self.assertEqual(explanation.declared["also_after"],
                         (("Rider", ("Anchor",)),))                       # 4. carried by explain
        self.assertEqual(explanation.groups, (("Anchor",), ("Rider",)))   # and it truly ordered the run
        self.assertEqual([kind.slot for kind in explanation.vocabulary][-1],
                         "also_after")                                    # 5. and the reading says what it spoke

    def test_a_grown_kinds_container_is_vetted_at_class_definition(self):
        grown = SHIPPED.grown(EdgeKind("also_after", BY_CLASS, hard=False, counterpart=None, colour="#123456"))
        with mock.patch.object(Vocabulary, "shipped", return_value=grown):
            with self.assertRaises(TypeError) as refused:
                class Rider(cabaxiom.core.Step):
                    also_after = (cabaxiom.core.Step)   # the forgotten comma, on a kind that did not exist
            self.assertIn("also_after must be a tuple", str(refused.exception))   # 5. vetted unedited

    def test_the_drawing_styles_every_kind_in_the_table(self):
        # 6. drawable: STYLING is BUILT from the vocabulary at import, so it cannot miss a slot - and the
        # paint derives from what a kind IS (hard is bold, a soft capability lean is dashed).
        self.assertEqual(set(STYLING), {kind.slot for kind in SHIPPED})
        self.assertIn("penwidth=2", STYLING["requires"].dot)
        self.assertEqual(STYLING["wants"].mermaid, "-.->")
        self.assertEqual(STYLING["expects"].mermaid, "-->")


class VocabularyIsAnInjectedAxisTests(unittest.IsolatedAsyncioTestCase):
    """The vocabulary is injected like every other axis, never registered. The kernel holds no global
    mutable state, so a language grows by handing a bigger table to the run that speaks it - and the
    table validates at construction, the fail-at-construction doctrine on the axis that carries all the
    others' words."""

    def test_an_empty_or_twice_declared_language_is_refused(self):
        with self.assertRaises(ValueError):
            Vocabulary()
        with self.assertRaises(ValueError) as refused:
            SHIPPED.grown(EdgeKind("expects", BY_CLASS, hard=False, counterpart=None, colour="#000000"))
        self.assertIn("`expects` twice", str(refused.exception))

    def test_a_broken_counterpart_pairing_is_refused_with_the_rule(self):
        with self.assertRaises(ValueError) as missing:
            Vocabulary(EdgeKind("solo", BY_CLASS, hard=True, counterpart="ghost", colour="#000000"))
        self.assertIn("no such kind", str(missing.exception))
        with self.assertRaises(ValueError) as unpaired:
            Vocabulary(
                EdgeKind("this", BY_CLASS, hard=True, counterpart="that", colour="#000000"),
                EdgeKind("that", BY_CLASS, hard=True, counterpart="this", colour="#111111"),
            )
        self.assertIn("differ in hardness", str(unpaired.exception))

    def test_a_kind_guards_itself_the_moment_it_is_minted(self):
        # A VALUE OBJECT's own gate, one earlier than the Vocabulary's. The row refuses itself, so a bad
        # slot never even reaches a table and a kind cannot be its own counterpart.
        with self.assertRaises(ValueError) as refused:
            EdgeKind("not a name", BY_CLASS, hard=False, counterpart=None, colour="#000000")
        self.assertIn("not an identifier", str(refused.exception))
        with self.assertRaises(ValueError) as looped:
            EdgeKind("loop", BY_CLASS, hard=True, counterpart="loop", colour="#000000")
        self.assertIn("names itself", str(looped.exception))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            SHIPPED and setattr(next(iter(SHIPPED)), "colour", "#ffffff")   # frozen refuses the rewrite

    def test_before_reverses_the_edge_the_declaring_step_writes(self):
        # The proof a domain can say something the kernel never taught it. A step that cannot edit the
        # declaration of the step it must precede finally has a slot, with the DIRECTION riding the record.
        speaking = SHIPPED.grown(
            EdgeKind("before", BY_CLASS, hard=False, counterpart=None, colour="#1098ad", precedes=True))

        class Deploy(cabaxiom.core.Step):
            pass

        class Warmup(cabaxiom.core.Step):
            before = (Deploy,)   # Warmup cannot edit Deploy and no longer has to

        deploy, warmup = Deploy(), Warmup()
        graph = cabaxiom.core.Graph((deploy, warmup), speaking)
        self.assertEqual(graph.dependencies(deploy), (warmup,))   # the edge landed on the OTHER side
        self.assertEqual(graph.dependencies(warmup), ())
        explanation = cabaxiom.core.Reconciler((deploy, warmup), vocabulary=speaking).explain()
        self.assertEqual(explanation.groups, (("Warmup",), ("Deploy",)))   # and the run obeys it
        self.assertEqual(explanation.declared["before"], (("Warmup", ("Deploy",)),))
        drawn = explanation.mermaid()
        self.assertIn("|before|", drawn)   # styled off the run's own vocabulary, no import-time table

    def test_a_closing_scope_speaks_the_runs_language(self):
        # Only derives its own pre-narrow Graph, so a custom-vocabulary run hands the same vocabulary
        # there - and the closure then follows an edge the shipped language does not know.
        speaking = SHIPPED.grown(
            EdgeKind("leans_on", BY_CLASS, hard=False, counterpart=None, colour="#5c940d"))

        class Base(cabaxiom.core.Step):
            pass

        class Tower(cabaxiom.core.Step):
            leans_on = (Base,)

        base, tower = Base(), Tower()
        # The scope is HANDED the run's language through the Graph it selects over, never holding one of
        # its own. The same Only narrows differently depending on the Graph's vocabulary, while the reconciler
        # builds that Graph with the run's language - so the two cannot be handed different languages.
        self.assertEqual(cabaxiom.core.Only(Tower).select(cabaxiom.core.Graph((base, tower), speaking)).steps, (base, tower))
        self.assertEqual(cabaxiom.core.Only(Tower).select(cabaxiom.core.Graph((base, tower))).steps, (tower,))   # shipped language cannot
        self.assertEqual(cabaxiom.core.Reconciler((base, tower), scope=cabaxiom.core.Only(Tower),
                                             vocabulary=speaking).explain().groups,
                         (("Base",), ("Tower",)))   # and the run wires it with no keyword to forget

    async def test_the_composers_thread_the_language_through(self):
        # One kwarg, the same everywhere. A Transition speaks ONE vocabulary on both its sides.
        speaking = SHIPPED.grown(
            EdgeKind("leans_on", BY_CLASS, hard=False, counterpart=None, colour="#5c940d"))

        class Quiet(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        cutover = await cabaxiom.core.Transition([], [Quiet()], vocabulary=speaking).converge()
        self.assertTrue(cutover.clean)
        rift = cabaxiom.core.Succession([], [Quiet()], vocabulary=speaking).compare()
        self.assertEqual(rift.quieted, ())


class BlameSpeaksTheRunsLanguageTests(unittest.IsolatedAsyncioTestCase):
    """The Ledger blames through the RUN's derivation, handed in - it used to derive a Graph of its own,
    lazily, over the steps in the groups it walked. A second derivation of the same world is two things
    that must agree, yet the moment the vocabulary became injectable they stopped. A run speaking a grown
    language blocked by the SHIPPED one, so `foresee()` named a dependent the run then let run against
    state nobody put there - while the blame walk's own comment promised the two were 'the same set by
    construction, not by agreement'."""

    def _leaning(self):
        speaking = Vocabulary.shipped().grown(
            EdgeKind("leans_on", BY_CLASS, hard=False, counterpart=None, colour="#5c940d"))

        class Base(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[cabaxiom.core.DriftItem("Base", "absent")]), {}

            def apply(self, inputs):
                raise RuntimeError("Base fell over")

                return None, {}
        class Tower(cabaxiom.core.Step):
            leans_on = (Base,)

            def assess(self, inputs):
                return Assessment(deviation=[cabaxiom.core.DriftItem("Tower", "absent")]), {}

        return speaking, Base, Tower

    async def test_a_grown_edge_blocks_the_dependent_it_ordered(self):
        speaking, Base, Tower = self._leaning()
        reconciler = cabaxiom.core.Reconciler((Base(), Tower()), vocabulary=speaking,
                                         mode=cabaxiom.core.Parallel(cabaxiom.core.OnError.BestEffort))
        residual = await reconciler.converge()
        blamed = {item.name: item.message for item in residual.failures}
        self.assertIn("step failed", blamed["Base"])
        self.assertIn("step blocked: prerequisite Base failed", blamed["Tower"])

    async def test_the_forecast_and_the_record_name_the_same_set(self):
        # The promise, asserted rather than trusted. What foresee() predicts and what the run records are
        # one walk over one derivation, in a language the shipped vocabulary does not even know.
        speaking, Base, Tower = self._leaning()
        base, tower = Base(), Tower()
        reconciler = cabaxiom.core.Reconciler((base, tower), vocabulary=speaking,
                                         mode=cabaxiom.core.Parallel(cabaxiom.core.OnError.BestEffort))
        forecast = reconciler.foresee(base)
        recorded = {item.name for item in (await reconciler.converge()).failures}
        self.assertEqual(set(forecast.blocked) | {forecast.failed}, recorded)

    def test_the_ledger_derives_nothing_of_its_own(self):
        # The structural half. No second derivation can drift from the first if there is no second one.
        self.assertNotIn("Graph(", inspect.getsource(cabaxiom.core.Ledger))
        self.assertEqual(tuple(inspect.signature(cabaxiom.core.Ledger).parameters),
                         ("groups", "on_error", "observer", "graph"))


class OneFactSpokenOnceTests(unittest.IsolatedAsyncioTestCase):
    """Four divergences an adversarial sweep found and reproduced. One fact represented twice, with
    nothing keeping the two in agreement. Each is asserted here by the outcome it used to get wrong."""

    async def test_one_label_scheme_means_one_step_everywhere(self):
        # The reconciler tallied in RUN order and an isolation in SUPPLIED order, both claiming "the same
        # rule explain() applies" - so `Web#2` on an indictment and `Web#2` on a drawing were different
        # steps, so painting an indictment's accused onto a map reddened the innocent one. Shipped
        # vocabulary, two instances of one kind. The whole setup it took.
        class Web(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        class Always(cabaxiom.laboratory.Charge):
            def shows(self, proof: cabaxiom.laboratory.Proof) -> bool:
                return True

        second, first = Web(), Web()
        second.needs = (first,)
        steps = (second, first)   # supplied order deliberately DISAGREES with run order
        run = cabaxiom.core.Reconciler(steps)
        named = dict(zip((label for group in run.explain().groups for label in group),
                         (step for group in run._partition for step in group)))
        indicted = await cabaxiom.laboratory.Isolation(steps, charge=Always()).isolate()
        for label in (*indicted.accused, *indicted.dismissed):
            with self.subTest(label=label):
                self.assertIn(label, named, "an indictment must name a step by the run's own label")

    def test_a_closing_scope_cannot_be_handed_a_different_language(self):
        # Only held its own vocabulary, with the pairing left to the caller in prose - one forgotten
        # keyword silently narrowed away a prerequisite the run's own language declared.
        speaking = Vocabulary.shipped().grown(
            EdgeKind("rides", BY_CLASS, hard=False, counterpart=None, colour="#000000"))

        class Db(cabaxiom.core.Step):
            pass

        class Api(cabaxiom.core.Step):
            rides = (Db,)

        groups = cabaxiom.core.Reconciler((Api(), Db()), scope=cabaxiom.core.Only(Api),
                                     vocabulary=speaking).explain().groups
        self.assertEqual(groups, (("Db",), ("Api",)))   # the closure followed the run's own edge
        self.assertEqual(tuple(inspect.signature(cabaxiom.core.Scope.select).parameters),
                         ("self", "graph"))   # the Graph carries the language, so there is no second arg to forget

    def test_every_itinerary_hop_speaks_the_itinerarys_language(self):
        # Itinerary stored the vocabulary, carried it faithfully into reversed() and never gave it to the
        # Transitions it built - so every hop of every custom-language path resolved in the shipped one.
        speaking = Vocabulary.shipped().grown(
            EdgeKind("rides", BY_CLASS, hard=False, counterpart=None, colour="#000000"))

        class Db(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        class Api(cabaxiom.core.Step):
            rides = (Db,)

            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        walked = cabaxiom.core.Itinerary([(), (Api(), Db())], vocabulary=speaking)
        hop = walked._Itinerary__hops[0]   # noqa: SLF001 - the language a hop resolves in is the point
        self.assertEqual(hop._converge.explain().groups, (("Db",), ("Api",)))

    async def test_enclosure_reads_the_direction_off_the_kind(self):
        # It spelled the direction a second time ("the resolver must converge first"), which a `precedes`
        # kind inverts - so the one citizen whose job is catching a voided ordering certified a broken
        # tree airtight and levelled its sharpest accusation at a sound one.
        speaking = Vocabulary.shipped().grown(
            EdgeKind("before", BY_CLASS, hard=False, counterpart=None, colour="#1098ad", precedes=True))

        class Network(cabaxiom.core.Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        class Warmup(cabaxiom.core.Step):
            before = (Network,)

            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        class Sub(cabaxiom.core.Enclave):
            before = (Network,)   # declared on the class - a grown kind is no per-instance slot the freeze allows

        sound = Sub(cabaxiom.core.Reconciler((Warmup(),), vocabulary=speaking))
        top = cabaxiom.core.Reconciler((sound, Network()), vocabulary=speaking)
        self.assertEqual(top.explain().groups, (("Sub",), ("Network",)))   # the enclave genuinely first
        self.assertTrue(cabaxiom.core.Enclosure(top).prove().airtight)


class FinalMarkingTests(unittest.TestCase):
    """`@final` asserted against what the suite actually does, not against where the type gate happens to look.

    The gate reads `files = ["src"]` and nothing else, so a class can be marked sealed while the suite two
    directories away subclasses it, yet no tool ever puts the two facts side by side. That is not a
    hypothetical. `Idempotence` and `Reversibility` were both `@final` while a test subclassed each of them to
    prove they were OPEN, one of those tests being named `test_the_harness_is_open_for_a_stricter_check`.
    Extending mypy over the suite would answer it, at the price of 1905 strict errors on files that were never
    annotated. This answers it for the cost of one walk over the syntax."""

    @staticmethod
    def _kernel_classes() -> dict[str, type]:
        # BOTH published surfaces, read at their WIDEST point rather than at the front door. This walk has
        # now lost its footing twice for the same reason - once when the laboratory left `cabaxiom` and
        # again when eighty names moved down into their layers - so it reads `cabaxiom.core`, which carries
        # every kernel name whether or not the door advertises it. A guard that quietly covers less is
        # worse than one that fails, which is why the sibling test below plants a violation to prove it.
        found = {}
        for module in (cabaxiom.core, cabaxiom.laboratory):
            for name in dir(module):
                held = getattr(module, name)
                if isinstance(held, type):
                    found[name] = held
        return found

    def test_no_final_class_is_subclassed_anywhere_in_the_suite(self):
        # Classes declared INSIDE a test function are the whole point, so this reads the syntax rather than
        # importing modules - a harness defined in a method body exists nowhere an import can see it.
        known = self._kernel_classes()
        here = pathlib.Path(__file__).resolve().parents[1]   # the whole suite, every level of it
        offences = []
        for path in sorted(here.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for base in node.bases:
                    named = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", None)
                    parent = known.get(named or "")
                    if parent is not None and getattr(parent, "__final__", False):
                        offences.append(f"{path.name}:{node.lineno} {node.name} subclasses @final {named}")
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_check_would_actually_catch_a_sealed_base(self):
        # A guard nobody has seen fail is a guard nobody should trust. Isolation IS sealed and deliberately so,
        # which makes it the honest fixture for proving the walk fires.
        self.assertTrue(getattr(cabaxiom.laboratory.Isolation, "__final__", False))
        known = self._kernel_classes()
        tree = ast.parse("class Sneaky(Isolation):\n    pass\n")
        caught = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
                  for b in n.bases if getattr(known.get(getattr(b, "id", ""), None), "__final__", False)]
        self.assertEqual(caught, ["Sneaky"])

    def test_the_two_harnesses_the_suite_extends_are_left_open(self):
        # The other direction. These two carry a documented, tested extension point, so a later tidy-up that
        # reseals them has to break this line first.
        self.assertFalse(getattr(cabaxiom.laboratory.Idempotence, "__final__", False))
        self.assertFalse(getattr(cabaxiom.laboratory.Reversibility, "__final__", False))


class PlacementWordingTests(unittest.TestCase):
    """A shape's WORDING vetted where the shape is declared, because nothing else would ever notice it.

    `described` and `grouping` both end up in text a person reads and neither is ever compared, so a shape
    that words them wrongly runs green and only shows up as a mangled sentence in verify()'s refusal or as a
    capitalised phrase inside a drawn subgraph. Partition is an open axis by design, so the contract cannot
    live in the docstrings of the three shipped shapes alone. The clock is the same one ABCMeta already uses
    to refuse a shape that forgot its rule."""

    @staticmethod
    def _shape(described: str, grouping: str) -> type:
        return type("Sneaky", (cabaxiom.core.Partition,),
                    {"placement": Placement(lambda dependency, dependent: True, described, grouping)})

    def test_the_three_shipped_shapes_obey_their_own_contract(self):
        for shape in (cabaxiom.core.WavesPartition, cabaxiom.core.ChainsPartition, cabaxiom.core.WalkPartition):
            with self.subTest(shape=shape.__name__):
                told = shape.placement.described
                self.assertTrue(told[0].islower())
                self.assertGreaterEqual(len(told.split()), 2)
                self.assertNotIn(told[-1], ".,;:")
                self.assertTrue(shape.placement.grouping.isalpha())
                self.assertTrue(shape.placement.grouping.islower())

    def test_a_described_that_cannot_finish_the_sentence_is_refused(self):
        # Each of these produces a broken refusal at the one moment a caller most needs a clear one.
        for described, why in (("In an earlier group", "capital"), ("earlier", "one word"),
                               ("in an earlier group.", "full stop"), ("in an earlier group,", "comma")):
            with self.subTest(why=why), self.assertRaises(ValueError) as refused:
                self._shape(described, "wave")
            self.assertIn("completes one sentence mid-flow", str(refused.exception))

    def test_a_described_carrying_prose_punctuation_is_refused(self):
        for described in ("in an earlier group: really", "in an earlier group; really"):
            with self.subTest(described=described), self.assertRaises(ValueError) as refused:
                self._shape(described, "wave")
            self.assertIn("carries no colon and no semicolon", str(refused.exception))

    def test_a_grouping_that_is_not_one_lowercase_word_is_refused(self):
        for grouping, why in (("Wave", "capital"), ("wave 0", "a phrase"), ("wave_group", "an identifier"),
                              ("", "nothing at all")):
            with self.subTest(why=why), self.assertRaises(ValueError) as refused:
                self._shape("in an earlier group", grouping)
            self.assertIn("reads as a single lowercase word", str(refused.exception))

    def test_a_well_worded_shape_is_accepted(self):
        # The guard must not merely refuse. A shape that words its rule properly still gets to exist.
        shape = self._shape("beside its dependent", "band")
        self.assertEqual(shape.placement.grouping, "band")
