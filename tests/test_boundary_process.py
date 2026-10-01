"""RemoteDispatcher over a REAL process boundary - a second interpreter, the Crossing as bytes over a pipe,
work() running where it landed.

tests/test_remote.py proves the protocol honestly and proves it IN THIS PROCESS. Its transport is the shipped
worker called on the coordinator's own stack. The claim a caller actually buys - that a dispatcher can hand a
wave to a worker which does not share this interpreter - is argued there and never demonstrated. This file
demonstrates it. A spawned worker owns the far side, the envelope crosses as bytes and the only things that
come home are the ones the protocol carries.

THE CONTEXT IS SPAWN, chosen here and never inherited from the platform. Fork is Linux's default and it is
the wrong tool twice over. It copies this interpreter mid-flight, event loop, asyncio internals, pool locks
and pytest's own threads included, which is a documented hazard inside an async test and a class of hang that
would be blamed on the kernel. And a forked child would INHERIT this process's module state, which would quietly
falsify the whole point of the freeze doctrine below - a worker that shares our globals proves nothing about a
worker that does not. Spawn re-executes a fresh interpreter and re-imports this module there, so the first
test asserts exactly that (a different pid, an EMPTY copy of a global this process filled in after import).
Forkserver would serve equally on Linux and does not exist on Windows or macOS-without-fork, so spawn is the
one context every platform this package supports can answer.

EVERY WAIT IS BOUNDED, because this is the one file in the suite that could hang a CI run. Each reply is
awaited with a timeout, each join and each poll takes one, the pool is torn down in a module teardown and each
piped worker in an addCleanup, while the one worker that is EXPECTED never to answer is waited on briefly.
A broken worker fails a test here. It does not hold the suite open.

PLATFORMS. Everything below rides multiprocessing's spawn context, which CPython supports on Linux, macOS and
Windows. Rather than guess from sys.platform, the file performs one real handshake with a real worker and
SKIPS LOUDLY when the sandbox cannot start one (no shared-memory semaphores, no exec, an import mode a
spawned child cannot resolve). A skip here means the boundary claims are unproven on that platform, which the
skip says so in those words."""
import asyncio
import multiprocessing
import os
import pickle
import sys
import threading
import unittest
from collections.abc import Callable
from multiprocessing.connection import Connection
from multiprocessing.pool import Pool

from cabaxiom import (
    Assessment,
    Cancelled,
    Crossing,
    DriftItem,
    Observer,
    OnError,
    Parallel,
    Reconciler,
    RemoteDispatcher,
    Retry,
    Skew,
    Step,
)

# The one deliberate context. See the module docstring for why it is not the platform's default.
CONTEXT = multiprocessing.get_context("spawn")

# What a HEALTHY crossing is given. A real crossing answers in single-digit milliseconds, so this bound is
# never reached by working code - it exists so a wedged worker becomes a failed test in twenty seconds
# instead of a suite that never returns.
PATIENCE = 20.0

# What a worker EXPECTED to die is given. Nothing can arrive, so the only thing a longer wait would buy is a
# slower suite.
BRIEF = 0.5

# Two module globals, one per direction, both of them the world that does NOT cross. The coordinator fills
# the first in at run time (never at import, which a spawned child re-runs), while a worker fills the second in
# on its own copy of this module.
COORDINATOR_ONLY: list[str] = []
SCRIBBLES: list[str] = []


