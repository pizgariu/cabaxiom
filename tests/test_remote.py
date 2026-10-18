"""RemoteDispatcher, the wire as a shipped leaf. The verb rides the envelope, retry rides the crossings.

The doctrine test_wire.py pins is executed here by real surface - a decorator whose transport carries
a versioned Crossing out, whose worker half runs the clone and ferries the outcome or the exception
back, whose books - Graph, Ledger, observer hooks - never leave the originals. The transport in
these tests is the shipped worker itself (the loopback wire), sometimes behind a thread or a fault
injector, so every claim is proven over the actual protocol bytes."""
import asyncio
import pickle
import threading
import unittest

from cabaxiom import (
    Assessment,
    Authority,
    Cancellation,
    Cancelled,
    Crossing,
    DriftItem,
    Graph,
    Local,
    Observer,
    OnError,
    Parallel,
    Permit,
    Reconciler,
    RemoteDispatcher,
    Retry,
    Skew,
    Step,
    Supervised,
    ThreadDispatcher,
    Write,
)
from cabaxiom.laboratory import Adversary, ChaosDispatcher, Sabotage


class Producer(Step):
    """Computes remotely. Its artifacts are what the wire must carry back. Module-level, since pickle
    addresses a class by its import path."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {"payload": "made-remotely"}

    def apply(self, inputs):
        return [DriftItem("wire", "made remotely")], {"payload": "made-remotely"}


class Consumer(Step):
    """Reads what the producer made, routed to it by the Ledger keyed on the ORIGINAL instances."""

    expects = (Producer,)

    def assess(self, inputs):
        arrived = inputs.get("payload") == "made-remotely"
        return Assessment(deviation=[] if arrived else [DriftItem("consumer", "payload never arrived")]), {}


class Sleeper(Step):
    """A coroutine write. The worker drives it to completion on a fresh loop of its own."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {}

    async def apply(self, inputs):
        await asyncio.sleep(0)
        return [DriftItem("sleeper", "awaited remotely")], {}


class Doomed(Step):
    """A write that dies on the worker. The exception must ferry back and be recorded, not swallowed."""

    def apply(self, inputs):
        raise RuntimeError("remote write dies")


class Aborting(Step):
    """A write that observes the abort on the worker: Cancelled must cut through the wire."""

    def apply(self, inputs):
        raise Cancelled("the worker observed the abort")


class GroupAborting(Step):
    """A write whose own TaskGroup dies of a pure abort. The group must ferry as the abort itself, so
    Cancelled cuts through the wire even out of a hook's inner concurrency."""

    def apply(self, inputs):
        raise BaseExceptionGroup("the hook's own group", [Cancelled("the worker observed the abort")])


class GroupFailing(Step):
    """A write whose TaskGroup dies of ordinary failures. Anything besides a pure abort ferries as the
    group it is, so no member is silently promoted or dropped."""

    def apply(self, inputs):
        raise ExceptionGroup("two inner writes died", [RuntimeError("left"), RuntimeError("right")])


class Leaky(Step):
    """A write that lands but hands back an unpicklable artifact - legal locally, skew on the wire."""

    def apply(self, inputs):
        return None, {"handle": threading.Lock()}


class Unpicklable(Exception):
    """An exception whose own pickling dies, so its ferry must degrade to its story as text."""

    def __reduce__(self):
        raise TypeError("this exception refuses to pickle")


class Picky(Step):
    """A write whose failure cannot cross as an object. The diagnosis must still cross as a sentence."""

    def apply(self, inputs):
        raise Unpicklable("the world said no")


class Loopback:
    """The shipped worker as the carriage - a transport that records every envelope's verb, then runs
    the envelope exactly where a remote worker would - the loopback wire."""

    def __init__(self):
        self.verbs: list[str] = []

    def __call__(self, payload: bytes) -> bytes:
        self.verbs.append(pickle.loads(payload).verb)   # named, so a grown envelope needs no reshuffle
        return RemoteDispatcher.work(payload)


class FlakyWire(Loopback):
    """A wire whose first crossings drop on the network - the transient failure retry exists for."""

    def __init__(self, failures: int):
        super().__init__()
        self.failures = [failures]
        self.crossings = [0]

    def __call__(self, payload: bytes) -> bytes:
        self.crossings[0] += 1
        if self.failures[0]:
            self.failures[0] -= 1
            raise ConnectionError("the wire dropped")
        return super().__call__(payload)


LANDED: list[str] = []


class Counted(Step):
    """Counts every apply that actually RUNS, wherever it runs. The worker unpickles a CLONE, so no
    instance could carry the tally home - but the loopback worker shares this process, so a module-level
    count is exactly what the world would have seen happen to it."""

    def apply(self, inputs):
        LANDED.append("apply")

        return None, {}


class CountedLeaky(Counted):
    """Lands and counts, then hands back an artifact that cannot cross. The write is DONE and only the
    reply skews. The one shape that proves a landed write is never retried."""

    def apply(self, inputs):
        super().apply(inputs)

        return None, {"handle": threading.Lock()}


class Follower(Step):
    """Stands on a write that skews, so the sentence it is handed can be read."""

    expects = (CountedLeaky,)

    def apply(self, inputs):
        return None, {}


class DroppedReply(Loopback):
    """A wire that lets the work LAND and only then loses the reply on the way home.

    FlakyWire cannot model this. It raises BEFORE the worker runs, so the write never happened and a
    retry is free. This one is the dangerous half of a flaky network, the half the coordinator
    cannot tell apart from the safe one - which is why the contract it pins is at-least-once rather than
    a promise the kernel has no way to keep."""

    def __init__(self, drops: int):
        super().__init__()
        self.drops = [drops]

    def __call__(self, payload: bytes) -> bytes:
        landed = super().__call__(payload)   # the worker RAN: whatever it did to the world is done
        if self.drops[0]:
            self.drops[0] -= 1
            raise ConnectionError("the reply never made it home")
        return landed


