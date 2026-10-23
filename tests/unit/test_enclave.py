"""Enclave - a whole reconciler as ONE step of a parent run - stacks nest, one converge proves the tree."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Enclave, OnError, Parallel, Reconciler, Step
from cabaxiom.core.run import Unpublished
from cabaxiom.laboratory import Idempotence
from support import Fixable, ReportOnly


class EnclaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_sub_stack_converges_as_one_step_of_the_parent(self):
        # A whole reconciler (its own steps, its own resolution) rides a parent run as a single step.
        inner = Reconciler((Fixable(), Fixable()))
        residual = await Reconciler((Enclave(inner),)).converge()
        self.assertEqual(residual, [])                       # the parent's one residual proves the tree

    async def test_apply_routes_the_inner_applied_channel_not_the_residual(self):
        # The load-bearing rule. What the sub-stack CHANGED lands on the parent's applied channel. What is
        # STILL WRONG inside must never ride it - a naive adapter returning the Residual would poison
        # applied with still-wrong items and break Proof.churned.
        class Creates(Step):
            def __init__(self) -> None:
                self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "missing")]), {}

            def apply(self, inputs):
                self.__done[0] = True
                return [DriftItem("svc", "created")], {}

        residual = await Reconciler((Enclave(Reconciler((Creates(),))),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["created"])

    async def test_the_inner_residual_surfaces_through_the_parents_reprobe(self):
        # A report-only step inside the enclave stays wrong. The parent sees it via drift() delegation
        # (the honest re-probe), not via apply()'s return.
        residual = await Reconciler((Enclave(Reconciler((ReportOnly(),))),)).converge()
        self.assertEqual([item.message for item in residual], ["still wrong"])
        self.assertEqual(residual.applied, ())

    async def test_an_enclave_is_ordered_like_any_step(self):
        # Two whole stacks ordered by `expects`. The ground stack converges before the tower stack.
        log: list = []

        class Ground(Step):
            def apply(self, inputs):
                log.append("ground")

                return None, {}
        class GroundStack(Enclave):
            pass

        class TowerStack(Enclave):
            expects = (GroundStack,)

        class Tower(Step):
            def apply(self, inputs):
                log.append("tower")

                return None, {}
        tower = TowerStack(Reconciler((Tower(),)))
        ground = GroundStack(Reconciler((Ground(),)))
        await Reconciler((tower, ground)).converge()         # handed in shuffled
        self.assertEqual(log, ["ground", "tower"])

    async def test_idempotence_proves_the_whole_tree(self):
        # The finale. One Proof certifies a NESTED world - the second converge of the parent drives a
        # second converge of every enclave, so stability composes.
        inner_one = Reconciler((Fixable(),))
        inner_two = Reconciler((Fixable(), Fixable()))
        parent = Reconciler((Enclave(inner_one), Enclave(inner_two)))
        self.assertTrue((await Idempotence(parent).prove()).stable)

    async def test_prune_tears_the_sub_stack_down_from_the_parents_teardown(self):
        pruned: list = []

        class Owns(Step):
            def prune(self, inputs):
                pruned.append("inner")
                return [], {}

        residue = await Reconciler((Enclave(Reconciler((Owns(),))),)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(pruned, ["inner"])

    async def test_assess_delegates_the_inner_deviation(self):
        # The enclave's one read hook delegates to the sub-stack. Its Assessment's deviation is the inner
        # reconciler's drift, surfaced through the parent's honest re-probe.
        class Eyes(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("e", "drifting")]), {}

        enclave = Enclave(Reconciler((Eyes(),)))
        assessment, _ = await enclave.assess({})
        self.assertEqual([d.message for d in assessment.deviation], ["drifting"])

    def test_an_enclave_is_a_step(self):
        self.assertTrue(issubclass(Enclave, Step))           # an enclave IS a step, that is the whole point


class AsyncEnclaveTests(unittest.IsolatedAsyncioTestCase):
    """The coroutine twin - a whole Reconciler as one step of an async parent, awaited end to end."""

    class _AsyncFix(Step):
        def __init__(self) -> None:
            self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        async def assess(self, inputs):
            await asyncio.sleep(0)
            return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.__done[0] = True
            return [DriftItem("svc", "fixed over io")], {}

    async def test_an_async_sub_stack_converges_inside_an_async_parent(self):
        inner = Reconciler((self._AsyncFix(),))
        residual = await Reconciler((Enclave(inner),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["fixed over io"])

    async def test_the_async_read_awaits_into_the_sub_stack(self):
        enclave = Enclave(Reconciler((self._AsyncFix(),)))
        assessment, _ = await enclave.assess({})
        self.assertEqual([d.message for d in assessment.deviation], ["needs io"])

    async def test_async_prune_tears_the_sub_stack_down(self):
        pruned: list = []

        class Owns(Step):
            async def prune(self, inputs):
                await asyncio.sleep(0)
                pruned.append("inner")
                return [], {}

        residue = await Reconciler((Enclave(Reconciler((Owns(),))),)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(pruned, ["inner"])


class PublishesTests(unittest.IsolatedAsyncioTestCase):
    """The write-side boundary crossing - an explicit export list, an empty default that keeps the sealed
    boundary sealed, plus a published key as a PROMISE - refused loudly when nothing inside keeps it."""

    def _producer(self, key: str, value: str):
        class Producer(Step):
            def assess(self, inputs):
                return Assessment(), {key: value}   # the level-triggered mirror: assess shows what apply produces

            def apply(self, inputs):
                return None, {key: value}
        return Producer

    async def test_the_default_publishes_nothing(self):
        # The shipped doctrine stays true by default. The boundary is sealed unless the enclave declares
        # otherwise, so every existing Enclave behaves byte for byte as it always did.
        seen: list = []
        Producer = self._producer("uri", "s3://x")

        class Reads(Step):
            def apply(self, inputs):
                seen.append(dict(inputs))

                return None, {}
        enclave = Enclave(Reconciler((Producer(),)))
        reader = Reads()
        reader.uses = (enclave,)
        await Reconciler((enclave, reader)).converge()
        self.assertEqual(seen, [{}])

    async def test_exported_keys_ride_the_parents_data_flow(self):
        # The whole point. A published key leaves the sub-stack as this step's own artifact and arrives in
        # a parent consumer's payload like any sibling's.
        seen: list = []
        Producer = self._producer("uri", "s3://made-inside")

        class Reads(Step):
            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        enclave = Enclave(Reconciler((Producer(),)), publishes=("uri",))
        reader = Reads()
        reader.uses = (enclave,)
        await Reconciler((enclave, reader)).converge()
        self.assertEqual(seen, ["s3://made-inside"])

    async def test_a_missing_published_key_names_the_inner_casualty(self):
        # The refusal must not bury the true cause. When an inner failure explains the silence, the
        # sentence QUOTES the inner record instead of erasing it into "nothing inside produced it".
        class Dies(Step):
            def apply(self, inputs):
                raise RuntimeError("bucket gone")

        inner = Reconciler((Dies(),), mode=Parallel(OnError.BestEffort))
        with self.assertRaises(Unpublished) as refused:
            await Enclave(inner, publishes=("uri",)).apply({})
        spoken = str(refused.exception)
        self.assertIn("Enclave publishes `uri` and nothing inside produced it this run", spoken)
        self.assertIn("The run recorded inside: ", spoken)
        self.assertIn("step failed: RuntimeError: bucket gone", spoken)

    async def test_a_missing_published_key_without_a_casualty_names_the_promise(self):
        # The static case, a typo or a step that never returns the key. No failure to quote, so the
        # sentence names the promise and why it is checked here rather than at resolution.
        Producer = self._producer("other", "s3://x")
        with self.assertRaises(Unpublished) as refused:
            await Enclave(Reconciler((Producer(),)), publishes=("uri",)).apply({})
        spoken = str(refused.exception)
        self.assertIn("Enclave publishes `uri` yet no step inside produces it", spoken)
        self.assertIn("in the spirit of `demands`", spoken)

    async def test_two_producers_of_one_published_key_are_refused_as_two_instances(self):
        # The boundary is ONE consumer of each published key, so the per-consumer collision doctrine
        # holds - and one class twice reads as what it is, never as a stutter.
        Producer = self._producer("uri", "s3://x")
        inner = Reconciler((Producer(), Producer()))
        with self.assertRaises(Unpublished) as refused:
            await Enclave(inner, publishes=("uri",)).apply({})
        self.assertIn("two Producer instances both produce it", str(refused.exception))

    async def test_two_producers_of_different_kinds_are_named_in_declaration_order(self):
        # Different classes are named apart, in the INNER declaration order - a fact about the world, not
        # about the strategy that walked it.
        First = self._producer("uri", "s3://a")
        Second = self._producer("uri", "s3://b")
        Second.__name__ = "Second"
        First.__name__ = "First"
        inner = Reconciler((First(), Second()))
        with self.assertRaises(Unpublished) as refused:
            await Enclave(inner, publishes=("uri",)).apply({})
        self.assertIn("First and Second both produce it", str(refused.exception))

    def test_a_bare_string_is_refused_with_the_comma_named(self):
        with self.assertRaises(TypeError) as refused:
            Enclave(Reconciler(()), publishes="uri")   # type: ignore[arg-type]
        self.assertIn("publishes=('uri',)", str(refused.exception))

    def test_a_non_tuple_and_a_non_string_key_are_refused(self):
        with self.assertRaises(TypeError) as listed:
            Enclave(Reconciler(()), publishes=["uri"])   # type: ignore[arg-type]
        self.assertIn("must be a tuple of artifact keys, got list", str(listed.exception))
        with self.assertRaises(TypeError) as keyed:
            Enclave(Reconciler(()), publishes=(7,))   # type: ignore[arg-type]
        self.assertIn("Enclave publishes 7, which is not an artifact key", str(keyed.exception))

    async def test_prune_exports_nothing_even_when_asked_to_publish(self):
        # The teardown walks the inverse partition. A parent dependent already ran before this enclave is
        # pruned, so there is nobody left to read a key and nothing crosses on the way down.
        class Holder(Step):
            def prune(self, inputs):
                return None, {"uri": "s3://x"}

        _residue, artifacts = await Enclave(Reconciler((Holder(),)), publishes=("uri",)).prune({})
        self.assertEqual(artifacts, {})

    async def test_nesting_re_exports_a_key_two_levels_up(self):
        # Levels compose with zero special-casing. The inner enclave's export is recorded as its own
        # artifact in the outer enclave's run, so the outer enclave finds one producer and re-exports.
        Producer = self._producer("uri", "s3://leaf")
        inner = Enclave(Reconciler((Producer(),)), publishes=("uri",))
        outer = Enclave(Reconciler((inner,)), publishes=("uri",))
        seen: list = []

        class Reads(Step):
            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        reader = Reads()
        reader.uses = (outer,)
        await Reconciler((outer, reader)).converge()
        self.assertEqual(seen, ["s3://leaf"])

    async def test_an_exported_key_collides_with_a_sibling_under_the_parents_own_guard(self):
        # The interplay that costs nothing. An exported key joins the parent's payloads like any
        # sibling's, so the parent's mount refuses the collision naming the Enclave itself.
        Producer = self._producer("uri", "s3://inner")
        Sibling = self._producer("uri", "s3://outer")

        class Reads(Step):
            def apply(self, inputs):
                return None, {}

        enclave = Enclave(Reconciler((Producer(),)), publishes=("uri",))
        sibling = Sibling()
        reader = Reads()
        reader.uses = (enclave, sibling)
        with self.assertRaises(ValueError) as refused:
            await Reconciler((enclave, sibling, reader)).converge()
        spoken = str(refused.exception)
        self.assertIn("Reads reads `uri` from two of its prerequisites", spoken)
        self.assertIn("Enclave", spoken)


class GlimpseTests(unittest.IsolatedAsyncioTestCase):
    """The read-side crossing - the photograph to the write side's promise. Soft on a dirty world, hard on
    a clean one - and the softness is safe exactly because absence and deviation travel together."""

    async def test_absence_on_a_dirty_world_is_skipped_and_the_deviation_says_why(self):
        # BOTH halves of the load-bearing coupling in one test. The key is absent from the glimpse AND the
        # deviation channel is non-empty, so the parent's proof stays dirty exactly when the absence is real.
        class NotBuilt(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("dataset", "not built yet")]), {}

            def apply(self, inputs):
                return None, {"uri": "s3://x"}

        assessment, artifacts = await Enclave(Reconciler((NotBuilt(),)), publishes=("uri",)).assess({})
        self.assertNotIn("uri", artifacts)                                  # the photograph shows a hole
        self.assertEqual([item.message for item in assessment.deviation], ["not built yet"])   # and says why

    async def test_absence_on_a_clean_reading_is_refused_naming_the_contract(self):
        # The panel's corner. A clean reading claims the world converged, so a promised key with no
        # producer is a typo or a producer whose assess forgot to mirror - never the world's fault.
        # Skipping here would mint a clean proof over a broken promise.
        class Lazy(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://x"}   # produces on write, yet its assess shows nothing

        with self.assertRaises(Unpublished) as refused:
            await Enclave(Reconciler((Lazy(),)), publishes=("uri",)).assess({})
        spoken = str(refused.exception)
        self.assertIn("a clean reading shows no producer for it", spoken)
        self.assertIn("mirror what apply produces", spoken)

    async def test_a_read_collision_is_refused_as_the_same_unpublished(self):
        # The one fate both verbs share, direct - two inner assess claims on one published key.
        class Producer(Step):
            def assess(self, inputs):
                return Assessment(), {"uri": "s3://x"}

        with self.assertRaises(Unpublished) as refused:
            await Enclave(Reconciler((Producer(), Producer())), publishes=("uri",)).assess({})
        self.assertIn("two Producer instances both produce it", str(refused.exception))

    async def test_a_read_refusal_reaches_the_parent_inside_the_probe_group(self):
        # The documented catchability difference. The probe fan gathers a wave's broken reads into one
        # ExceptionGroup, so on the read side an Unpublished arrives inside it and except* reaches it by
        # type - the read contract for every broken read, not an exception made for this one.
        class Lazy(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://x"}

        enclave = Enclave(Reconciler((Lazy(),)), publishes=("uri",))
        with self.assertRaises(ExceptionGroup) as grouped:
            await Reconciler((enclave,)).assess()
        self.assertIsNotNone(grouped.exception.subgroup(Unpublished))

    async def test_on_a_clean_world_the_glimpse_equals_the_export(self):
        # The design's own equation, end to end. After a clean converge the re-probe hands a parent
        # consumer the same published key its apply consumed - the sekcja-8 hole, closed.
        world = {"built": False}
        seen: dict = {}

        class Producer(Step):
            def assess(self, inputs):
                shows = {"uri": "s3://x"} if world["built"] else {}
                still = [] if world["built"] else [DriftItem("dataset", "not built yet")]
                return Assessment(deviation=still), shows

            def apply(self, inputs):
                world["built"] = True
                return None, {"uri": "s3://x"}

        class Reads(Step):
            def assess(self, inputs):
                seen["assess"] = dict(inputs)
                return Assessment(), {}

            def apply(self, inputs):
                seen["apply"] = dict(inputs)
                return None, {}

        enclave = Enclave(Reconciler((Producer(),)), publishes=("uri",))
        reader = Reads()
        reader.uses = (enclave,)
        residual = await Reconciler((enclave, reader)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(seen["apply"], {"uri": "s3://x"})    # the write export
        self.assertEqual(seen["assess"], {"uri": "s3://x"})   # and the SAME key in the re-probe payload


class EveryChannelCrossesTests(unittest.IsolatedAsyncioTestCase):
    """All four channels of the inner reading reach the parent, not deviation alone.

    They used to stop at the boundary, where the first real consumer of a nested run found it - a check
    suite holding a git-hooks reconciler needs the inner run's ADVICE, which is exactly what a run with
    no deviation still has to say. An enclave that drops it is lossy in the one direction nothing would
    ever notice, because the parent stays green either way."""

    class Speaks(Step):
        def assess(self, inputs):
            return Assessment(
                deviation=[DriftItem("inner", "wrong")],
                plan=[DriftItem("inner", "would fix it")],
                advisory=[DriftItem("inner", "worth knowing")],
                footprint=[DriftItem("inner", "held")],
            ), {}

    async def test_the_parent_reads_all_four_channels_of_the_inner_run(self):
        reading = await Reconciler((Enclave(Reconciler((self.Speaks(),))),)).assess()
        self.assertEqual([item.message for item in reading], ["wrong"])
        self.assertEqual([item.message for item in reading.plan], ["would fix it"])
        self.assertEqual([item.message for item in reading.advisory], ["worth knowing"])
        self.assertEqual([item.message for item in reading.footprint], ["held"])

    async def test_advice_crosses_from_a_sub_stack_with_nothing_wrong(self):
        # The case that made the gap invisible. Nothing deviates, so the parent is green whether or not
        # the advice arrives - which is why only a consumer that RENDERS advice would ever have noticed.
        class Quiet(Step):
            def assess(self, inputs):
                return Assessment(advisory=[DriftItem("inner", "an upgrade is available")]), {}

        reading = await Reconciler((Enclave(Reconciler((Quiet(),))),)).assess()
        self.assertEqual(list(reading), [])
        self.assertEqual([item.message for item in reading.advisory], ["an upgrade is available"])