class Seed(Step):
    """The head of the parity declaration, module-level because pickle addresses a class by its import path -
    the same reason test_remote.py gives, plus the reason it matters more here, since the far side really does
    have to import this module to find the class."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {"seed": "9"}

    def apply(self, inputs):
        return [DriftItem("seed", "seeded")], {"seed": "9"}


class Doubled(Step):
    """Stands on Seed and reads what it produced. Its own report is correct ONLY when the artifact made the
    round trip - out as this step's inputs, home as its prerequisite's reply."""

    expects = (Seed,)

    def assess(self, inputs):
        arrived = inputs.get("seed")
        return Assessment(deviation=[] if arrived == "9" else [DriftItem("doubled", f"seed never arrived, got {arrived!r}")]), {"doubled": "18"}

    def apply(self, inputs):
        return [DriftItem("doubled", f"doubled {inputs['seed']}")], {"doubled": "18"}


class Nags(Step):
    """A step nothing can satisfy. The two runs below are then compared over a NON-EMPTY proof set rather
    than over two empty lists agreeing with each other."""

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("nags", "still wrong")]), {}


class Witness(Step):
    """Reports where it ran and what its own interpreter's copy of this module holds. The premise every other
    test here leans on, turned into an artifact this side can assert."""

    def apply(self, inputs):
        return [DriftItem("witness", "ran")], {"pid": os.getpid(), "parent": os.getppid(), "inherited": tuple(COORDINATOR_ONLY)}


class Vandal(Step):
    """Mutates everything within reach AND hands back an artifact. Its module global and its own instance
    cell are the two things a worker cannot send home, while the artifact is the one thing it can."""

    def __init__(self):
        # A held list, mutated in place rather than reassigned, which is what the frozen Step contract allows.
        self.notebook = []

    def apply(self, inputs):
        SCRIBBLES.append("the worker's own module global")
        self.notebook.append("the worker's own instance")
        return [DriftItem("vandal", "scribbled on its own copy")], {"receipt": "the only thing that crosses"}


class Doomed(Step):
    """A write that dies on the far side. The exception has to come home as a record, not as a hang."""

    def apply(self, inputs):
        raise RuntimeError("the far side could not write")


class Aborting(Step):
    """A write that observes an abort on the far side. Cancelled must cut through a real boundary exactly as
    it cuts through a loopback one."""

    def apply(self, inputs):
        raise Cancelled("the worker observed the abort")


class Unwireable(Step):
    """A declaration that cannot be pickled at all, because it carries a lock. Legal to construct, legal to
    run locally and refused by the wire before a byte leaves this process."""

    def __init__(self):
        self.handle = threading.Lock()


class Vanishing(Step):
    """A teardown that kills its own worker outright. No exception, no reply, nothing to ferry - the case a
    transport's bounded wait exists for, plus the case an unbounded one turns into a hung suite."""

    def prune(self, inputs):
        os._exit(70)


class Watching(Observer):
    """Records what retried() announces, so an attempt spent on the far side is counted rather than assumed."""

    def __init__(self):
        self.announced: list[tuple[Step, int]] = []

    def retried(self, step, attempt, error) -> None:
        self.announced.append((step, attempt))


class Bare:
    """The shipped worker, unwrapped, serving ONE envelope over a pipe.

    This is what a naive deployment writes - work() called directly, its return value sent home. It is here
    to show precisely what that shape does with the protocol's own refusals, which is not what a reader of
    work() would expect (see BareWorkerTests).

    It mutes its own stderr because this worker is EXPECTED to die in one test and the interpreter's death
    traceback is noise on the suite's console, not the finding."""

    @staticmethod
    def serve(connection: Connection) -> None:
        muted = os.open(os.devnull, os.O_WRONLY)
        os.dup2(muted, 2)
        connection.send_bytes(RemoteDispatcher.work(connection.recv_bytes()))


class Pumped:
    """A worker framework's own pump over the same envelope, which is the shape work()'s docstring points a
    real deployment at.

    It differs from Bare in one line and that line is load-bearing. A BaseException out of work() - the
    envelope guards raise Skew, which is one by design - is turned into the protocol's OWN skew fate and sent
    home, so the refusal reaches the coordinator as a sentence rather than dying with the interpreter that
    wrote it."""

    @staticmethod
    def serve(connection: Connection) -> None:
        while True:
            payload = connection.recv_bytes()
            try:
                connection.send_bytes(RemoteDispatcher.work(payload))
            except BaseException as refused:
                # A worker's outermost frame catches EVERYTHING or its pipe goes silent, where a silent pipe is
                # the one failure a coordinator cannot tell apart from a wedged machine.
                connection.send_bytes(pickle.dumps(("skew", f"{type(refused).__name__} - {refused}")))


