"""The one read hook and the teardown - assess()'s four channels, prune() and the freeze's clock."""
import unittest
from dataclasses import dataclass

from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Step


class FrozenStepTests(unittest.IsolatedAsyncioTestCase):
    """The freeze seals at the METACLASS, after the outermost construction - never inside it. That clock
    is what these pin, because both of its failure modes shipped once. An __init__ wrapper sealed a
    derived step at its super().__init__() call, where the same wrapper occupied cls.__dict__ so @dataclass
    skipped generating the constructor its fields needed."""

    def test_a_dataclass_step_with_a_constructor_field_builds_and_freezes(self):
        # The dataclass form takes its argument. Nothing occupies __init__ at class-definition time, so
        # the decorator generates the constructor its field declares - and the seal still lands after it.
        @dataclass(eq=False)
        class Valued(Step):
            amount: int

        valued = Valued(7)
        self.assertEqual(valued.amount, 7)
        with self.assertRaises(TypeError):
            valued.amount = 8                       # sealed: a field is not a declaration slot
        valued.tags = frozenset({"prod"})           # a declaration slot stays settable, as documented

    def test_a_derived_init_that_sets_fields_after_super_is_not_sealed_early(self):
        # The re-entrancy case the old wrapper needed a flag for. The seal waits for the OUTERMOST
        # constructor, so a derived __init__ assigns freely after its super() call.
        class Base(Step):
            def __init__(self, path: str) -> None:
                self.path = path

        class Derived(Base):
            def __init__(self, path: str, content: str) -> None:
                super().__init__(path)
                self.content = content              # after super().__init__ - must not be sealed yet

        built = Derived("/tmp/x", "hello")
        self.assertEqual((built.path, built.content), ("/tmp/x", "hello"))
        with self.assertRaises(TypeError):
            built.content = "rewritten"

    def test_a_step_built_inside_another_steps_init_seals_itself_alone(self):
        # Each construction is its own metaclass call. The inner step seals at ITS end, while the outer
        # constructor keeps assigning past it - the seal never leaks across instances mid-build.
        class Inner(Step):
            def __init__(self) -> None:
                self.token = "inner"

        class Outer(Step):
            def __init__(self) -> None:
                self.inner = Inner()                # a fully built, already-sealed step
                self.token = "outer"                # and this assignment still lands

        outer = Outer()
        self.assertEqual((outer.inner.token, outer.token), ("inner", "outer"))
        for sealed in (outer, outer.inner):
            with self.assertRaises(TypeError):
                sealed.token = "rewritten"