class Hoarder(Step):
    """Given a per-instance declaration heavy enough to blow a tiny ceiling on the way OUT - the weight
    must ride the INSTANCE, because a class attribute crosses the wire as a reference, not as bytes."""

    def apply(self, inputs):
        return None, {}


class BigProducer(Counted):
    """Lands and counts, then hands back artifacts heavier than a tiny ceiling - the reply direction."""

    def apply(self, inputs):
        super().apply(inputs)

        return None, {"blob": "x" * 4096}


class Chatty(Step):
    """Heavy in both directions, for proving the default ceiling is no ceiling at all."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {"blob": "x" * 4096}

    def apply(self, inputs):
        return None, {"blob": "x" * 4096}


class Permitted(Step):
    """A write that DECLARES a capacity and counts its landings in the module-level tally.

    Module-level for the reason every step here is - the envelope pickles the class by its import path -
    and counting through the tally rather than through `self` because the write runs on a clone, so the
    instance that declared the permit is not the instance that would have recorded holding one."""

    leases = (Permit("api", 3),)

    def apply(self, inputs):
        LANDED.append("apply")

        return [DriftItem("wire", "landed")], {}


class Denying(Authority):
    """A pool that is permanently empty and RECORDS every ask.

    Both halves of the wire's promise need it. That the authority is asked at all is one question and
    that a denial actually stops the crossing is another, where an implementation could pass either alone
    by accident."""

    def __init__(self):
        self.asked: list[str] = []

    def acquire(self, permit, holder):
        self.asked.append(permit.name)
        return False

    def release(self, permit, holder):
        ...


class Tallying(Authority):
    """A pool that always grants, counts every ask and keeps its own set of holders.

    It is an Authority of its own rather than a subclass of `Local`, which is final for a reason worth
    respecting even in a test. What it adds over the shipped one is the ask LOG, since the question here
    is how many times a capacity was asked for one write and whether the slot came back afterwards."""

    def __init__(self):
        self.asked: list[str] = []
        self.holders: set[str] = set()

    def acquire(self, permit, holder):
        self.asked.append(permit.name)
        self.holders.add(holder)
        return True

    def release(self, permit, holder):
        self.holders.discard(holder)


class Granting(Authority):
    """Grants its first `slots` asks of a run and refuses every later one - a pool that FILLS mid-write.

    It is the narrowest authority that can compose a denial with something already having happened, which is
    what the retry axis crossed with this one needs. A permanently empty pool refuses the first ask too, so
    no crossing ever happens and there is nothing for a denial to be wrong about."""

    def __init__(self, slots: int):
        self.slots = slots
        self.asked: list[str] = []

    def acquire(self, permit, holder):
        self.asked.append(permit.name)
        return len(self.asked) <= self.slots

    def release(self, permit, holder):
        ...


class Watching(Observer):
    """Records what retried() announces, so the wire's attempts are provably spent on the real step."""

    def __init__(self):
        self.announced: list[tuple[Step, int]] = []

    def retried(self, step, attempt, error) -> None:
        self.announced.append((step, attempt))


class RemoteDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_wire_converges_and_the_verbs_ride_the_envelopes(self):
        # The whole leaf in one converge. Every hook crossed as an envelope, the artifacts came back and
        # routed to the original consumer, with each envelope saying which verb it carried.
        wire = Loopback()
        residual = await Reconciler((Producer(), Consumer()), mode=RemoteDispatcher(wire)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["made remotely"])
        self.assertEqual(wire.verbs.count("apply"), 2)    # both writes crossed
        self.assertEqual(wire.verbs.count("assess"), 2)   # and the re-probe that proves them
        self.assertEqual(set(wire.verbs), {"apply", "assess"})

    async def test_a_teardown_says_prune(self):
        # The verb is the run's, not a constant. The same dispatcher on a prune ships "prune".
        wire = Loopback()
        residue = await Reconciler((Producer(), Consumer()), mode=RemoteDispatcher(wire)).prune()
        self.assertEqual(residue, [])
        self.assertEqual(set(wire.verbs), {"prune"})
        self.assertEqual(len(wire.verbs), 2)

    async def test_retry_rides_the_wire_and_announces_the_real_step(self):
        # The run's retry is re-laid over the transport call, so a dropped crossing spends an attempt
        # exactly as a transient write does - and retried() announces the ORIGINAL instance, never a
        # clone or a stand-in, because the wire call takes the step the payload was built from.
        wire = FlakyWire(2)
        watching = Watching()
        producer, consumer = Producer(), Consumer()
        residual = await Reconciler((producer, consumer), mode=RemoteDispatcher(wire),
                                    retry=Retry(3), observer=watching).converge()
        self.assertEqual(residual, [])
        self.assertEqual(wire.crossings[0], 6)   # 3 for the flaky write, 1 clean write, 2 probe reads
        self.assertEqual([attempt for _, attempt in watching.announced], [1, 2])
        for announced, _ in watching.announced:
            self.assertIs(announced, producer)

    async def test_a_remote_failure_is_ferried_and_recorded(self):
        # The worker catches what the hook raised and ships it back. The coordinator re-raises it inside
        # its own machinery, so BestEffort records the failure exactly as if the write had died here.
        underlying = Parallel(OnError.BestEffort)
        residual = await Reconciler((Doomed(),), mode=RemoteDispatcher(RemoteDispatcher.work, underlying)).converge()
        self.assertEqual(sum("step failed: RuntimeError: remote write dies" in item.message for item in residual), 1)

    async def test_a_remote_abort_cuts_through_the_wire(self):
        # An abort is a decision wherever it is made: Cancelled ferries back and cuts through BestEffort
        # on the coordinator, exactly as it cuts through everything else.
        underlying = Parallel(OnError.BestEffort)
        with self.assertRaises(Cancelled):
            await Reconciler((Aborting(),), mode=RemoteDispatcher(RemoteDispatcher.work, underlying)).converge()

    async def test_an_async_transport_carries_an_async_hook(self):
        # Both colours on both sides. The transport is a coroutine (awaited like every hook the kernel
        # takes) and the step's own apply is one too - driven to completion by the worker's fresh loop,
        # off this loop's thread.
        async def carriage(payload: bytes) -> bytes:
            return await asyncio.to_thread(RemoteDispatcher.work, payload)

        residual = await Reconciler((Sleeper(),), mode=RemoteDispatcher(carriage)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["awaited remotely"])

    async def test_it_wraps_supervised_too(self):
        # Any WAVE dispatcher underneath, same freedom as ThreadDispatcher's. Honesty note: Supervised
        # here bounds the WAIT on a crossing, never the remote work itself - an in-flight write on the
        # far side runs to completion after a coordinator-side abort.
        residual = await Reconciler((Producer(), Consumer()),
                                    mode=RemoteDispatcher(RemoteDispatcher.work, Supervised(poll=0.01))).converge()
        self.assertEqual(residual, [])

    async def test_the_chaos_axis_composes_inside_the_wire(self):
        # The documented order - chaos INSIDE remote, so the strikes land on the crossings themselves and
        # the Write reaches the wire intact. Zero rates here - the composition shape is the claim.
        inner = ChaosDispatcher(Parallel(), Sabotage())
        residual = await Reconciler((Producer(), Consumer()),
                                    mode=RemoteDispatcher(RemoteDispatcher.work, inner)).converge()
        self.assertEqual(residual, [])

    def test_a_thread_underlying_is_refused_at_construction(self):
        # The thread bridge narrows the write to a synchronous call and a crossing is a coroutine, so
        # the pairing would ship zero envelopes and blame the steps - refused where it is written.
        with self.assertRaises(ValueError) as refused:
            RemoteDispatcher(RemoteDispatcher.work, ThreadDispatcher())
        self.assertIn("cannot wrap a ThreadDispatcher", str(refused.exception))

    async def test_a_bare_callable_is_refused_with_the_fix_named(self):
        # The envelope needs the verb and a bare closure carries none. Refused loudly, naming both exits
        # AND the stripping-decorator case, instead of shipping an envelope that guesses.
        step = Producer()
        remote = RemoteDispatcher(RemoteDispatcher.work)
        with self.assertRaises(ValueError) as refused:
            await remote.dispatcher.execute(((step,),), Graph((step,)), lambda s, i: (None, {}), Cancellation(), Observer())
        self.assertIn("needs the verb in its envelope", str(refused.exception))
        self.assertIn("Write", str(refused.exception))
        self.assertIn("INSIDE this one", str(refused.exception))

    def test_an_unknown_verb_is_protocol_skew(self):
        # The worker guards the protocol's whole vocabulary. An envelope naming anything but the three
        # step verbs is a skew between the two sides, refused where it lands - and refused as Skew, so a
        # loopback wire cannot spend the run's attempts on a verb no version of the protocol has.
        with self.assertRaises(Skew) as refused:
            RemoteDispatcher.work(pickle.dumps(Crossing(RemoteDispatcher._VERSION, "audit", Producer(), {})))
        self.assertIn("no verb of the step contract", str(refused.exception))


