"""The Statement. execute()'s record and the artifacts' way OUT of the run they used to die inside.
The Ledger closes with one Statement instead of two lists, the Residual carries the final pass's
produced map as a photograph, so the record family's founding sentence holds. what was true when the
run ended stays true, even against a step that kept a handle to its own returned dict."""
import unittest

from cabaxiom import (
    DriftItem,
    Fixpoint,
    Graph,
    Ledger,
    Observer,
    OnError,
    Parallel,
    Reconciler,
    Statement,
    Step,
)
from support import A, B


class StatementRecordTests(unittest.TestCase):
    def test_the_ledger_closes_with_a_statement_carrying_all_three_channels(self):
        class Maker(Step):
            pass

        maker = Maker()
        ledger = Ledger(((maker,),), OnError.FailFast, Observer(), Graph((maker,)))
        ledger.record(maker, [DriftItem("svc", "made")], {"uri": "s3://x"}, None)
        statement = ledger.outcome()
        self.assertEqual([item.message for item in statement.returns], ["made"])
        self.assertEqual(statement.failures, ())
        self.assertEqual(statement.produced[maker], {"uri": "s3://x"})

    def test_the_record_is_deliberately_not_iterable(self):
        # The old contract died loudly on purpose. Unpacking the two lists was positional plumbing, where a
        # record whose tuple-ness is accidental API is EdgeKind's exact refusal. A caller reads properties.
        with self.assertRaises(TypeError):
            _returns, _failures = Statement((), ())   # type: ignore[misc]

    def test_produced_is_copied_at_mint_so_a_kept_handle_cannot_rewrite_it(self):
        # A step returning `self._cache` keeps a handle to the dict it handed the run. The Statement takes
        # its photograph at mint, so mutating the source afterwards changes nothing the record says - and
        # writing through the exposed view is refused outright.
        class Maker(Step):
            pass

        maker = Maker()
        cache = {"uri": "s3://before"}
        statement = Statement((), (), {maker: cache})
        cache["uri"] = "s3://after"
        cache["extra"] = "smuggled"
        self.assertEqual(statement.produced[maker], {"uri": "s3://before"})
        with self.assertRaises(TypeError):
            statement.produced[maker] = {}   # type: ignore[index]


class ProducedPhotographTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_residual_carries_the_final_pass_photograph(self):
        # The temporal rule, at the shape that killed the accumulator draft. Under Fixpoint every pass
        # re-executes the whole partition, so a settled step no-ops in pass two. Artifacts are
        # level-triggered - the no-op returns the SAME artifacts it would have produced fresh - so the
        # final pass's map is complete, so the photograph never wipes what a diary would have kept.
        world = {"count": 0, "steady": False}

        class Steady(Step):
            def apply(self, inputs):
                if world["steady"]:
                    return None, {"uri": "s3://x"}   # the level-triggered no-op: same artifacts, no work

                world["steady"] = True
                return [DriftItem("steady", "made")], {"uri": "s3://x"}

        class Growing(Step):
            def assess(self, inputs):
                from cabaxiom import Assessment
                still = [] if world["count"] >= 2 else [DriftItem("growing", "not there yet")]
                return Assessment(deviation=still), {}

            def apply(self, inputs):
                if world["count"] >= 2:
                    return None, {"count": world["count"]}

                world["count"] += 1
                return [DriftItem("growing", f"grew to {world['count']}")], {"count": world["count"]}

        steady, growing = Steady(), Growing()
        residual = await Reconciler((steady, growing), convergence=Fixpoint()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(residual.produced[steady], {"uri": "s3://x"})   # pass two's no-op, not a wipe
        self.assertEqual(residual.produced[growing], {"count": 2})      # the final pass's world, verbatim

    async def test_a_failed_step_is_honestly_absent_from_the_photograph(self):
        # The other direction the accumulator lied in. A step whose last word was failure contributes no
        # entry, agreeing with the failures channel instead of presenting stale data as truth.
        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("db down")

        class Fine(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://fine"}

        boom, fine = Boom(), Fine()
        residual = await Reconciler((boom, fine), mode=Parallel(OnError.BestEffort)).converge()
        self.assertNotIn(boom, residual.produced)
        self.assertEqual(residual.produced[fine], {"uri": "s3://fine"})

    async def test_a_prune_statement_rides_its_residual_too(self):
        # The teardown closes over the same seam. What each prune() produced is readable off the record
        # the same way, because prune is the mirror verb, not a second engine.
        class Holder(Step):
            def prune(self, inputs):
                return None, {"released": "s3://x"}

        holder = Holder()
        residue = await Reconciler((holder,)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(residue.produced[holder], {"released": "s3://x"})


if __name__ == "__main__":
    unittest.main()


class ReadingRecordTests(unittest.IsolatedAsyncioTestCase):
    """The Statement's read twin, on the OTHER precedent - a Sequence, because the deviations ARE the
    reading - so every list-shaped caller of assess() behaves unchanged while the produced channel rides
    beside them."""

    async def test_assess_returns_the_reading_and_every_list_shaped_caller_survives(self):
        # The seam assertion and the BC claim in one. The probe's store surfaces as produced, while
        # equality, truthiness, len, iteration and indexing all read as the plain list they always were.
        from cabaxiom import Assessment

        class Prober(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "still wrong")]), {"uri": "s3://x"}

        prober = Prober()
        reading = await Reconciler((prober,)).assess()
        self.assertEqual(reading, [DriftItem("svc", "still wrong")])   # list equality, the Residual rule
        self.assertTrue(reading)
        self.assertEqual(len(reading), 1)
        self.assertEqual(reading[0].message, "still wrong")
        self.assertEqual(reading[0:], (reading[0],))                   # slicing hands back a plain tuple
        self.assertEqual(reading.produced[prober], {"uri": "s3://x"})  # the store, surfaced at last

    def test_equality_is_by_items_and_a_stranger_is_not_compared(self):
        from cabaxiom import Reading

        one = Reading([DriftItem("a", "x")])
        self.assertEqual(one, Reading([DriftItem("a", "x")]))          # its own kind, by items
        self.assertNotEqual(one, [DriftItem("a", "y")])                # a list that differs
        self.assertNotEqual(one, [])                                   # and one that is shorter
        self.assertNotEqual(one, object())                             # NotImplemented falls through

    def test_gathered_folds_every_channel_and_files_every_artifact(self):
        # The fold both read fans used to hand-roll, with five positional results into a constructor where
        # plan and advisory share a type - so a swapped pair typed clean. Folded once, every channel lands in
        # its own slot and every settled step gets a produced entry, the empty one included.
        from cabaxiom import Assessment
        from cabaxiom.core.record import Reading

        one, two = A([]), B([])
        reading = Reading.gathered([
            (one, Assessment(deviation=[DriftItem("one", "off")], plan=[DriftItem("one", "would fix")]), {"k": 1}),
            (two, Assessment(advisory=[DriftItem("two", "note")], footprint=[DriftItem("two", "owns")]), {}),
        ])
        self.assertEqual(reading, [DriftItem("one", "off")])
        self.assertEqual(reading.plan, (DriftItem("one", "would fix"),))
        self.assertEqual(reading.advisory, (DriftItem("two", "note"),))
        self.assertEqual(reading.footprint, (DriftItem("two", "owns"),))
        self.assertEqual(dict(reading.produced), {one: {"k": 1}, two: {}})   # answered without it, not never asked
        self.assertEqual(Reading.gathered([]), [])

    def test_produced_is_copied_at_mint_exactly_as_the_statements(self):
        from cabaxiom import Reading

        class Maker(Step):
            pass

        maker = Maker()
        cache = {"uri": "s3://before"}
        reading = Reading((), {maker: cache})
        cache["uri"] = "s3://after"
        self.assertEqual(reading.produced[maker], {"uri": "s3://before"})
        with self.assertRaises(TypeError):
            reading.produced[maker] = {}   # type: ignore[index]
        self.assertIn("Reading(", repr(reading))