class AssessmentChannelTests(unittest.IsolatedAsyncioTestCase):
    """The four read hooks are one assess() now. It returns an Assessment whose deviation, plan, advisory
    and footprint channels answer the four questions from a single probe. converge re-probes only the
    deviation, so advice and teardown previews never dirty the proof."""

    def test_one_probe_fills_the_four_channels(self):
        class Rich(Step):
            def assess(self, inputs):
                return Assessment(
                    deviation=[DriftItem("cfg", "content differs")],
                    plan=[DriftItem("cfg", "would rewrite 3 lines")],
                    advisory=[DriftItem("hint", "a better mode is available")],
                    footprint=[DriftItem("cfg", "the managed file")],
                ), {}

        assessment, _ = Rich().assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["content differs"])
        self.assertEqual([item.message for item in assessment.plan], ["would rewrite 3 lines"])
        self.assertEqual([item.message for item in assessment.advisory], ["a better mode is available"])
        self.assertEqual([item.message for item in assessment.footprint], ["the managed file"])

    def test_the_non_deviation_channels_default_empty(self):
        # A step reporting only drift leaves plan, advice and footprint at the Assessment's empty defaults,
        # so a probe never invents a preview a step did not declare.
        class OnlyDrift(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("f", "needs fix")]), {}

        assessment, _ = OnlyDrift().assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["needs fix"])
        self.assertEqual(
            (tuple(assessment.plan), tuple(assessment.advisory), tuple(assessment.footprint)),
            ((), (), ()),
        )

    async def test_the_reconciler_surfaces_the_deviation_channel(self):
        # Reconciler.assess flattens the deviation of every step in resolved order - the channel converge
        # re-probes - and leaves the advisory and footprint previews to the steps that carry them.
        class PA(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("A", "a")]), {}

        class PB(Step):
            expects = (PA,)

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("B", "b")]), {}

        drift = await Reconciler((PB(), PA())).assess()   # shuffled, PA must come first
        self.assertEqual([item.name for item in drift], ["A", "B"])

    async def test_converge_re_probes_only_the_deviation(self):
        # An advising step already in desired state - empty deviation, advice on the advisory channel and a
        # teardown preview on the footprint channel. converge proves clean and neither channel enters it.
        class Advising(Step):
            def assess(self, inputs):
                return Assessment(
                    deviation=[],
                    advisory=[DriftItem("hint", "a better mode is available")],
                    footprint=[DriftItem("thing", "owned")],
                ), {}

        residual = await Reconciler((Advising(),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(residual.applied, ())


class PruneTests(unittest.IsolatedAsyncioTestCase):
    """prune() is the deletion half: Reconciler.prune() runs step.prune() in REVERSE resolved order."""

    async def test_prune_runs_in_reverse_of_build_order(self):
        log = []

        class PA(Step):
            def prune(self, inputs):
                log.append("A")

                return None, {}
        class PB(Step):
            expects = (PA,)

            def prune(self, inputs):
                log.append("B")

                return None, {}
        class PC(Step):
            expects = (PB,)

            def prune(self, inputs):
                log.append("C")

                return None, {}
        await Reconciler((PC(), PA(), PB())).prune()
        self.assertEqual(log, ["C", "B", "A"])       # teardown is the inverse of build order

    async def test_build_forward_then_tear_down_backward(self):
        applied, pruned = [], []

        class A2(Step):
            def apply(self, inputs):
                applied.append("A2")

                return None, {}
            def prune(self, inputs):
                pruned.append("A2")

                return None, {}
        class B2(Step):
            expects = (A2,)

            def apply(self, inputs):
                applied.append("B2")

                return None, {}
            def prune(self, inputs):
                pruned.append("B2")

                return None, {}
        rec = Reconciler((B2(), A2()))
        await rec.converge()
        await rec.prune()
        self.assertEqual(applied, ["A2", "B2"])
        self.assertEqual(pruned, ["B2", "A2"])

    async def test_prune_goes_through_the_executor_best_effort(self):
        log = []

        class BoomPrune(Step):
            def prune(self, inputs):
                raise RuntimeError("rm failed")

        class OkPrune(Step):
            def prune(self, inputs):
                log.append("ok")

                return None, {}
        failures = await Reconciler((BoomPrune(), OkPrune()), mode=Parallel(OnError.BestEffort)).prune()
        self.assertEqual(log, ["ok"])
        self.assertEqual(len(failures), 1)

    async def test_prune_default_is_a_no_op(self):
        class CreateOnly(Step):
            def apply(self, inputs):
                pass

                return None, {}
        self.assertEqual(await Reconciler((CreateOnly(),)).prune(), [])

    async def test_prune_returns_the_residue_a_step_reports(self):
        # Self-verification. prune() returns whatever a step says SURVIVED its teardown.
        class Stubborn(Step):
            def prune(self, inputs):
                return [DriftItem("artifact", "survived teardown")], {}

        residual = await Reconciler((Stubborn(),)).prune()
        self.assertEqual([(d.name, d.message) for d in residual], [("artifact", "survived teardown")])

    async def test_prune_is_clean_when_every_step_reports_no_residue(self):
        # A step that removed everything returns [] - the empty residual is the proof of a clean teardown.
        class CleanRemove(Step):
            def prune(self, inputs):
                return [], {}

        self.assertEqual(await Reconciler((CleanRemove(),)).prune(), [])

    async def test_prune_surfaces_both_residue_and_best_effort_failures(self):
        # Residue (a soft "survived" return) and a hard prune() exception both land in the residual.
        class Survivor(Step):
            def prune(self, inputs):
                return [DriftItem("a", "survived teardown")], {}

        class BoomPrune(Step):
            def prune(self, inputs):
                raise RuntimeError("rm failed")

        residual = await Reconciler((Survivor(), BoomPrune()), mode=Parallel(OnError.BestEffort)).prune()
        names = {d.name for d in residual}
        self.assertIn("a", names)            # the soft residue
        self.assertIn("BoomPrune", names)


class DefaultWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_default_watch_never_wakes(self):
        # The base watch() is the empty event source. A step that overrides nothing is a step whose world
        # never announces itself, so a watch() loop over it converges once and then sleeps forever.
        wakes = [wake async for wake in Step().watch()]
        self.assertEqual(wakes, [])


class SelfNamingTests(unittest.IsolatedAsyncioTestCase):
    """`identifier` - the seam that lets a step a human did not write be named by whoever did write it.

    A class name identifies a step perfectly while every step is a distinct class, then stops identifying
    anything the moment a run holds five instances of one generic class - a graph assembled from data, a step
    minted per row. These pin that the seam is honest in both directions. A step that declares nothing is
    named exactly as before, while a step that declares an id is called by it in every sentence a run writes."""

    def test_a_step_that_declares_nothing_is_named_by_its_kind(self):
        class Quiet(Step):
            pass

        quiet = Quiet()
        self.assertIsNone(quiet.identifier)
        self.assertEqual(Step.named(quiet), "Quiet")

    def test_a_self_naming_step_is_labelled_by_its_own_id(self):
        class Named(Step):
            def __init__(self, called: str) -> None:
                self._called = called

            @property
            def identifier(self) -> str:
                return self._called

        first, second = Named("draft"), Named("send")
        self.assertEqual(list(Step.labelled([first, second]).values()), ["draft", "send"])

    def test_two_steps_claiming_one_id_still_get_distinct_labels(self):
        # The labeller's invariant is DISTINCT names, where a self-declared id cannot be trusted to be unique
        # the way a class name is - so the ordinal still applies. A recipe refuses a duplicate id upstream,
        # but the kernel does not get to assume its caller did.
        class Named(Step):
            @property
            def identifier(self) -> str:
                return "same"

        labels = Step.labelled([Named(), Named()])
        self.assertEqual(sorted(labels.values()), ["same", "same#2"])

    async def test_the_ledgers_sentences_call_a_step_by_its_own_id(self):
        # The whole point, observable. Two instances of ONE class, with the blocked sentence telling them apart.
        # Before the seam both read `Broken` and `Standing`, so a report on a five-instance graph named the
        # same step in every line and the reader could not act on any of them.
        class Sided(Step):
            def __init__(self, called: str, *, breaks: bool) -> None:
                self._called = called
                self._breaks = breaks

            @property
            def identifier(self) -> str:
                return self._called

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem(self._called, "unsettled")]), {}

            def apply(self, inputs):
                if self._breaks:
                    raise RuntimeError("no")
                return None, {}

        broken = Sided("draft", breaks=True)
        standing = Sided("send", breaks=False)
        standing.uses = (broken,)
        residual = await Reconciler((broken, standing), mode=Parallel(OnError.BestEffort)).converge()
        spoken = " ".join(item.message for item in residual.failures)
        self.assertIn("step failed: RuntimeError: no", spoken)
        self.assertIn("step blocked: prerequisite draft failed", spoken)
        self.assertEqual(sorted(item.name for item in residual.failures), ["draft", "send"])