class WireProtocolGuardTests(unittest.IsolatedAsyncioTestCase):
    """The reply's fate is guarded as strictly as the outbound verb. Every hole here was found by an
    adversarial pump before it shipped. A reply the coordinator does not recognise must be skew said out
    loud, never a silent success for dependents to build on."""

    async def test_a_skewed_reply_fate_is_refused(self):
        # A custom pump answering fates of its own invention. The run must NOT converge on them.
        def pump(payload: bytes) -> bytes:
            return pickle.dumps(("ok", (None, {})))

        with self.assertRaises(Skew) as refused:
            await Reconciler((Producer(),), mode=RemoteDispatcher(pump)).converge()
        self.assertIn("no fate of the wire protocol", str(refused.exception))

    async def test_a_raised_fate_without_an_exception_is_refused(self):
        # The sharpest hole the review found. A reply SAYING the hook raised, ferrying no exception,
        # used to be returned as the outcome - the failure vanished and the run reported clean.
        def pump(payload: bytes) -> bytes:
            return pickle.dumps(("raised", "boom, as a string"))

        with self.assertRaises(Skew) as refused:
            await Reconciler((Producer(),), mode=RemoteDispatcher(pump)).converge()
        self.assertIn("instead of an exception", str(refused.exception))

    async def test_a_reply_that_cannot_pickle_tells_the_truth(self):
        # The write LANDED and only its reply refused to cross. The error must say exactly that, never
        # impersonate the hook - a "step failed" for a step that succeeded would hand retry a landed write.
        residual = await Reconciler((Leaky(),), mode=RemoteDispatcher(RemoteDispatcher.work,
                                                                            Parallel(OnError.BestEffort))).converge()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("ran on the worker. Its reply refuses to pickle", spoken)
        self.assertIn("wire-safe", spoken)

    async def test_an_exception_that_refuses_to_pickle_still_tells_its_story(self):
        # A ferried failure whose own pickling dies must still arrive as its story, not as a bare
        # serialization error that erases the diagnosis.
        residual = await Reconciler((Picky(),), mode=RemoteDispatcher(RemoteDispatcher.work,
                                                                            Parallel(OnError.BestEffort))).converge()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("Unpicklable", spoken)
        self.assertIn("refuses to pickle", spoken)

    async def test_the_loopback_names_the_fix_for_a_coroutine_hook(self):
        # work() on the coordinator's own loop cannot drive a coroutine hook. The refusal ferries back
        # naming the fix, instead of the raw cannot-be-called-from-a-running-loop confusion.
        with self.assertRaises(RuntimeError) as refused:
            await Reconciler((Sleeper(),), mode=RemoteDispatcher(RemoteDispatcher.work)).converge()
        self.assertIn("asyncio.to_thread", str(refused.exception))