class Pooled:
    """The concurrent transport - a wave's crossings handed to a pool of spawned workers.

    Async on purpose. A blocking transport would pin the coordinator's event loop for a whole crossing and
    serialise the wave, while the kernel takes a transport in both colours, so the reply is awaited off the loop
    through a worker thread while the pool's own pipe does the carrying. The verb of every envelope is recorded
    the way test_remote.py's loopback records it, by NAME off the Crossing."""

    def __init__(self, pool: Pool, patience: float = PATIENCE):
        self._pool = pool
        self._patience = patience
        self.verbs: list[str] = []

    async def __call__(self, payload: bytes) -> bytes:
        self.verbs.append(pickle.loads(payload).verb)
        return await asyncio.to_thread(self.__ship, payload)

    def __ship(self, payload: bytes) -> bytes:
        reply = self._pool.apply_async(RemoteDispatcher.work, (payload,))
        try:
            return reply.get(timeout=self._patience)
        except multiprocessing.TimeoutError:
            # BOUNDING THE WAIT IS THE TRANSPORT'S JOB and the kernel says so - Supervised bounds the wait on
            # a crossing, never the remote work. A worker that died mid-write sends nothing at all, so without
            # this timeout the coordinator would await a reply no living process is going to write.
            raise TimeoutError(
                f"the worker did not answer within {self._patience} seconds, so the crossing was abandoned. "
                f"Whether the write landed before the worker stopped is unknown to this side."
            ) from None


class Piped:
    """The precise transport - one named worker process, one duplex pipe, one crossing at a time.

    Pooled above is the concurrent one. This is the one whose far side this test can name, join and read an
    exit code from, which is what the envelope-vetting claims need - "the worker refused" and "the worker
    died" are the same silence over a pool.

    `version` rewrites the envelope's version on the way out. It is the only honest way to model a peer
    running other code, because _VERSION is a property of the code by design and not a parameter two sides
    could negotiate per instance."""

    def __init__(self, worker: Callable[[Connection], None], version: int | None = None):
        self.version = version
        self.crossings = 0
        self.here, self.there = CONTEXT.Pipe()
        self.__turn = threading.Lock()
        # A daemon, so a worker that wedges cannot keep the interpreter alive after the suite is done with it.
        self.process = CONTEXT.Process(target=worker, args=(self.there,), daemon=True)
        self.process.start()

    async def __call__(self, payload: bytes) -> bytes:
        self.crossings += 1
        if self.version is not None:
            payload = pickle.dumps(pickle.loads(payload)._replace(version=self.version))
        return await asyncio.to_thread(self.__ship, payload)

    def __ship(self, payload: bytes) -> bytes:
        # One pipe is one conversation. The lock is what makes this transport safe for a wave wider than one
        # step, where two threads would otherwise interleave their halves of two crossings.
        with self.__turn:
            self.here.send_bytes(payload)
            if not self.here.poll(timeout=PATIENCE):
                raise TimeoutError(f"the worker did not answer within {PATIENCE} seconds")
            return self.here.recv_bytes()

    def hand(self, envelope: bytes) -> None:
        # One envelope with NO reply awaited, for the case where the far side is expected to die instead of
        # answering. Bypasses the retry, the record and the run - the claim is about the worker alone.
        self.here.send_bytes(envelope)

    def settled(self) -> int | None:
        # The worker's exit code once it has stopped, bounded. None means it is still running. A generous
        # bound costs nothing when the worker really does stop, since join returns the moment it does and it
        # is what keeps this from failing on a loaded machine that merely took its time.
        self.process.join(timeout=PATIENCE)
        return self.process.exitcode

    def answered(self) -> bool:
        return self.here.poll(0)

    def close(self) -> None:
        self.process.kill()
        self.process.join(timeout=PATIENCE)
        self.here.close()
        self.there.close()


