"""The wire boundary. A step crosses to a worker as a CLONE and the kernel never notices.

The frozen Step is what lets a dispatcher hand a step to a worker that does not share this process.
Identity, though, stays the INSTANCE in this process - the kernel's dependency addressing, the thing
Transition's leavers, Succession's swaps and the two-instances-of-one-kind semantics all stand on. The
two claims meet at the dispatcher and only there. A remote dispatcher is a DECORATOR (the
ThreadDispatcher pattern) whose transport ships (step, inputs) out, lets the deserialized clone do the
work, then takes the outcome back on the call's own stack. The ORIGINAL step keys the Graph and the
Ledger throughout, so the clone never touches either.

These tests pin both halves of that doctrine. The boundary pattern works with no kernel identity
change - artifacts made by a clone land against the original and route to its dependents. And the
naive topology, using a returned clone as a key against local maps, is exactly the KeyError it looks
like: a boundary design fault, never a kernel destiny, so the failure is pinned as the contract
rather than fixed by giving steps a global identity the rest of the kernel would pay for."""
import inspect
import pickle
import unittest

from cabaxiom import (
    Assessment,
    Crossing,
    Dispatcher,
    DriftItem,
    Graph,
    Ledger,
    Observer,
    OnError,
    Overlap,
    Reconciler,
    RemoteDispatcher,
    RunMode,
    Skew,
    Step,
    Waves,
)
from cabaxiom.dispatcher import _Gather  # the wave worker is private, so a custom wire wrapper reaches for it here