class FerriedGroupTests(unittest.IsolatedAsyncioTestCase):
    """The worker-side twin of run_wave's sift. A hook may die as a whole exception GROUP, which the wire
    must sort an abort from a failure exactly as the wave dispatchers do on the coordinator's side."""

    async def test_a_pure_abort_group_ferries_as_the_abort_itself(self):
        # A group of nothing but Cancelled IS the abort. It crosses as itself and cuts through, so
        # `except Cancelled` on the coordinator still means what it means everywhere else.
        with self.assertRaises(Cancelled) as cut:
            await Reconciler((GroupAborting(),), mode=RemoteDispatcher(RemoteDispatcher.work)).converge()
        self.assertIn("the worker observed the abort", str(cut.exception))

    async def test_a_mixed_group_ferries_as_the_group_it_is(self):
        # Anything besides a pure abort stays a group, so neither member is promoted over the other and
        # the record names the whole death, not a lucky half of it.
        remote = RemoteDispatcher(RemoteDispatcher.work, Parallel(OnError.BestEffort))
        residual = await Reconciler((GroupFailing(),), mode=remote).converge()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step failed: ExceptionGroup: two inner writes died", spoken)


class LandedWriteTests(unittest.IsolatedAsyncioTestCase):
    """What happens to a write that ALREADY RAN on the worker - the half of the wire the first shipped
    suite left uncovered, because its fault injector failed before the worker ever got the envelope.

    Two cases live here and they are not the same case. When the worker KNOWS the write landed and only
    its reply cannot cross, it says so and that sentence must not be spent as a retryable failure. That
    was a bug and the first test is its pin. When the REPLY ITSELF is lost on the way home, nobody knows
    anything - a dropped reply is indistinguishable from a dropped envelope - so the attempts are spent by
    design, which is at-least-once and is the caller's to opt into."""

    def setUp(self):
        LANDED.clear()

    async def test_a_landed_write_whose_reply_cannot_cross_is_not_retried(self):
        # THE REGRESSION. The worker declines to say "step failed" for a hook that already ran, which
        # refusal used to be undone one frame later. The coordinator raised it as a ValueError, INSIDE the
        # retry-wrapped callable, while the attempt loop catches Exception. Measured before the fix. Three
        # applies of a write that landed once, reported as a verified clean converge. Skew is a
        # BaseException for the same reason Cancelled is, so the loop structurally cannot spend it.
        residual = await Reconciler((CountedLeaky(),), mode=RemoteDispatcher(RemoteDispatcher.work, Parallel(OnError.BestEffort)), retry=Retry(3)).converge()
        self.assertEqual(len(LANDED), 1)   # NOT three: the write landed once and stayed landed once
        spoken = " ".join(item.message for item in residual)
        self.assertIn("ran on the worker. Its reply refuses to pickle", spoken)

    async def test_a_dependent_of_a_skew_is_not_told_its_prerequisite_failed(self):
        # The lie one hop out. The skewed write may have LANDED, so a dependent blocked behind it must not
        # read "prerequisite Landing failed" - the word comes off the culprit's own recorded fate, only
        # the CONSEQUENCE (it was blocked) is asserted as fact.
        residual = await Reconciler((CountedLeaky(), Follower()), mode=RemoteDispatcher(RemoteDispatcher.work, Parallel(OnError.BestEffort))).converge()
        spoken = [item.message for item in residual]
        self.assertIn("step unconfirmed: Skew: The apply ran on the worker", " ".join(spoken))
        self.assertIn("step blocked: prerequisite CountedLeaky did not settle", spoken)

    async def test_a_skew_is_still_recorded_rather_than_vaporising_the_wave(self):
        # Not retried is not the same as cutting the run down. A skew is a value the ONE Ledger rule
        # classifies, so under BestEffort it blocks just that step's dependents and every wave-mate keeps
        # its own settled outcome - one skewed unit must not take a wave's other thousands with it.
        skewed, clean = CountedLeaky(), Counted()
        residual = await Reconciler((skewed, clean), mode=RemoteDispatcher(RemoteDispatcher.work, Parallel(OnError.BestEffort)), retry=Retry(3)).converge()
        self.assertEqual(len(LANDED), 2)   # both ran, once each: the clean one was not cancelled mid-flight
        self.assertEqual(sum("refuses to pickle" in item.message for item in residual), 1)

    async def test_a_skew_still_raises_under_fail_fast(self):
        # The policy still decides. FailFast re-raises it as itself, so a caller catches it by name - and
        # `except Exception` around a converge deliberately does NOT, which is the whole point of the type.
        with self.assertRaises(Skew) as refused:
            await Reconciler((CountedLeaky(),), mode=RemoteDispatcher(RemoteDispatcher.work), retry=Retry(3)).converge()
        self.assertIn("ran on the worker", str(refused.exception))
        self.assertEqual(len(LANDED), 1)

    async def test_a_reply_dropped_after_the_work_landed_spends_the_attempts(self):
        # The honest counterpart and NOT a bug. A reply lost on the way home is indistinguishable from an
        # envelope lost on the way out, so retry re-ships and the write lands again. Retry(n) over a wire is
        # therefore an opt-in at-least-once, which a domain answers with an idempotent apply() - the same
        # contract the kernel already asks for and lets Idempotence prove.
        wire = DroppedReply(drops=2)
        await Reconciler((Counted(),), mode=RemoteDispatcher(wire), retry=Retry(3)).converge()
        self.assertEqual(len(LANDED), 3)                            # two dropped replies, three landings
        self.assertEqual(wire.verbs.count("apply"), 3)              # three write crossings, not one

    async def test_the_default_retry_crosses_a_landed_write_exactly_once(self):
        # The shipped default is Retry(1), which wraps nothing, so the dangerous case above cannot arise
        # unless a caller asks for it. This is the sentence an operator needs before putting an invoice or
        # a payment behind the wire. at-most-once per cycle is the default, at-least-once is a choice.
        with self.assertRaises(ConnectionError):
            await Reconciler((Counted(),), mode=RemoteDispatcher(DroppedReply(drops=1))).converge()
        self.assertEqual(len(LANDED), 1)


