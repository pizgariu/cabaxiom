"""The data-flow mount speaks once and refuses to lose data. Ledger.mounted is the ONE home both the
write side (assemble) and the read fan build a payload through, plus a key two prerequisites both produced
is refused by name instead of resolved by whichever landed later - the silent overwrite that collapsed a
ten-thousand-shard fan-in to a single value with nothing in the record to say so."""
import unittest

from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Step


class WriteCollisionTests(unittest.IsolatedAsyncioTestCase):
    def _world(self, seen: list):
        class Left(Step):
            def apply(self, inputs):
                return None, {"dataset_uri": "s3://left.parquet"}

        class Right(Step):
            def apply(self, inputs):
                return None, {"dataset_uri": "s3://right.parquet"}

        class Train(Step):
            expects = (Left, Right)

            def apply(self, inputs):
                seen.append(dict(inputs))

                return None, {}
        return Left, Right, Train

    async def test_a_collision_is_refused_naming_both_producers_and_the_key(self):
        # The regression at the exact shape the audit measured, two shards instead of ten thousand. Two
        # prerequisites of one step write one key. Before the guard the later one won in silence and the
        # consumer trained on data the record could not attribute. Now the payload is never mounted.
        seen: list = []
        Left, Right, Train = self._world(seen)
        with self.assertRaises(ValueError) as refused:
            await Reconciler((Left(), Right(), Train())).converge()
        spoken = str(refused.exception)
        self.assertIn("Train reads `dataset_uri` from two of its prerequisites", spoken)
        self.assertIn("Left", spoken)
        self.assertIn("Right", spoken)
        self.assertIn("Namespace the keys", spoken)
        self.assertEqual(seen, [])   # the consumer never ran against a payload that lies

    async def test_the_refusal_is_structural_so_best_effort_does_not_soften_it(self):
        # A collision is a contract defect, not a step failure. The same declaration collides on every
        # run, so it aborts under any policy exactly as the membership guard does - never recorded as
        # one step's bad day for the rest of the run to build on.
        seen: list = []
        Left, Right, Train = self._world(seen)
        with self.assertRaises(ValueError):
            await Reconciler((Left(), Right(), Train()), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(seen, [])

    async def test_namespaced_keys_are_the_migration_and_both_values_arrive(self):
        # The one-sentence migration, proven. A run that wants both values says who produced what in the
        # key itself, so the consumer reads them side by side.
        seen: list = []

        class Left(Step):
            def apply(self, inputs):
                return None, {"left/dataset_uri": "s3://left.parquet"}

        class Right(Step):
            def apply(self, inputs):
                return None, {"right/dataset_uri": "s3://right.parquet"}

        class Train(Step):
            expects = (Left, Right)

            def apply(self, inputs):
                seen.append(dict(inputs))

                return None, {}
        await Reconciler((Left(), Right(), Train())).converge()
        self.assertEqual(seen, [{"left/dataset_uri": "s3://left.parquet",
                                 "right/dataset_uri": "s3://right.parquet"}])


class CollisionScopeTests(unittest.IsolatedAsyncioTestCase):
    """The refusal is PER CONSUMER, because a collision is a fact about one payload, not about the run."""

    async def test_one_key_produced_twice_is_legal_while_no_single_step_reads_both(self):
        # Two producers of `uri`, each with its OWN consumer. Neither payload holds two claims to one
        # key, so nothing is refused - the run-wide key space was never the contract.
        seen: list = []

        class Left(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://left"}

        class Right(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://right"}

        class ReadsLeft(Step):
            expects = (Left,)

            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        class ReadsRight(Step):
            expects = (Right,)

            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        await Reconciler((Left(), Right(), ReadsLeft(), ReadsRight())).converge()
        self.assertEqual(sorted(seen), ["s3://left", "s3://right"])

    async def test_a_prerequisite_reached_by_two_edges_contributes_its_keys_once(self):
        # One producer reached through BOTH a kind edge and a capability edge is one prerequisite, not
        # two. The derivation deduplicates the edges, so a step cannot collide with itself.
        seen: list = []

        class Provider(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                return None, {"uri": "s3://one"}

        class Reader(Step):
            expects = (Provider,)
            wants = ("database",)

            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        await Reconciler((Provider(), Reader())).converge()
        self.assertEqual(seen, ["s3://one"])

    async def test_a_fan_in_of_unique_keys_converges_and_a_shared_one_is_refused(self):
        # The map-reduce shape both ways. A hundred shards with per-shard keys aggregate cleanly, where the
        # same hundred sharing one key are refused naming two of them - not silently collapsed to one.
        gathered: list = []

        class Shard(Step):
            def __init__(self, index: int, key: str) -> None:
                self.__index = index
                self.__key = key

            def apply(self, inputs):
                return None, {self.__key: self.__index}

        class Aggregate(Step):
            def apply(self, inputs):
                gathered.append(len(inputs))

                return None, {}
        shards = tuple(Shard(index, f"rows/{index}") for index in range(100))
        aggregate = Aggregate()
        aggregate.uses = shards
        await Reconciler((*shards, aggregate)).converge()
        self.assertEqual(gathered, [100])   # every shard's artifact arrived, none overwritten

        colliding = tuple(Shard(index, "rows") for index in range(100))
        rival = Aggregate()
        rival.uses = colliding
        with self.assertRaises(ValueError) as refused:
            await Reconciler((*colliding, rival)).converge()
        self.assertIn("Aggregate reads `rows`", str(refused.exception))
        self.assertIn("two Shard instances", str(refused.exception))   # one class twice reads as what it is


class ProbeCollisionTests(unittest.IsolatedAsyncioTestCase):
    """One fact, one home. The read fan mounts through the same Ledger.mounted the write side uses, so
    the probe cannot bless a payload the write side would refuse."""

    async def test_an_assess_collision_is_refused_on_the_probe_side_too(self):
        # The read fan hands a step the artifacts its prerequisites' assess() produced, through the same
        # mount - so a collision among ASSESSMENTS is refused exactly as one among writes, so the probe
        # cannot bless a payload the write side would refuse.
        class Left(Step):
            def assess(self, inputs):
                return Assessment(), {"uri": "s3://left"}

        class Right(Step):
            def assess(self, inputs):
                return Assessment(), {"uri": "s3://right"}

        class Train(Step):
            expects = (Left, Right)

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("train", "never reached")]), {}

        with self.assertRaises(ValueError) as refused:
            await Reconciler((Left(), Right(), Train())).assess()
        self.assertIn("Train reads `uri` from two of its prerequisites", str(refused.exception))


class SelfNamedCollisionTests(unittest.IsolatedAsyncioTestCase):
    """The collision sentence names steps, where a step that names ITSELF is named by that.

    Two instances of one generic class - the shape a data-assembled graph takes - collided into "two
    HttpState instances", which told a reader the count and nothing they could act on. The sentence now
    compares the NAMES rather than the classes, so a same-class pair with distinct ids reads as the pair it
    is, while a genuinely anonymous pair still reads as what it was."""

    async def test_two_same_class_steps_with_their_own_ids_are_named_apart(self):
        class Source(Step):
            def __init__(self, called: str) -> None:
                self._called = called

            @property
            def identifier(self) -> str:
                return self._called

            def assess(self, inputs):
                return Assessment(), {}

            def apply(self, inputs):
                return None, {"uri": "s3://bucket/x"}

        class Sink(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("sink", "never reached")]), {}

            def apply(self, inputs):
                return None, {}

        left, right = Source("nightly"), Source("hourly")
        sink = Sink()
        sink.uses = (left, right)
        with self.assertRaises(ValueError) as refused:
            await Reconciler((left, right, sink)).converge()
        self.assertIn("nightly and hourly both produced it", str(refused.exception))
        self.assertIn("say `nightly/uri`", str(refused.exception))   # the advice names a real prefix


if __name__ == "__main__":
    unittest.main()