class Producer(Step):
    """Computes remotely. Its artifacts are the payload the wire must carry back. Module-level, since
    pickle addresses a class by its import path."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {"payload": "made-remotely"}

    def apply(self, inputs):
        return [DriftItem("wire", "made remotely")], {"payload": "made-remotely"}


class Consumer(Step):
    """Reads what the producer made. The Ledger routes the artifacts to it keyed on the ORIGINAL
    instances, which is the exact lookup a clone-keyed topology would break."""

    expects = (Producer,)

    def assess(self, inputs):
        arrived = inputs.get("payload") == "made-remotely"
        return Assessment(deviation=[] if arrived else [DriftItem("consumer", "payload never arrived")]), {}


RAN: list[int] = []


class Counting(Step):
    """Records that it ran, so a refusal can be proved to have refused BEFORE the hook was touched.
    Module-level for the same reason Producer is, since pickle addresses a class by its import path."""

    def apply(self, inputs):
        RAN.append(1)
        return None, {}


class WireDispatcher(Dispatcher):
    """A remote dispatcher in miniature - a DECORATOR over a real one, whose transport is a pickle
    round trip standing in for the network. The write and the read cross the wire as (step, inputs)
    payloads and run on the deserialized CLONE, while the composed dispatcher's wave mechanics - and
    every Graph and Ledger lookup inside them - keep running on the originals. Correlation is the
    call's own stack. The outcome returns to the caller that shipped it, so no clone is ever used as
    a key. A queue-shaped transport would carry a token for the same correlation instead."""

    overlaps = Overlap.WITHIN

    def __init__(self, witnessed: list, underlying: Dispatcher | None = None):
        self._witnessed = witnessed   # each crossing records that the worker saw a DIFFERENT object
        self._underlying = underlying if underlying is not None else _Gather()
        super().__init__(self._underlying._on_error)

    def _shipped(self, call):
        async def wired(step, inputs):
            clone, carried = pickle.loads(pickle.dumps((step, inputs)))   # the network, out
            self._witnessed.append(clone is not step)
            outcome = call(clone, carried)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            return pickle.loads(pickle.dumps(outcome))                    # and the network, back
        return wired

    async def execute(self, groups, graph, do, cancellation, observer):
        return await self._underlying.execute(groups, graph, self._shipped(do), cancellation, observer)

    async def probe(self, groups, graph, read, cancellation, observer):
        return await self._underlying.probe(groups, graph, self._shipped(read), cancellation, observer)


class WireBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_clone_does_the_work_and_the_originals_keep_the_books(self):
        # The whole doctrine in one converge. Every hook ran on a deserialized clone, yet the residual
        # is clean - the clone's artifacts were recorded against the original producer and routed to the
        # original consumer, because the payload crossed the wire and the identity never had to.
        witnessed: list = []
        residual = await Reconciler((Producer(), Consumer()), mode=RunMode(Waves(), WireDispatcher(witnessed))).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["made remotely"])
        self.assertTrue(witnessed, "nothing ever crossed the wire, so the run proved nothing")
        self.assertTrue(all(witnessed), "a crossing handed the worker the original, not a clone")

    async def test_the_naive_topology_is_the_keyerror_it_looks_like(self):
        # The counter-half. Identity is process-local BY DESIGN, so a clone that comes back and is used
        # as a key against local maps misses. That is the boundary's correlation to do (the call stack
        # above or a token on a queue), where pinning the miss keeps anyone from "fixing" it in the
        # kernel with a global identity that Transition's leavers and Succession's swaps would pay for.
        original = Producer()
        graph = Graph((original,))
        clone = pickle.loads(pickle.dumps(original))
        self.assertIsNot(clone, original)
        self.assertNotIn(clone, {original})
        with self.assertRaises(KeyError):
            graph.dependencies(clone)

    async def test_the_ledger_refuses_a_foreign_clone_loudly(self):
        # The sharper half of the same miss. Graph lookups at least CRASH on a clone, yet the Ledger's
        # write path used to accept one - artifacts stored under a key no dependency read ever consults,
        # assemble() answering {} and the run reporting CLEAN. A proof that a boundary bug can
        # silence is no proof, so the record refuses a step that is not the run's own and names the fix.
        producer, consumer = Producer(), Consumer()
        graph = Graph((producer, consumer))
        ledger = Ledger(((producer,), (consumer,)), OnError.BestEffort, Observer(), graph)
        clone = pickle.loads(pickle.dumps(producer))
        with self.assertRaises(ValueError) as refused:
            ledger.record(clone, None, {"payload": "made-remotely"}, None)
        self.assertIn("not a step of this run", str(refused.exception))
        self.assertIn("Correlate at the transport boundary", str(refused.exception))

    def test_a_step_crosses_the_wire_frozen_and_declared(self):
        # The serializability half of the frozen-step promise, pinned. The clone lands with its
        # declaration intact and the freeze still armed, so the worker runs the same contract.
        clone = pickle.loads(pickle.dumps(Consumer()))
        self.assertEqual(clone.expects, (Producer,))
        with self.assertRaises(TypeError):
            clone.smuggled = "state the wire must not admit"
        assessment, _ = clone.assess({"payload": "made-remotely"})
        self.assertEqual(list(assessment.deviation), [])


class VersionedEnvelopeTests(unittest.IsolatedAsyncioTestCase):
    """The envelope as a versioned contract, plus the refusal that makes the version mean something.

    It was an anonymous three-tuple, which pays for every new field twice - once when the shape changes and
    once when a peer on the old shape misreads the new one in silence. The field that forced the change is a
    lease token, where a token dropped without a word is a capacity limit enforced by nobody while every log
    line reports a clean run. So `work()` refuses a version it does not speak instead of reading past it and
    these pin that refusal in both directions, because a guard nobody has watched fail is a guard nobody
    should trust.

    The cost is deliberate and it is deployment order. Workers before coordinators, loudly, rather than a
    silent degradation nobody notices until a limit stops holding."""

    @staticmethod
    def _envelope(**overrides):
        fields = {"version": RemoteDispatcher._VERSION, "verb": "apply", "step": Producer(), "inputs": {}}
        fields.update(overrides)
        return pickle.dumps(Crossing(**fields))

    def test_a_crossing_is_still_a_tuple_so_the_ceiling_is_untouched(self):
        # The byte ceiling measures len(payload) and is blind to the shape on purpose, which is what lets
        # the envelope grow fields without the limit growing a special case.
        crossing = Crossing(1, "apply", Producer(), {})
        self.assertIsInstance(crossing, tuple)
        self.assertEqual(crossing.version, 1)
        self.assertEqual(crossing[0], 1)   # positional and named agree, so old readers of [0] see a version

    def test_the_optional_slots_cross_untouched(self):
        # They are here before the axes that fill them, so those axes cost no second break. This proves the
        # protocol carries them today rather than promising it will.
        landed = pickle.loads(self._envelope(token="lease-7", deadline=99.5, trace="tr-1"))
        self.assertEqual((landed.token, landed.deadline, landed.trace), ("lease-7", 99.5, "tr-1"))

    def test_the_optional_slots_default_to_absent(self):
        landed = pickle.loads(self._envelope())
        self.assertEqual((landed.token, landed.deadline, landed.trace), (None, None, None))

    def test_an_anonymous_tuple_from_an_older_coordinator_is_refused_by_name(self):
        # The exact shape the protocol used to ship. A worker that unpacked it would run fine and drop
        # every field it did not know, so it is refused with the deployment order named.
        with self.assertRaises(Skew) as refused:
            RemoteDispatcher.work(pickle.dumps(("apply", Producer(), {})))
        self.assertIn("rather than a Crossing", str(refused.exception))
        self.assertIn("older code than this worker", str(refused.exception))

    def test_a_newer_version_is_refused_rather_than_read_past(self):
        with self.assertRaises(Skew) as refused:
            RemoteDispatcher.work(self._envelope(version=RemoteDispatcher._VERSION + 1))
        self.assertIn("this worker speaks", str(refused.exception))
        self.assertIn("Deploy workers before coordinators", str(refused.exception))

    def test_an_older_version_is_refused_in_the_same_breath(self):
        # Skew in the other direction is the same fault, so it gets the same answer rather than a lenient
        # one. A worker guessing what an older coordinator meant is a worker inventing a protocol.
        with self.assertRaises(Skew) as refused:
            RemoteDispatcher.work(self._envelope(version=RemoteDispatcher._VERSION - 1))
        self.assertIn("protocol version 0", str(refused.exception))

    def test_the_version_is_vetted_before_the_hook_is_touched(self):
        # Order matters. A refused envelope must not have run anything or a version check would be a
        # report about a write that already landed.
        RAN.clear()
        with self.assertRaises(Skew):
            RemoteDispatcher.work(self._envelope(version=99, step=Counting()))
        self.assertEqual(RAN, [])
        RemoteDispatcher.work(self._envelope(step=Counting()))   # and it DOES run when the version fits
        self.assertEqual(RAN, [1])

    def test_the_verb_guard_still_fires_behind_the_version_guard(self):
        with self.assertRaises(Skew) as refused:
            RemoteDispatcher.work(self._envelope(verb="delete"))
        self.assertIn("no verb of the step contract", str(refused.exception))

    async def test_a_real_crossing_still_works_end_to_end(self):
        # The regression that matters. The coordinator now ships a Crossing and the worker reads one, so a
        # run over the wire has to stay exactly as green as it was before the shape changed.
        producer, consumer = Producer(), Consumer()
        run = Reconciler((producer, consumer),
                         mode=RemoteDispatcher(lambda payload: RemoteDispatcher.work(payload)))
        residual = await run.converge()
        # An empty residual IS the proof, since the consumer's own assess only reads clean when the
        # producer's artifact reached it - across the wire, keyed on the ORIGINAL instances.
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["made remotely"])