class WirePermitTests(unittest.IsolatedAsyncioTestCase):
    """A declared capacity is enforced over the wire, by the COORDINATOR, before the envelope goes out.

    THE BUG CLASS is this file's founding one wearing a quieter layer. execute() laid the run's retry over
    the crossing through `rewire`, which lays that ONE layer, so the permit the carrier holds was
    substituted away with the local hook and a step declaring `leases` crossed with its pool never asked
    once. Nothing raised and every channel read clean, which is why the wire suite could not see it.
    Measured before the fix, one step declaring `Permit("api", 3)` against an authority that always
    refuses - under `Parallel` the authority was asked `['api']` and nothing applied, under
    `RemoteDispatcher` it was asked `[]` and the write LANDED. That is a fence the storage does not
    enforce, which is the verdict the `Crossing` docstring already wrote about exactly this field.

    BOTH HALVES ARE PINNED, because either alone is satisfiable by a mistake. An authority that is asked
    and then ignored enforces nothing, while a write that never crossed proves nothing about a pool if
    nobody ever asked it."""

    def setUp(self):
        LANDED.clear()

    async def test_a_denied_permit_defers_the_step_instead_of_crossing(self):
        # The whole promise in one run. The pool was asked, the answer was honoured, no envelope carrying
        # the write was ever built, so the step reads as deferred rather than as broken - because
        # nothing about it broke.
        wire = Loopback()
        authority = Denying()
        residual = await Reconciler((Permitted(),), mode=RemoteDispatcher(wire), authority=authority).converge()
        self.assertEqual(authority.asked, ["api"])       # the authority was asked at all
        self.assertEqual(wire.verbs.count("apply"), 0)   # and the write never crossed
        self.assertEqual(LANDED, [])                     # so nothing landed on the far side
        self.assertEqual(residual.applied, ())
        self.assertEqual(residual.failures, ())          # an exhausted pool is not a failure
        self.assertEqual(sum("step deferred" in item.message for item in residual), 1)

    async def test_the_wire_defers_exactly_as_the_event_loop_does(self):
        # The dispatcher axis decides WHERE a write runs and never WHETHER a capacity holds, so the same
        # declaration under the same authority has to read identically through a wire and through the
        # loop - the asks, the world and every line of the record.
        verdicts = []
        for dispatcher in (Parallel(), RemoteDispatcher(RemoteDispatcher.work)):
            LANDED.clear()
            authority = Denying()
            residual = await Reconciler((Permitted(),), mode=dispatcher, authority=authority).converge()
            verdicts.append((authority.asked, list(LANDED),
                             sorted((item.name, item.message) for item in residual)))
        self.assertEqual(verdicts[0], verdicts[1])
        # Pinned absolutely as well, so two dispatchers agreeing on nothing cannot pass as two agreeing.
        asked, landed, record = verdicts[0]
        self.assertEqual(asked, ["api"])
        self.assertEqual(landed, [])
        self.assertEqual([name for name, _ in record], ["Permitted"])
        self.assertTrue(record[0][1].startswith("step deferred"))

    async def test_the_pool_is_asked_once_per_crossing_and_every_slot_comes_back(self):
        # The permit sits INSIDE the retry on the wire exactly as it does in-process, so a re-shipped
        # envelope re-asks instead of holding a slot across a backoff it is not using. And the slot is
        # returned whether the crossing carried a write home or a dropped connection, since a slot a dead
        # run still holds is a slot nobody can reclaim.
        wire = FlakyWire(2)
        authority = Tallying()
        residual = await Reconciler((Permitted(),), mode=RemoteDispatcher(wire), retry=Retry(3),
                                    authority=authority).converge()
        self.assertEqual(residual, [])
        self.assertEqual(authority.asked, ["api", "api", "api"])   # one ask per crossing, not one per step
        self.assertEqual(authority.holders, set())                 # and every one of them came back
        self.assertEqual(LANDED, ["apply"])                        # the write landed once, on the third try
        self.assertEqual(wire.crossings[0], 4)                     # 3 write crossings plus the re-probe

    async def test_a_read_asks_for_no_capacity_on_the_wire_either(self):
        # The permit layer belongs to the WRITE, here as everywhere. A probe under a denying authority
        # therefore crosses and answers, rather than deferring a read nobody declared a pool for.
        wire = Loopback()
        authority = Denying()
        reading = await Reconciler((Permitted(),), mode=RemoteDispatcher(wire), authority=authority).assess()
        self.assertEqual(reading, [])
        self.assertEqual(authority.asked, [])
        self.assertEqual(wire.verbs, ["assess"])

    async def test_a_dropped_crossing_outranks_a_denial_on_the_next_attempt(self):
        # WHERE TWO FIXES MEET, where neither alone can be trusted to keep this true. Asking the pool per
        # crossing is what makes a denial reachable on the wire at all, while the attempt loop is what decides
        # what a denial MEANS once a crossing has already failed. Composed - the first crossing drops, the
        # pool then refuses the second attempt, so the run reports the dropped connection rather than a
        # deferral claiming the apply never ran. It DID cross and what it did on the far side is unknown,
        # which is the one thing "nothing broke and nothing changed" may not be said about.
        wire = FlakyWire(1)
        authority = Granting(1)
        with self.assertRaises(ConnectionError) as broke:
            await Reconciler((Permitted(),), mode=RemoteDispatcher(wire), retry=Retry(2),
                             authority=authority).converge()
        self.assertEqual(str(broke.exception), "the wire dropped")
        self.assertEqual(authority.asked, ["api", "api"])   # asked per crossing, refused the second time
        self.assertEqual(wire.crossings[0], 1)              # so the second envelope was never built
        self.assertEqual(LANDED, [])
        # The denial's sentence does not ride out as the failure's context, here as in-process.
        self.assertTrue(broke.exception.__suppress_context__)

    async def test_a_denial_with_no_dropped_crossing_behind_it_is_still_a_deferral(self):
        # The control for the pairing above plus the promise it must not spend. A wire that carries every
        # crossing cleanly and a pool that is simply full still reports a deferral under the DEFAULT policy
        # rather than aborting, because nothing broke - the ruling Ledger.record keeps one layer further in.
        wire = Loopback()
        authority = Granting(0)
        residual = await Reconciler((Permitted(),), mode=RemoteDispatcher(wire), retry=Retry(2),
                                    authority=authority).converge()
        self.assertEqual(list(residual.failures), [])
        self.assertEqual(sum("step deferred" in item.message for item in residual), 1)
        self.assertEqual(wire.verbs.count("apply"), 0)
        self.assertEqual(LANDED, [])