class Interpreters:
    """The one shared pool of real second interpreters plus the bounded way in and out of it.

    Built ONCE for the whole file and lazily, because a spawned interpreter costs tens of milliseconds and
    every test here would otherwise pay that twice. Torn down in tearDownModule, whatever the tests did to
    it.

    demand() is a HANDSHAKE and not a platform guess. It ships one real envelope to one real worker and
    checks the fate that comes back, so a sandbox that forbids what this file needs is reported as the skip
    it is instead of a confusing failure inside an unrelated assertion."""

    _pool: Pool | None = None
    _refusal: str | None = None
    _asked = False

    @classmethod
    def pool(cls) -> Pool:
        if cls._pool is None:
            # Written the instant BEFORE any worker exists. That order is what makes the emptiness a spawned
            # child reports a fact about SPAWN rather than a fact about timing - a forked child would have
            # carried this very line away with it.
            COORDINATOR_ONLY.append("written by the coordinator before any worker existed")
            cls._pool = CONTEXT.Pool(processes=2)
        return cls._pool

    @classmethod
    def demand(cls) -> Pool:
        if not cls._asked:
            cls._asked = True
            cls.__handshake()
        if cls._refusal is not None:
            raise unittest.SkipTest(cls.__unproven())
        return cls.pool()

    @classmethod
    def __handshake(cls) -> None:
        try:
            envelope = pickle.dumps(Crossing(RemoteDispatcher._VERSION, "apply", Witness(), {}))
            fate, _ferried = pickle.loads(cls.pool().apply_async(RemoteDispatcher.work, (envelope,)).get(timeout=PATIENCE))
            if fate != "outcome":
                cls._refusal = f"the handshake worker answered the fate {fate!r} rather than an outcome"
        except Exception as refused:
            cls._refusal = f"{type(refused).__name__} - {refused}"
        if cls._refusal is not None:
            cls.close()
            # Said once, on stderr, because a silent skip of THIS file reads as a passing suite while the
            # only tests that touch a real boundary never ran.
            print(cls.__unproven(), file=sys.stderr)

    @classmethod
    def __unproven(cls) -> str:
        return (
            f"THE REAL PROCESS BOUNDARY COULD NOT BE BUILT ON THIS PLATFORM ({cls._refusal}). Every claim in "
            f"tests/test_boundary_process.py is therefore UNPROVEN here - the wire's in-process suite still "
            f"passes, yet nothing has demonstrated that a worker which does not share this interpreter works "
            f"at all. Run the suite where multiprocessing can spawn."
        )

    @classmethod
    def close(cls) -> None:
        pool, cls._pool = cls._pool, None
        if pool is not None:
            # terminate() rather than close(), on purpose. This is a teardown, not a drain - a wedged worker
            # gets a signal and the suite moves on, where close() would wait for work that may never finish.
            pool.terminate()
            pool.join()


def tearDownModule() -> None:
    # unittest's own module hook, which is the one reason this is a function and not a method - the shared
    # pool is torn down however the tests above ended.
    Interpreters.close()


class _Boundary(unittest.IsolatedAsyncioTestCase):
    """The handshake and the readings every claim below shares. Holds no test of its own - it exists so the
    local run and the remote one are compared through ONE definition of "the same"."""

    def setUp(self):
        self.pool = Interpreters.demand()

    @staticmethod
    def _multiset(items):
        # Order legitimately differs when a wave is scheduled two ways, so identity is the BAG of
        # (name, message). Sorted rather than counted, which keeps a failure readable. test_equivalence.py's
        # rule, kept word for word, because this file asks that file's question about a second interpreter.
        return sorted((item.name, item.message) for item in items)

    @staticmethod
    def _produced(residual):
        # The data-flow record keyed by NAME rather than by instance, since the two runs being compared are
        # two separate declarations and their instances are deliberately not the same objects.
        return {Step.named(step): dict(artifacts) for step, artifacts in residual.produced.items()}

    def _declaration(self):
        # Fresh instances per run. Seed -> Doubled spans two waves, while Nags holds the residual open.
        return (Seed(), Doubled(), Nags())


