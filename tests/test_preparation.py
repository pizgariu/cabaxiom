"""Preparation edges ride every guard unchanged - the payoff of the vocabulary owning the DIRECTION.
`prepares` and `mandates` are the first shipped `precedes` pair. Declaring one puts the DECLARER before
the match, the edge written the other way around. Kahn orders them, verify() rejects their mis-splits,
the Ledger blocks through them, Only pulls a preparer into a targeted run, demand() fires for `mandates`,
and explain() lands the arrow with the preparer on the prerequisite side. Not one guard learned a kind."""
import unittest

from cabaxiom import Graph, Kahn, OnError, Only, Parallel, Reconciler, Step, WavesPartition


class PreparationRideTests(unittest.IsolatedAsyncioTestCase):
    async def test_kahn_orders_a_preparer_before_every_instance_of_the_match(self):
        # One preparer and two instances of the class it prepares, handed scrambled. The reversed fan puts
        # the preparer before BOTH, the mirror image of `expects` fanning to two instances of one kind.
        log = []

        class Ground(Step):
            def apply(self, inputs):
                log.append("ground")

                return None, {}
        class Tower(Step):
            def apply(self, inputs):
                log.append("tower")

                return None, {}
        Ground.prepares = (Tower,)
        await Reconciler((Tower(), Ground(), Tower())).converge()
        self.assertEqual(log[0], "ground")
        self.assertEqual(sorted(log[1:]), ["tower", "tower"])

    async def test_a_prepares_edge_to_an_absent_class_is_trusted(self):
        # Soft means soft in either direction. Nothing to prepare is a dead end, never an error, where the
        # preparer still runs on its own.
        log = []

        class Absent(Step):
            pass

        class Ground(Step):
            prepares = (Absent,)

            def apply(self, inputs):
                log.append("ground")

                return None, {}
        await Reconciler((Ground(),)).converge()
        self.assertEqual(log, ["ground"])

    def test_mandates_demands_the_match_is_present(self):
        # The hard twin refuses at resolution, in the pair's own words - composed from the row, so the
        # refusal arrived with the kind instead of being taught to demand().
        class Absent(Step):
            pass

        class Ground(Step):
            mandates = (Absent,)

        with self.assertRaises(ValueError) as ctx:
            Reconciler((Ground(),))
        self.assertIn("Ground mandates Absent but no Absent is in the run", str(ctx.exception))
        self.assertIn("Unlike `prepares`, which trusts an absent dependency, `mandates` demands its presence", str(ctx.exception))

    def test_verify_rejects_a_prepares_mis_split_with_no_new_guard_code(self):
        # verify() reads the Graph, which already wrote the edge the right way around - so seating
        # the prepared beside its preparer is refused exactly as any ignored edge is.
        class Ground(Step):
            pass

        class Tower(Step):
            pass

        Ground.prepares = (Tower,)
        ground, tower = Ground(), Tower()
        graph = Graph((ground, tower))
        WavesPartition(((ground,), (tower,))).verify(graph)   # preparer in an earlier wave: honoured
        with self.assertRaises(ValueError) as ctx:
            WavesPartition(((ground, tower),)).verify(graph)  # same wave: the reversed edge ignored, so refused
        self.assertIn("Tower depends on Ground", str(ctx.exception))

    async def test_best_effort_blocks_the_prepared_dependent_of_a_failed_preparer(self):
        # The Ledger walks the Graph, so the prepared step is blocked like any dependent. unprepared
        # ground is never built on and the residual names the culprit.
        ran = []

        class Ground(Step):
            def apply(self, inputs):
                raise RuntimeError("no ground today")

        class Tower(Step):
            def apply(self, inputs):
                ran.append("tower")

                return None, {}
        Ground.prepares = (Tower,)
        residual = await Reconciler((Ground(), Tower()), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])
        messages = [item.message for item in residual]
        self.assertEqual(sum("step blocked: prerequisite Ground failed" in message for message in messages), 1)

    def test_only_pulls_the_preparer_into_a_targeted_run(self):
        # A targeted run must stay a correct run in both directions. The target's prerequisite is its
        # PREPARER here, where the closure follows the edge as derived, not as declared.
        class Ground(Step):
            pass

        class Tower(Step):
            pass

        Ground.prepares = (Tower,)
        groups = Reconciler((Ground(), Tower()), scope=Only(Tower)).explain().groups
        self.assertEqual(groups, (("Ground",), ("Tower",)))

    def test_explain_lands_the_arrow_with_the_preparer_on_the_prerequisite_side(self):
        # The (dependent, prerequisite, slot) contract holds for a `precedes` kind because explain()
        # orients at the source - the drawing and the dependency projection stay deaf to direction.
        class Ground(Step):
            pass

        class Tower(Step):
            pass

        Ground.prepares = (Tower,)
        explanation = Reconciler((Ground(), Tower())).explain()
        self.assertEqual(explanation.arrows, (("Tower", "Ground", "prepares"),))
        self.assertEqual(explanation.dependencies, (("Tower", ("Ground",)),))
        self.assertEqual(dict(explanation.declared["prepares"]), {"Ground": ("Tower",)})
        self.assertIn("n0 -->|prepares| n1", explanation.mermaid())   # n0 is Ground, wave 0

    def test_foresee_counts_the_prepared_among_a_preparers_casualties(self):
        # The counterfactual read runs on the same derived edges, so a preparer's fall names the step it
        # would have prepared - no consumer re-learned the direction.
        class Ground(Step):
            pass

        class Tower(Step):
            pass

        Ground.prepares = (Tower,)
        ground = Ground()
        casualty = Reconciler((ground, Tower())).foresee(ground)
        self.assertIn("Tower", casualty.blocked)

    def test_opposite_directions_on_one_pair_close_a_cycle(self):
        # `expects` says the match goes first, `prepares` says the declarer does - both at once is a cycle,
        # and the ordering refuses it like any other instead of quietly picking a winner.
        class Ground(Step):
            pass

        class Tower(Step):
            pass

        Ground.prepares = (Tower,)
        Ground.expects = (Tower,)
        with self.assertRaises(ValueError):
            Kahn()(Graph((Ground(), Tower())))


class InstancePairTests(unittest.IsolatedAsyncioTestCase):
    """`uses` and `needs` are the instance pair now - one soft, one hard, over one addressing - the split
    that lets a subset run trust a missing instance while a full run refuses to lose one silently."""

    def test_needs_demands_the_instance_is_present(self):
        # The instance twin of `requires`, spoken in the addressing's own nouns - and the instance is
        # named by its class, not by an object repr no operator can read.
        class Node(Step):
            pass

        absent = Node()
        present = Node()
        present.needs = (absent,)
        with self.assertRaises(ValueError) as ctx:
            Reconciler((present,))
        self.assertIn("Node needs Node but that instance is not in the run", str(ctx.exception))
        self.assertIn("Unlike `uses`, which trusts an absent instance, `needs` demands its presence", str(ctx.exception))

    async def test_uses_orders_after_the_named_instance(self):
        # The soft twin still orders when the instance IS present - softness is a presence rule, never a
        # weaker edge.
        log = []

        class Node(Step):
            def __init__(self, tag: str) -> None:
                self.__tag = tag

            def apply(self, inputs):
                log.append(self.__tag)

                return None, {}
        first = Node("first")
        second = Node("second")
        second.uses = (first,)
        await Reconciler((second, first)).converge()
        self.assertEqual(log, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