class WriteTests(unittest.IsolatedAsyncioTestCase):
    """The carrier's own contract. It IS the callable, it SAYS the verb, rewire() lays the same
    retry over a different raw call, while relay() lays the whole stack over a RELOCATED hook.

    The bug class relay() defends against has shipped twice in the same place. A decorator that moves the
    write somewhere else - onto a worker thread, over a wire - rebuilt the stack around a layer that was
    already wrapped, so the work quietly ran back where it started while every outcome stayed correct.
    Once that layer was the retry, once it was the permit. Both are pinned here at the seam and
    behaviourally in tests/test_retry.py and tests/test_orthogonality.py."""

    def test_it_is_the_callable_and_says_the_verb(self):
        def raw(step, inputs):
            return [DriftItem("w", "wrote")], {}

        write = Write(Retry(1), Observer(), raw, "apply")
        self.assertEqual(write.verb, "apply")
        produced, artifacts = write(Producer(), {})
        self.assertEqual([item.message for item in produced], ["wrote"])
        self.assertEqual(artifacts, {})

    def test_the_neutral_retry_rewires_to_the_raw_call_itself(self):
        # Retry(1) wraps nothing, so rewiring under it hands back exactly the callable given - the
        # same identity the retry axis already promises for its own wrapping.
        def wire_call(step, inputs):
            return None, {}

        write = Write(Retry(1), Observer(), lambda s, i: (None, {}), "prune")
        self.assertIs(write.rewire(wire_call), wire_call)

    def test_relay_relocates_the_hook_underneath_the_permit_and_not_the_permit_itself(self):
        # What a relocating decorator must go through. It hands in HOW it moves a call and gets the stack
        # __call__ has, so the permit layer stays OUTSIDE the relocation. Rebuilding from `raw` instead
        # relocated that layer, so with an authority injected `raw` is a coroutine function whatever the
        # step's own colour, so the relocation only built a coroutine and the write ran back home.
        relocated = []

        def hook(step, inputs):
            return None, {}

        def relocate(raw):
            relocated.append(raw)
            return raw

        gated = Write(Retry(1), Observer(), hook, "apply", Local())
        self.assertIsNot(gated.raw, hook)              # the permit layer is real and it sits over the hook
        self.assertIsNot(gated.relay(relocate), hook)  # relay hands back the stack, permit layer included
        self.assertEqual(relocated, [hook])            # and what it relocated is the hook, never that layer

    def test_relay_costs_nothing_when_both_layers_it_lays_are_neutral(self):
        # Retry(1) wraps nothing and no authority permits nothing, so relay must hand back exactly what the
        # relocation returned. A decorator is then free to reach for it unconditionally.
        def hook(step, inputs):
            return None, {}

        threaded = Write(Retry(1), Observer(), hook, "apply").relay(lambda raw: raw)
        self.assertIs(threaded, hook)


class WireCeilingTests(unittest.IsolatedAsyncioTestCase):
    """The control-plane rule, enforced at the only place the payload is already bytes. Artifacts carry
    pointers, while a frame that tries to be the data plane is refused by name, in both directions."""

    async def test_an_oversized_envelope_is_refused_before_it_crosses(self):
        hoarder = Hoarder()
        hoarder.tags = frozenset({"x" * 4096})   # a declaration slot, so it stays settable and rides the envelope
        with self.assertRaises(ValueError) as refused:
            await Reconciler((hoarder,), mode=RemoteDispatcher(RemoteDispatcher.work, limit=512)).converge()
        spoken = str(refused.exception)
        self.assertIn("envelope for Hoarder", spoken)
        self.assertIn("against the wire's limit of 512", spoken)
        self.assertIn("pointers, not payloads", spoken)

    async def test_an_oversized_reply_is_a_skew_so_the_landed_write_is_not_retried(self):
        # The reply direction is the dangerous one. The work LANDED, so the refusal must be the fate a
        # retry structurally cannot spend - one apply at any budget, exactly like the unpicklable reply.
        LANDED.clear()
        with self.assertRaises(Skew) as refused:
            await Reconciler((BigProducer(),), mode=RemoteDispatcher(RemoteDispatcher.work, limit=512),
                             retry=Retry(3)).converge()
        self.assertEqual(len(LANDED), 1)   # landed once, never re-shipped to fetch the same oversized reply
        self.assertIn("reply is", str(refused.exception))
        self.assertIn("let the data plane move the data", str(refused.exception))

    async def test_no_limit_means_unlimited_and_a_bad_limit_is_refused(self):
        residual = await Reconciler((Chatty(),), mode=RemoteDispatcher(RemoteDispatcher.work)).converge()
        self.assertEqual(residual, [])   # the default carries what it always carried
        with self.assertRaises(ValueError) as refused:
            RemoteDispatcher(RemoteDispatcher.work, limit=0)
        self.assertIn("positive byte count or None", str(refused.exception))


THREADS: list[str] = []    # the thread every write in a matrix cell really ran on, wherever it ran
STUMBLED: list[str] = []   # the one failure Stumbles is allowed per matrix cell


class Located(Step):
    """Records the thread its write really ran on and declares a capacity so the permit layer is reached
    at all. Module level like every step here, because the envelope addresses a class by its import path,
    and it reports through a module list rather than through `self` because the wire runs a clone."""

    leases = (Permit("api", 3),)

    def apply(self, inputs):
        THREADS.append(threading.current_thread().name)

        return [DriftItem("matrix", "wrote")], {}

    def prune(self, inputs):
        THREADS.append(threading.current_thread().name)

        return None, {}