class CorrespondenceTests(unittest.IsolatedAsyncioTestCase):
    """`Step.paired`. Which step of the successor continues which step of the predecessor, the one home two
    citizens read so a pre-flight cannot disagree with the transition it precedes.

    An identifier is what makes the answer possible for a declaration assembled from data, where the successor is a
    fresh object on every build and instance identity has nothing left to compare. Object identity stays the
    fallback, so nothing written before identifiers existed pairs differently."""

    def test_the_same_object_pairs_with_itself(self):
        class Held(Step):
            pass

        step = Held()
        self.assertEqual(Step.paired((step,), (step,)), {step: step})

    def test_a_rebuilt_step_pairs_by_the_name_it_calls_itself(self):
        was, now = _Row("rows/7"), _Row("rows/7")
        self.assertIsNot(was, now)
        self.assertEqual(Step.paired((was,), (now,)), {now: was})

    def test_a_different_name_is_a_leaver_and_a_joiner(self):
        was, now = _Row("rows/7"), _Row("rows/8")
        self.assertEqual(Step.paired((was,), (now,)), {})

    def test_an_unnamed_rebuild_pairs_with_nothing_because_nothing_can_tell(self):
        class Anonymous(Step):
            pass

        self.assertEqual(Step.paired((Anonymous(),), (Anonymous(),)), {})

    def test_a_joiner_is_absent_from_the_map_and_a_leaver_from_its_values(self):
        stays, leaves, joins = _Row("a"), _Row("b"), _Row("c")
        paired = Step.paired((stays, leaves), (_Row("a"), joins))
        self.assertEqual([Step.named(step) for step in paired], ["a"])
        self.assertEqual(list(paired.values()), [stays])

    def test_two_steps_of_one_declaration_may_not_share_a_name(self):
        # An identifier names a step across runs, so an ambiguous pairing would silently take whichever came
        # second. Refused on either side, since either side can be the one that was built from data.
        for side, previous, desired in (("previous", (_Row("dup"), _Row("dup")), ()),
                                        ("desired", (), (_Row("dup"), _Row("dup")))):
            with self.subTest(side=side):
                with self.assertRaises(ValueError) as raised:
                    Step.paired(previous, desired)
                self.assertIn(f"in the {side} declaration both call themselves 'dup'", str(raised.exception))