class RemoteConvergenceTests(_Boundary):
    """A declaration converges when its waves execute in ANOTHER interpreter, with the same residual, the
    same applied channel and the same data-flow a local Parallel produces over the same declaration.

    The bug class this catches is everything that works only because the worker shares this process. The
    suite has shipped two of them already, both from the same gap - ThreadDispatcher under Retry never ran
    apply() at all and its probe mangled an async read - and both were invisible because no test put the
    two objects in one Reconciler. A loopback wire has exactly that shape. It executes the worker half on the
    coordinator's own stack, so an artifact that was never really serialised, a global the far side should
    not have seen, plus a reply that is the same object rather than a copy of one, all pass there."""

    async def test_the_far_side_is_a_second_interpreter(self):
        # The premise the rest of this file rests on, asserted instead of assumed. A different pid says
        # another process ran the write. An EMPTY copy of a global this process filled in before the workers
        # existed says that process imported this module FRESH, which is what spawn means and what a fork
        # would have contradicted. And it is OUR child rather than a stray, because its parent is this pid.
        self.assertTrue(COORDINATOR_ONLY)   # this side holds it, while the contrast below is that the far side does not
        witness = Witness()
        residual = await Reconciler((witness,), mode=RemoteDispatcher(Pooled(self.pool))).converge()
        self.assertEqual(residual, [])
        attested = residual.produced[witness]
        self.assertNotEqual(attested["pid"], os.getpid())
        self.assertEqual(attested["parent"], os.getpid())
        self.assertEqual(attested["inherited"], ())

    async def test_a_declaration_converges_over_the_boundary_exactly_as_it_does_here(self):
        # Waves in another interpreter, compared against the local Parallel over the same declaration. The
        # applied line "doubled 9" is the round trip in one string - Seed's artifact came home as a reply,
        # was recorded against the ORIGINAL instance and was mounted into the envelope Doubled crossed in.
        wire = Pooled(self.pool)
        crossed = await Reconciler(self._declaration(), mode=RemoteDispatcher(wire)).converge()
        here = await Reconciler(self._declaration(), mode=Parallel()).converge()
        # Pinned first, so two runs agreeing on nothing cannot pass as two runs agreeing.
        self.assertEqual(self._multiset(crossed), [("nags", "still wrong")])
        self.assertEqual(self._multiset(crossed.applied), [("doubled", "doubled 9"), ("seed", "seeded")])
        self.assertEqual(self._produced(crossed), {"Seed": {"seed": "9"}, "Doubled": {"doubled": "18"}, "Nags": {}})
        self.assertEqual(self._multiset(crossed), self._multiset(here))
        self.assertEqual(self._multiset(crossed.applied), self._multiset(here.applied))
        self.assertEqual(self._produced(crossed), self._produced(here))
        # Both phases really crossed, one envelope per step per phase, with the read side crossing too.
        self.assertEqual(wire.verbs.count("apply"), 3)
        self.assertEqual(wire.verbs.count("assess"), 3)
        self.assertEqual(set(wire.verbs), {"apply", "assess"})


class FreezeAcrossTheBoundaryTests(_Boundary):
    """THE WORLD CROSSES BACK ONLY THROUGH ARTIFACTS. A worker mutating its own copy of a shared object
    changes nothing here, which is the whole reason a step must RETURN what it learned instead of keeping it.

    Nothing else in the suite can show this. Every in-process transport shares one heap, so a step that
    quietly accumulated on `self` or wrote to a module global would look like it worked - and the freeze
    doctrine, the sentence the Step docstring spends a paragraph on, would be a style rule rather than a fact.
    The bug class is a domain that carries state across a boundary in the one way that cannot survive it and
    it fails silently in exactly one direction, which is the direction nobody tests."""

    def setUp(self):
        super().setUp()
        SCRIBBLES.clear()

    async def test_a_worker_mutation_is_invisible_here_and_only_the_artifact_crosses(self):
        travelled, stayed = Vandal(), Vandal()
        remote = await Reconciler((travelled,), mode=RemoteDispatcher(Pooled(self.pool))).converge()
        # The step RAN - its own reported change is in the applied channel and its artifact is in the record -
        # and yet nothing it touched on the far side is visible from here.
        self.assertEqual(remote, [])
        self.assertEqual([item.message for item in remote.applied], ["scribbled on its own copy"])
        self.assertEqual(remote.produced[travelled], {"receipt": "the only thing that crosses"})
        self.assertEqual(SCRIBBLES, [])
        self.assertEqual(travelled.notebook, [])
        # And the same step run HERE mutates both, which is what makes the two lines above a fact about the
        # boundary rather than a step that quietly does nothing.
        local = await Reconciler((stayed,), mode=Parallel()).converge()
        self.assertEqual(local.produced[stayed], {"receipt": "the only thing that crosses"})
        self.assertEqual(SCRIBBLES, ["the worker's own module global"])
        self.assertEqual(stayed.notebook, ["the worker's own instance"])