class Stumbles(Located):
    """Loses its first attempt of a matrix cell and then behaves, so the retry layer has something to be
    laid around. The one permitted failure is spent against a module list rather than against a coin,
    because a matrix cell that flips is not a measurement - and against a module list rather than an
    instance field because the wire's clone is not the instance that stumbled."""

    def apply(self, inputs):
        if not STUMBLED:
            STUMBLED.append("once")
            raise ConnectionError("the write broke once")
        return super().apply(inputs)


class Dropping(Adversary):
    """An adversary that always drops. Deterministic on purpose - Sabotage rolls dice, where a matrix cell
    decided by a coin is an anecdote rather than a measurement."""

    async def strike(self, step):
        raise ConnectionError("the injected adversary dropped the connection")


class EveryDecoratorOrderingTests(unittest.IsolatedAsyncioTestCase):
    """Every ordering of every pair and every triple of the three decorators, held to the ONE invariant
    all four of this family's bugs broke.

    THE BUG CLASS, stated as an invariant for the first time. Four shipped defects were one sentence - a
    decorator rebuilt the write stack around a layer that was already wrapped - and every one of them was
    caught by a test written for that single composition after the fact. Nothing in the tree said the RULE.
    This says it over the whole enumeration, so a fifth shape has nowhere left to hide. A relocated write
    lands where its decorator moved it, with every layer the carrier holds is laid over the relocation
    rather than under it.

    Five of the fifteen orderings run and ten are refused, where WHICH ten is part of the invariant. A
    pairing that cannot keep the promise is refused at construction (either other decorator over the thread
    bridge) or refused loudly at the first write (the wire handed a callable somebody already rebuilt).
    The orderings are written outermost-first, so `TC` is ThreadDispatcher(ChaosDispatcher(Parallel())).

    The matrix is the whole enumeration and not a sample of it, which the first test proves rather than
    promises - so a decorator added to this family fails here until its row is written."""

    # The verdict for each ordering. `runs` keeps the promise, `refused` is a ValueError at construction,
    # `carrierless` is the wire refusing a rebuilt callable at the first write.
    _MATRIX = {
        "T": "runs", "C": "runs", "R": "runs",
        "TC": "runs", "RC": "runs",
        "TR": "carrierless", "CR": "carrierless", "TCR": "carrierless", "TRC": "carrierless",
        "CT": "refused", "RT": "refused", "CTR": "refused", "CRT": "refused", "RTC": "refused", "RCT": "refused",
    }

    # The five live orderings plus whether the chaos decorator in each holds the carrier. A chaos decorator
    # is only OUTERMOST in one of them. That is the whole difference the last test measures.
    _LIVE = ("T", "C", "R", "TC", "RC")

    @staticmethod
    def _built(order, policy=OnError.FailFast, adversary=None):
        # Composed inside out, so the string reads outermost-first exactly as the composition is written.
        struck = adversary if adversary is not None else Sabotage()
        built = Parallel(policy)
        for letter in reversed(order):
            if letter == "T":
                built = ThreadDispatcher(built)
            elif letter == "C":
                built = ChaosDispatcher(built, struck)
            else:
                built = RemoteDispatcher(Loopback(), built)
        return built

    async def _cell(self, order, step, policy=OnError.FailFast, adversary=None, verb="converge", **axes):
        THREADS.clear()
        STUMBLED.clear()
        LANDED.clear()
        authority, watching = Tallying(), Watching()
        reconciler = Reconciler((step,), mode=self._built(order, policy, adversary),
                                authority=authority, observer=watching, retry=Retry(3), **axes)
        residual = await getattr(reconciler, verb)()
        return residual, authority, watching

    def test_the_enumeration_is_every_ordering_of_every_pair_and_every_triple(self):
        # The matrix is complete by construction rather than by having been typed carefully once. A fourth
        # decorator or a row deleted in a hurry fails here before any behaviour is measured.
        letters = "TCR"
        enumerated = (
            [(one,) for one in letters]
            + [(one, two) for one in letters for two in letters if one != two]
            + [(one, two, three) for one in letters for two in letters for three in letters if len({one, two, three}) == 3]
        )
        self.assertEqual({"".join(order) for order in enumerated}, set(self._MATRIX))
        self.assertEqual(len(enumerated), 15)
        self.assertEqual(sorted(name for name, verdict in self._MATRIX.items() if verdict == "runs"), sorted(self._LIVE))

    async def test_every_ordering_either_keeps_the_promise_or_refuses_out_loud(self):
        # No ordering is allowed to be quietly half-composed, which is the only outcome this family has
        # ever actually shipped. Either the run works or somebody is told why at the earliest moment the
        # pairing can be seen - construction where a decorator can see its underlying, the first write
        # where only the callable's shape gives it away.
        for order, verdict in sorted(self._MATRIX.items()):
            with self.subTest(order=order, verdict=verdict):
                if verdict == "refused":
                    with self.assertRaises(ValueError) as denied:
                        self._built(order)
                    self.assertIn("cannot wrap a ThreadDispatcher", str(denied.exception))
                    continue
                if verdict == "carrierless":
                    # The wire is handed a callable an outer decorator rebuilt, so the verb is gone. It
                    # refuses at the first write - and answers a READ perfectly, since the probe has no
                    # carrier to lose, which is exactly why this half-composition needs saying out loud.
                    reading = await Reconciler((Located(),), mode=self._built(order)).assess()
                    self.assertEqual(reading, [])
                    with self.assertRaises(ValueError) as denied:
                        await Reconciler((Located(),), mode=self._built(order)).converge()
                    self.assertIn("needs the verb in its envelope", str(denied.exception))
                    continue
                residual, _, _ = await self._cell(order, Located())
                self.assertEqual(residual, [])

    async def test_every_layer_the_carrier_holds_is_laid_over_the_relocated_write(self):
        # THE INVARIANT ITSELF, on both write verbs. Counted before it is located, because a write that
        # never ran is somewhere other than the event loop too - which is precisely the shape of the first
        # bug this family shipped, plus the reason a where-did-it-run assertion alone proves nothing.
        awaiting = threading.current_thread().name
        for order in self._LIVE:
            for verb in ("converge", "prune"):
                with self.subTest(order=order, verb=verb):
                    _, authority, watching = await self._cell(order, Located(), verb=verb)
                    self.assertEqual(len(THREADS), 1, f"the {verb} write ran {len(THREADS)} times instead of once")
                    if "T" in order:
                        self.assertNotIn(awaiting, THREADS,
                                         f"{order} bridged the {verb} write onto a thread and it ran on the loop anyway")
                    else:
                        self.assertEqual(THREADS, [awaiting])   # nothing else moves a write off this thread
                    self.assertEqual(authority.asked, ["api"])  # the permit layer was laid, once
                    self.assertEqual(authority.holders, set())  # and the slot came back
                    self.assertEqual(watching.announced, [])    # nothing failed, so nothing was retried
        for order in self._LIVE:
            with self.subTest(order=order, layer="retry"):
                # A real transient failure must spend exactly one attempt and re-ask the pool for the
                # second, under every ordering. Both layers are the carrier's, so a decorator that held
                # either of them itself is what every bug in this family did.
                _, authority, watching = await self._cell(order, Stumbles())
                self.assertEqual([attempt for _, attempt in watching.announced], [1])
                self.assertEqual(authority.asked, ["api", "api"])
                self.assertEqual(len(THREADS), 1)

    async def test_a_chaos_strike_rides_inside_the_run_only_where_the_decorator_holds_the_carrier(self):
        # THE ONE PLACE THE INVARIANT IS STILL HALF TRUE, pinned with its exact cost so it cannot be
        # rediscovered by accident and cannot be quietly lost either.
        #
        # relay() answers a plain callable, so only the OUTERMOST decorator is handed a carrier. Chaos
        # outermost lays its strike innermost and an injected drop then spends the budget and the slot a
        # real one spends. Chaos composed INSIDE another decorator is handed an already-flat stack, so its
        # strike sits outside both layers - and the numbers below are what that costs. The day relay()
        # answers a carrier, this test goes red and the third case becomes the first.
        _, authority, watching = await self._cell("C", Located(), OnError.BestEffort, Dropping())
        self.assertEqual([attempt for _, attempt in watching.announced], [1, 2])   # the whole budget, as a real drop would
        self.assertEqual(authority.asked, ["api", "api", "api"])                   # and the slot each attempt would hold
        self.assertEqual(THREADS, [])                                              # the strike never let the write run
        for order in ("TC", "RC"):
            with self.subTest(order=order, limit="the strike is outside the stack"):
                # RemoteDispatcher's own docstring recommends `RC` for sabotaging the wire, so its own
                # promise is that a transient network failure spends an attempt exactly as a transient
                # write does. An INJECTED one spends none, in that very composition, for the same reason
                # the supported thread order spends none.
                residual, authority, watching = await self._cell(order, Located(), OnError.BestEffort, Dropping())
                self.assertEqual(watching.announced, [])
                self.assertEqual(authority.asked, [])
                self.assertEqual(sum("ConnectionError" in item.message for item in residual.failures), 1)