class _Row(Step):
    """A step nobody hand-wrote, minted per row, which is the whole reason `identifier` exists."""

    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def identifier(self) -> str:
        return self.name


class SelfNamingReachesEverySentenceTests(unittest.IsolatedAsyncioTestCase):
    """The seam asserted where it is CONSUMED, not where it is defined.

    `Step.named` shipped with a docstring calling itself the one home for naming a step in a sentence, while
    twenty-three sites still spelled `step.__class__.__name__` themselves. A claim like that has to be
    checkable, so these drive the sentences a caller actually meets and look for the caller's own id. The
    worst of them was the cycle path, which printed `HttpState -> HttpState -> HttpState` for a graph
    assembled from data - the exact reader the seam exists for."""

    @staticmethod
    def _named(called: str, **slots):
        class Named(Step):
            def __init__(self) -> None:
                for slot, value in slots.items():
                    setattr(self, slot, value)

            @property
            def identifier(self) -> str:
                return called

            def assess(self, inputs):
                return Assessment(), {}

            def apply(self, inputs):
                return None, {}

        return Named()

    def test_a_cycle_path_names_the_steps_the_caller_named(self):
        first = self._named("draft")
        second = self._named("send", uses=(first,))
        first.uses = (second,)
        with self.assertRaises(ValueError) as refused:
            Reconciler((first, second))
        self.assertIn("draft", str(refused.exception))
        self.assertIn("send", str(refused.exception))
        self.assertNotIn("Named ->", str(refused.exception))

    def test_a_step_handed_twice_is_named_by_its_id(self):
        once = self._named("draft")
        with self.assertRaises(ValueError) as refused:
            Reconciler((once, once))
        self.assertIn("draft was handed to this run twice", str(refused.exception))

    def test_foreseeing_a_stranger_names_the_stranger(self):
        run = Reconciler((self._named("draft"),))
        with self.assertRaises(ValueError) as refused:
            run.foresee(self._named("outsider"))
        self.assertIn("outsider is not in this run", str(refused.exception))

    def test_a_declaration_refusal_names_the_step_not_the_class(self):
        # `uses` handed a bare instance instead of a tuple. The message has to say WHICH step got it wrong.
        broken = self._named("draft", uses=self._named("other"))
        with self.assertRaises(TypeError) as refused:
            Reconciler((broken,))
        self.assertIn("draft.uses", str(refused.exception))

    async def test_a_stamp_repr_names_the_step_the_caller_named(self):
        from cabaxiom.core.record.observer import Stamp

        self.assertIn("Stamp(draft,", repr(Stamp(self._named("draft"), 0.0)))
