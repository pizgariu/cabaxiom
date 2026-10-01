"""Cross-axis equivalence. The three shipped dispatchers are one verb three ways, so ONE declaration must
come out the same whichever of them drives it - clean or broken."""
import unittest

from cabaxiom import (
    Assessment,
    DriftItem,
    Kahn,
    OnError,
    Parallel,
    Reconciler,
    Step,
    Supervised,
    ThreadDispatcher,
)


class _Written(Step):
    """A step that writes its own class name into a shared world and reports the write, so two runs of ONE
    declaration are comparable by what they LEFT BEHIND rather than by how they got there. assess() reads the
    same world, so a converged run re-probes clean and only the report-only steps hold the residual open."""

    def __init__(self, world: dict):
        self._world = world

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__class__.__name__ in self._world else [DriftItem(self.__class__.__name__, "absent")]), {}

    def apply(self, inputs):
        self._world[self.__class__.__name__] = "written"
        return [DriftItem(self.__class__.__name__, "created")], {}


class Base(_Written):
    pass


class Schema(_Written):
    expects = (Base,)


class Api(_Written):
    expects = (Schema,)


class Cache(_Written):
    pass


class Metrics(_Written):
    pass


class _Nags(Step):
    """A step no dispatcher can satisfy. Drift never clears, so the residual is never trivially empty and the
    dispatchers are compared on a non-empty proof set instead of on three empty lists agreeing."""

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem(self.__class__.__name__, "still wrong")]), {}


class Firewall(_Nags):
    pass


class Quota(_Nags):
    # Hung off Cache so the declaration spans more than one wave, which is what makes the multiset comparison
    # below a real choice: Cache in an early wave, Quota strictly later.
    expects = (Cache,)


class Fuse(Step):
    """The one broken step of the failure declaration."""

    def apply(self, inputs):
        raise RuntimeError("hard I/O failure")


class _Runs(Step):
    def __init__(self, ran: list):
        self._ran = ran

    def apply(self, inputs):
        self._ran.append(self.__class__.__name__)
        return [DriftItem(self.__class__.__name__, "created")], {}


class Downstream(_Runs):
    expects = (Fuse,)


class FarDownstream(_Runs):
    expects = (Downstream,)


class Untouched(_Runs):
    pass


class _Equivalence(unittest.IsolatedAsyncioTestCase):
    """The reading every comparison below shares. Holds no test of its own - it exists so the dispatchers are
    compared through ONE definition of "the same", instead of each class inventing its own."""

    @staticmethod
    def _multiset(items):
        # Order legitimately differs between dispatchers scheduling one wave, so identity is the BAG of
        # (name, message), never the sequence. Sorted rather than Counter so a failure prints readably.
        return sorted((item.name, item.message) for item in items)

    def _declaration(self):
        # Minted fresh per run. The writing steps CARRY the world they mutate, so a second dispatcher handed
        # the first's instances would start from an already-written world and prove nothing.
        world: dict = {}
        steps = (Base(world), Schema(world), Api(world), Cache(world), Metrics(world), Firewall(), Quota())
        return steps, world

    def _broken(self):
        # The failure declaration, minted fresh for the same reason: Fuse -> Downstream -> FarDownstream is
        # the failing chain, Untouched is independent and must still run whichever dispatcher takes it.
        ran: list[str] = []
        return (Fuse(), Downstream(ran), FarDownstream(ran), Untouched(ran)), ran

    def _casualties(self, residual, ran):
        # What a run says about its own breakage, read the way the kernel channels it. `step failed` names
        # the culprit, `step blocked` names who was held back AND who to blame, while `ran` is the ground truth
        # of what actually executed.
        failed = sorted(item.name for item in residual.failures if "step failed" in item.message)
        blocked = self._multiset(item for item in residual.failures if "step blocked" in item.message)
        return failed, blocked, sorted(ran)


class DispatcherEquivalence(_Equivalence):
    """Parallel, Supervised and ThreadDispatcher are one Waves verb three ways - gather, gather-with-polling,
    and a worker thread. Nothing else in the suite runs ONE declaration through all three and compares what
    comes back, so until now the interchange was a claim, not a fact."""

    async def _converged(self, dispatcher):
        steps, world = self._declaration()
        residual = await Reconciler(steps, Kahn(), mode=dispatcher).converge()
        return self._multiset(residual), self._multiset(residual.applied), world

    async def test_every_dispatcher_converges_one_declaration_identically(self):
        readings = {}
        for dispatcher in (Parallel(), Supervised(), ThreadDispatcher()):
            readings[type(dispatcher).__name__] = await self._converged(dispatcher)
        residual, applied, world = readings["Parallel"]
        # Pinned first, so three dispatchers agreeing on nothing cannot pass as three dispatchers agreeing.
        self.assertEqual(residual, [("Firewall", "still wrong"), ("Quota", "still wrong")])
        self.assertEqual(len(applied), 5)
        self.assertEqual(world, {"Base": "written", "Schema": "written", "Api": "written",
                                 "Cache": "written", "Metrics": "written"})
        for name in ("Supervised", "ThreadDispatcher"):
            with self.subTest(mode=name):
                self.assertEqual(readings[name][0], residual)   # the proof set, as a bag
                self.assertEqual(readings[name][1], applied)    # what each run says it changed
                self.assertEqual(readings[name][2], world)      # and what it actually left behind


class FailureEquivalence(_Equivalence):
    """BestEffort has to mean the same thing on every dispatcher. Fuse -> Downstream -> FarDownstream is the
    failing chain, Untouched is independent and must still run whichever dispatcher takes it."""

    async def _verdict(self, dispatcher):
        steps, ran = self._broken()
        residual = await Reconciler(steps, Kahn(), mode=dispatcher).converge()
        return self._casualties(residual, ran)

    async def test_every_dispatcher_reports_the_same_failure_and_blocked_set(self):
        verdicts = {}
        for dispatcher in (Parallel(OnError.BestEffort), Supervised(OnError.BestEffort),
                           ThreadDispatcher(Parallel(OnError.BestEffort))):
            verdicts[type(dispatcher).__name__] = await self._verdict(dispatcher)
        failed, blocked, ran = verdicts["Parallel"]
        self.assertEqual(failed, ["Fuse"])
        self.assertEqual(blocked, [("Downstream", "step blocked: prerequisite Fuse failed"),
                                   ("FarDownstream", "step blocked: prerequisite Fuse failed")])
        self.assertEqual(ran, ["Untouched"])
        for name in ("Supervised", "ThreadDispatcher"):
            with self.subTest(mode=name):
                self.assertEqual(verdicts[name], (failed, blocked, ran))