class VersionSkewTests(_Boundary):
    """A version the worker does not speak is refused ACROSS THE REAL BOUNDARY, with the refusal naming both
    versions where the caller can read it.

    test_remote.py pins this by calling work() in this process and catching the Skew off the call stack. That
    is the one shape a real deployment never has, because the refusal is written in one interpreter and has
    to be read in another. The bug class is a protocol guard that is loud on the worker's console and silent
    at the coordinator, which is indistinguishable from a wedged worker to the only party that can act."""

    def setUp(self):
        super().setUp()
        # A version no worker of this release can speak, which is what a coordinator deployed AHEAD of its
        # workers looks like from the far side - the deployment order work()'s own message warns against.
        self.skewed = RemoteDispatcher._VERSION + 41

    async def test_the_refusal_names_the_version_it_cannot_speak(self):
        wire = Piped(Pumped.serve, version=self.skewed)
        self.addCleanup(wire.close)
        with self.assertRaises(Skew) as refused:
            await Reconciler((Witness(),), mode=RemoteDispatcher(wire)).converge()
        spoken = str(refused.exception)
        self.assertIn(f"protocol version {self.skewed}", spoken)
        self.assertIn(f"this worker speaks {RemoteDispatcher._VERSION}", spoken)
        self.assertIn("Deploy workers before coordinators", spoken)
        self.assertEqual(wire.crossings, 1)          # the envelope really left, one refusal ended the run
        self.assertTrue(wire.process.is_alive())     # a REFUSAL, not a death - the worker is still serving


class BareWorkerTests(_Boundary):
    """What the shipped worker does with its own envelope guards when nothing wraps it, over a real boundary.

    THIS TEST PINS A HAZARD RATHER THAN A GUARANTEE. The two must not be confused. work() raises Skew for
    the three envelope questions it vets, where Skew is a BaseException by design. A worker process whose
    outermost frame is work() therefore DIES of the refusal - multiprocessing's own worker loop catches
    Exception, so the sentence naming the version is written to the child's stderr and never sent home. The
    coordinator sees no reply at all, which is precisely what a wedged worker looks like. Cancelled's
    docstring already names this mechanism in the kernel's own words, that a BaseException escaping a pool
    worker would hang the pool, which is why work() ferries a worker-raised abort as a value instead of
    raising it. The envelope guards do not take the same care, though the protocol has the fate for it -
    ("skew", a sentence) already crosses for a reply that cannot pickle.

    Until that changes, THIS is the sentence a deployment has to read - a real worker must wrap work() the way
    Pumped does. VersionSkewTests above proves that wrapper delivers the refusal."""

    def test_a_bare_worker_dies_of_the_refusal_and_the_sentence_never_comes_home(self):
        wire = Piped(Bare.serve)
        self.addCleanup(wire.close)
        wire.hand(pickle.dumps(Crossing(RemoteDispatcher._VERSION + 41, "apply", Witness(), {})))
        # The worker stopped and it stopped BADLY - a nonzero exit rather than an answer.
        self.assertEqual(wire.settled(), 1)
        self.assertFalse(wire.answered())