class SupervisedBoundsTheCrossingTests(unittest.IsolatedAsyncioTestCase):
    """The wire's own claim, finally asserted with a firing Cancellation.

    RemoteDispatcher documents that a Supervised underlying bounds the WAIT on a crossing, which the suite
    composed the two but never let anything abort - so the sentence was prose. A transport is just an
    awaitable, so a worker that never answers hangs it forever. Under Parallel the Cancellation is read
    only BETWEEN waves, so a Deadline cannot fire while the wave is in flight and the run hangs with it.
    Supervised polls the wave while it runs, so the abort lands and the coordinator gets its loop back.

    The bound is on the WAIT and never on the far side - a worker that is merely slow keeps running after
    the abort, though a write already in flight may still land. That half is the honest limit the docstring
    states. It is not something a coordinator-side cancellation could ever fix."""

    class _Waiting(Step):
        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("wire", "never answered")]), {}

        def apply(self, inputs):   # pragma: no cover - the crossing never comes back to run it
            return None, {}

    @staticmethod
    async def _never_answers(payload: bytes) -> bytes:
        await asyncio.Event().wait()          # a worker that accepted the envelope and went quiet
        raise AssertionError("unreachable")   # pragma: no cover

    async def test_supervised_lets_a_deadline_cut_a_crossing_that_never_answers(self):
        from cabaxiom import Deadline

        run = Reconciler((self._Waiting(),), cancellation=Deadline(0.05),
                         mode=RemoteDispatcher(self._never_answers, Supervised(poll=0.01, grace=0.05)))
        with self.assertRaises(Cancelled):
            await asyncio.wait_for(run.converge(), timeout=3.0)   # the wait_for is the bound ON THE TEST

    async def test_parallel_cannot_cut_the_same_crossing_which_is_why_supervised_exists(self):
        # The contrast that makes the claim mean something. Same declaration, same dead worker, same
        # Deadline - and the run does NOT come back, because Parallel reads the Cancellation between waves
        # and this wave never ends. The test's own timeout is what ends it.
        from cabaxiom import Deadline

        run = Reconciler((self._Waiting(),), cancellation=Deadline(0.05),
                         mode=RemoteDispatcher(self._never_answers, Parallel()))
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(run.converge(), timeout=0.3)

    async def test_the_read_phase_is_bounded_too_so_the_proof_cannot_hang(self):
        # A converge re-probes, so a wire that hangs the READ would hang the proof - the phase a Deadline
        # could bound nowhere before Supervised polled its reads as well as its writes.
        from cabaxiom import Deadline

        run = Reconciler((self._Waiting(),), cancellation=Deadline(0.05),
                         mode=RemoteDispatcher(self._never_answers, Supervised(poll=0.01, grace=0.05)))
        with self.assertRaises(Cancelled):
            await asyncio.wait_for(run.assess(), timeout=3.0)
