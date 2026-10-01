"""Capability edges ride every guard unchanged - the payoff of the one-home Graph. Kahn orders them,
verify() rejects their mis-splits, the Ledger blocks through them, Only pulls providers into a targeted
run, Components join through them, then demand() fires at resolution. Not one guard learned a new kind."""
import unittest

from cabaxiom import Components, Graph, OnError, Only, Parallel, Reconciler, Step, WavesPartition


class CapabilityRideTests(unittest.IsolatedAsyncioTestCase):
    async def test_kahn_orders_a_wanter_after_every_provider(self):
        # Two providers of one capability and a step that wants it, handed scrambled. The fan-in puts the
        # wanter after BOTH providers, exactly as `expects` treats two instances of one kind.
        log = []

        class Primary(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                log.append("primary")

                return None, {}
        class Replica(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                log.append("replica")

                return None, {}
        class Api(Step):
            wants = ("database",)

            def apply(self, inputs):
                log.append("api")

                return None, {}
        await Reconciler((Api(), Replica(), Primary())).converge()
        self.assertEqual(log[-1], "api")
        self.assertEqual(sorted(log[:2]), ["primary", "replica"])

    def test_verify_rejects_a_capability_mis_split_with_no_new_guard_code(self):
        # The 0.11.0 requires bug cannot repeat for capabilities. verify() reads the Graph, so the edge
        # kind it never heard of is guarded anyway. Same wave = the fan would ignore the edge = rejected.
        class Db(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)

        db, api = Db(), Api()
        graph = Graph((db, api))
        WavesPartition(((db,), (api,))).verify(graph)   # provider in an earlier wave: honoured
        with self.assertRaises(ValueError) as ctx:
            WavesPartition(((db, api),)).verify(graph)  # provider in the SAME wave: edge ignored, so refused
        self.assertIn("Api depends on Db", str(ctx.exception))

    async def test_best_effort_blocks_the_dependent_of_a_failed_provider(self):
        # The Ledger walks the Graph, so a capability dependent is blocked like any other. The wanter
        # never runs against a database nobody brought up, so the residual names the culprit.
        ran = []

        class BoomDb(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                raise RuntimeError("db bring-up dies")

                return None, {}
        class Api(Step):
            wants = ("database",)

            def apply(self, inputs):
                ran.append("api")

                return None, {}
        residual = await Reconciler((BoomDb(), Api()), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])
        messages = [item.message for item in residual]
        self.assertEqual(sum("step blocked: prerequisite BoomDb failed" in message for message in messages), 1)

    async def test_only_pulls_the_providers_of_a_target_into_the_run(self):
        # A targeted run stays a correct run across the capability edge too: Only's closure reads the
        # Graph, so the provider rides in and the bystander stays out.
        log = []

        class Db(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                log.append("db")

                return None, {}
        class Metrics(Step):
            def apply(self, inputs):
                log.append("metrics")

                return None, {}
        class Api(Step):
            wants = ("database",)

            def apply(self, inputs):
                log.append("api")

                return None, {}
        await Reconciler((Db(), Metrics(), Api()), scope=Only(Api)).converge()
        self.assertEqual(log, ["db", "api"])

    async def test_components_weld_a_capability_edge_into_one_chain(self):
        # The union-find lives in the Graph, so a capability edge welds its two ends into one connected
        # component while the loner stays its own - the same grouping `expects` produces, read straight off
        # Components.chains. And the default run still holds the edge in series. db resolves before api.
        log = []

        class Db(Step):
            provides = frozenset({"database"})

            def apply(self, inputs):
                log.append("db")

                return None, {}
        class Api(Step):
            wants = ("database",)

            def apply(self, inputs):
                log.append("api")

                return None, {}
        class Loner(Step):
            def apply(self, inputs):
                log.append("loner")

                return None, {}
        db, api, loner = Db(), Api(), Loner()
        chains = Components().chains(Graph((db, api, loner)))
        welded = {frozenset(type(step).__name__ for step in chain) for chain in chains}
        self.assertIn(frozenset({"Db", "Api"}), welded)   # the capability edge joined them
        self.assertIn(frozenset({"Loner"}), welded)       # the loner rode alone

        await Reconciler((db, api, loner)).converge()
        self.assertLess(log.index("db"), log.index("api"))
        self.assertIn("loner", log)

    def test_a_demand_nothing_provides_fails_at_construction(self):
        # The hard flavour fires with the other resolution guards - loudly, upfront, naming both sides.
        class Api(Step):
            demands = ("database",)

        with self.assertRaises(ValueError) as ctx:
            Reconciler((Api(),))
        self.assertIn("Api demands 'database'", str(ctx.exception))