class FerriedFailureTests(_Boundary):
    """An exception raised in another interpreter arrives on this side as a failure in the record, an abort
    raised there still cuts through here, while a worker that stops answering becomes a recorded failure rather
    than a hang.

    The bug class is the whole reason this file has timeouts in it. A boundary failure has three plausible
    endings and only one of them is correct - the record says so, the run reports clean or the coordinator
    waits forever. The last two are what an in-process transport can never distinguish, because a loopback
    exception is just a frame on the same stack."""

    async def test_a_worker_exception_arrives_as_a_recorded_failure(self):
        wire = Pooled(self.pool)
        residual = await Reconciler((Doomed(),), mode=RemoteDispatcher(wire, Parallel(OnError.BestEffort))).converge()
        self.assertEqual(self._multiset(residual.failures), [("Doomed", "step failed: RuntimeError: the far side could not write")])
        self.assertEqual(wire.verbs.count("apply"), 1)   # ferried home, not re-shipped

    async def test_a_worker_abort_cuts_through_the_real_boundary(self):
        # An abort is a decision wherever it is made. It crosses as a pickled BaseException and cuts through
        # BestEffort on this side, exactly as it does everywhere else.
        wire = Pooled(self.pool)
        with self.assertRaises(Cancelled) as cut:
            await Reconciler((Aborting(),), mode=RemoteDispatcher(wire, Parallel(OnError.BestEffort))).converge()
        self.assertIn("the worker observed the abort", str(cut.exception))

    async def test_a_worker_that_stops_answering_is_recorded_rather_than_awaited_forever(self):
        # The step kills its own interpreter mid-write. There is no exception to ferry and no reply to wait
        # for. A teardown rather than a converge, deliberately - prune takes no re-probe, which keeps the
        # claim about the bounded wait alone and never races a respawned worker.
        #
        # Its own pool, because this one loses a worker. The shared pool is left healthy for its neighbours.
        with CONTEXT.Pool(processes=1) as pool:
            # Warmed first, with one ordinary crossing, so the brief patience below is measuring a worker's
            # death rather than an interpreter starting up on a loaded machine.
            pool.apply_async(RemoteDispatcher.work, (pickle.dumps(Crossing(RemoteDispatcher._VERSION, "apply", Witness(), {})),)).get(timeout=PATIENCE)
            wire = Pooled(pool, patience=BRIEF)
            residual = await Reconciler((Vanishing(),), mode=RemoteDispatcher(wire, Parallel(OnError.BestEffort))).prune()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step failed: TimeoutError", spoken)
        self.assertIn("the crossing was abandoned", spoken)
        self.assertEqual([item.name for item in residual], ["Vanishing"])


class UnwireableStepTests(_Boundary):
    """A step that cannot be pickled is refused with a sentence a caller can act on, refused BEFORE a
    byte leaves this process, so the far side never meets half an envelope.

    The bug class is a declaration that is legal everywhere except on a wire. It constructs, it runs under
    every local dispatcher and it only fails once a transport is composed in - which is the composition
    nothing had tested. Both directions are pinned here, because they end differently by design. A write is
    a value the Ledger classifies and a read is the run's proof, so a broken probe raises its wave's group
    instead of being collected."""

    async def test_the_write_direction_records_it_and_nothing_crosses(self):
        watching = Watching()
        wire = Pooled(self.pool)
        residual = await Reconciler((Unwireable(),), mode=RemoteDispatcher(wire, Parallel(OnError.BestEffort)),
                                    retry=Retry(3), observer=watching).prune()
        self.assertEqual([item.name for item in residual], ["Unwireable"])
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step failed: TypeError", spoken)
        self.assertIn("pickle", spoken)
        self.assertEqual(wire.verbs, [])   # refused on this side, so no worker ever saw a partial envelope
        # THE COST OF THAT REFUSAL BEING AN ORDINARY EXCEPTION, measured rather than assumed. A declaration
        # that cannot serialise will not serialise on the third try either, so the whole retry budget is
        # spent finding that out. The wire's own SIZE refusal is the same deterministic shape and says so in
        # its message. This one says nothing about the wire at all.
        self.assertEqual([attempt for _, attempt in watching.announced], [1, 2])

    async def test_the_read_direction_raises_it_as_the_group_the_probe_promises(self):
        wire = Pooled(self.pool)
        with self.assertRaises(BaseExceptionGroup) as broken:
            await Reconciler((Unwireable(),), mode=RemoteDispatcher(wire)).assess()
        self.assertEqual(len(broken.exception.exceptions), 1)
        self.assertIsInstance(broken.exception.exceptions[0], TypeError)
        self.assertIn("pickle", str(broken.exception.exceptions[0]))
        self.assertEqual(wire.verbs, [])

