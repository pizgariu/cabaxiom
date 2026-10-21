"""The Ledger. The record of ONE execute() run plus the OnError policy that writes it. The state courier
for the data-flow, extracted from dispatcher.py so the execution machinery imports its record rather
than housing it. Depends only on Step, Graph and the drift types - nothing dispatcher-shaped - so the
dependency arrow runs one way. dispatcher imports ledger, never the reverse."""
from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from types import MappingProxyType
from typing import NamedTuple, final

from ..declaration.cancellation import Cancelled, Deferred, Fault, Skew
from ..declaration.drift import Artifacts, Assessment, Changes, Drift, DriftItem
from ..declaration.held import _Held
from ..declaration.step import Step
from ..plan.graph import Graph
from .observer import Observer


@final
class _Fate(NamedTuple):
    """How a settled step is SPOKEN in the record. The word its own line takes and the clause a LATER
    sentence uses about it. The Colour precedent - the thing knows how it is spoken, so no sentence has to
    assume the only fate is failure.

    Two words rather than one because they sit in different grammar. A step's own line is a verdict on it
    ("step unconfirmed"), while a dependent speaks ABOUT it ("its prerequisite did not settle"). A
    single word cannot be both without reading as a fragment in one of them.

    It exists because "failed" was hardcoded in all three of this module's sentences. For a skew all
    three were false. A write whose reply could not cross had ALREADY LANDED, which is the whole reason the
    worker declines to call it a failure. An empty clause means there is no verb to speak at all - a
    decision to stop is not something that happened TO the step."""

    verdict: str
    clause: str


# The record's whole fate vocabulary, closed because a domain cannot invent one. A write either raised,
# crossed a wire that could not tell us what became of it or never ran because somebody stopped the run.
_FAILED = _Fate("failed", "failed")
_UNCONFIRMED = _Fate("unconfirmed", "did not settle")
_STOPPED = _Fate("stopped", "")
# A step that never ran because a capacity was exhausted. Not a failure in either grammar - its own line
# says it waited and a dependent says it waited, because nothing about it broke.
_DEFERRED = _Fate("deferred", "waited for a permit")


@final
class Statement:
    """What ONE execute() run settled. The writes' returns, the failures and what each settled step
    PRODUCED, keyed by instance - the Ledger's closing statement, the record that used to die as a local
    of the call that kept it.

    `produced` is copied SHALLOW at mint, one fresh dict per step. The Ledger stores the step's own
    returned dict. A step keeping a handle to it (`return None, self._cache`) would otherwise rewrite
    this record after the run. "What was true when the run ended stays true" is the record family's
    founding sentence. The values inside stay the caller's objects, exactly as they are everywhere else
    in the data-flow.

    Deliberately NOT iterable. The house holds precedents on both sides. Residual was made a Sequence so
    callers behave unchanged, since Residual's sequence-ness is meaningful (it IS the drifts). A Statement's
    would be positional plumbing - EdgeKind's exact refusal, tuple-ness as accidental API - and a
    two-channel record has no honest truthiness. So the old unpacking dies loudly at the call
    site, in a major, on purpose."""

    __slots__ = ("__returns", "__failures", "__deferred", "__produced")

    def __init__(self, returns: Sequence[Drift], failures: Sequence[Drift], produced: Mapping[Step, Artifacts] | None = None,
                 deferred: Sequence[Drift] | None = None):
        self.__returns = tuple(returns)
        self.__failures = tuple(failures)
        self.__deferred = tuple(deferred or ())
        self.__produced = {step: dict(artifacts) for step, artifacts in (produced or {}).items()}

    @property
    def returns(self) -> tuple[Drift, ...]:
        return self.__returns

    @property
    def failures(self) -> tuple[Drift, ...]:
        return self.__failures

    @property
    def deferred(self) -> tuple[Drift, ...]:
        # Steps that never ran because a capacity was exhausted, kept APART from failures because nothing
        # about them broke. They still belong in the residual, since a step that did not run is not settled,
        # and a run whose only trouble is a full pool must not read as clean.
        return self.__deferred

    @property
    def produced(self) -> Mapping[Step, Artifacts]:
        # A read-only view, not a copy per ask. The copy was taken once at mint, so every reader sees the
        # one record and nobody can write through it.
        return MappingProxyType(self.__produced)


@final
class Reading(_Held[Drift]):
    """What ONE probe() run read. The deviations in run order and what each step's assess produced -
    the Statement's read twin, kept in the same book because the ledger is where the run's records are
    minted and defined, whichever seam operates them.

    A Sequence, DELIBERATELY, where Statement is deliberately not iterable. The deviations ARE the
    reading - its sequence-ness is its core nature, the Residual precedent, not the positional plumbing
    EdgeKind refuses - so every caller that tested truthiness, iterated, indexed or compared against a
    plain list behaves unchanged, so Reconciler.assess() could grow the produced channel without
    breaking a single consumer. Equality is by items against any sequence, slicing hands back a plain
    tuple, exactly as Residual.

    `produced` is copied shallow at mint, one fresh dict per step, for the record family's founding
    sentence: what was true when the run ended stays true. And one property the boundary's absence
    semantics LEAN on, guaranteed by the shipped probe. A Reading is TOTAL over the run or not minted at
    all - a broken read raises the fan's group before any mint - so an absent key means "answered
    without it", never "did not answer". A custom dispatcher minting a partial Reading would convert a
    read casualty into an honest absence, the one confound the boundary's proof excludes.

    THE OTHER THREE CHANNELS RIDE HERE TOO. They did not before. An Assessment answers four - the
    deviation the residual is made of, the `plan` a converge would carry out, the `advisory` about a step
    already in desired state and the `footprint` a teardown would remove. The probe fan used to keep
    the first and drop the rest, so three quarters of what every step read was computed and thrown away
    inside the fan that asked for it. A gate that judges a run before it writes needs exactly those three,
    since "refuse when more than five things would be torn down" is a question about the footprint and
    cannot be asked of the deviations. They are additive here, so the sequence view is still the deviations
    and no existing caller sees a change."""

    __slots__ = ("__produced", "__plan", "__advisory", "__footprint")

    def __init__(self, deviations: Sequence[Drift], produced: Mapping[Step, Artifacts] | None = None,
                 plan: Sequence[Drift] = (), advisory: Sequence[Drift] = (), footprint: Sequence[Drift] = ()):
        super().__init__(deviations)
        self.__plan = tuple(plan)
        self.__advisory = tuple(advisory)
        self.__footprint = tuple(footprint)
        self.__produced = {step: dict(artifacts) for step, artifacts in (produced or {}).items()}

    @classmethod
    def gathered(cls, settled: Iterable[tuple[Step, Assessment, Artifacts]]) -> "Reading":
        # ONE PROBE'S WORTH OF ASSESSMENTS, FOLDED. Every dispatcher that fans a read ends with the same
        # walk - each step's four channels appended to four lists, each step's artifacts filed by instance -
        # and two of them wrote it out by hand with the five results passed positionally into a constructor
        # where `plan` and `advisory` are the same type, so a swapped pair would have typed clean. The fold
        # lives here once. Every settled step gets an entry in `produced`, empty dict included, so an absent
        # key downstream means "answered without it" rather than "never asked".
        deviation: list[Drift] = []
        plan: list[Drift] = []
        advisory: list[Drift] = []
        footprint: list[Drift] = []
        produced: dict[Step, Artifacts] = {}
        for step, assessment, artifacts in settled:
            deviation.extend(assessment.deviation)
            plan.extend(assessment.plan)
            advisory.extend(assessment.advisory)
            footprint.extend(assessment.footprint)
            produced[step] = artifacts
        return cls(deviation, produced, plan=plan, advisory=advisory, footprint=footprint)

    @property
    def plan(self) -> tuple[Drift, ...]:
        # What a converge WOULD do, flattened in run order. A dry run, the channel a gate reads to judge
        # scale before a single write lands.
        return self.__plan

    @property
    def advisory(self) -> tuple[Drift, ...]:
        # Findings about steps already in desired state, kept out of the deviations on purpose so advice can
        # never dirty a proof. A gate may still refuse on it.
        return self.__advisory

    @property
    def footprint(self) -> tuple[Drift, ...]:
        # What the steps own that a teardown would remove. The channel the destructive-scale question is
        # actually about, the reason all three had to stop dying inside the fan.
        return self.__footprint

    @property
    def produced(self) -> Mapping[Step, Artifacts]:
        # The same read-only view Statement gives. Copied once at mint, written through by nobody.
        return MappingProxyType(self.__produced)

    def __repr__(self) -> str:
        return f"Reading({list(self._held)!r})"


class OnError(Enum):
    # What the dispatcher does when a step's apply() (or prune()) raises.
    FailFast = "FailFast"       # let it propagate and abort the run
    BestEffort = "BestEffort"   # catch it, record it as Drift, block its dependents, keep going with the rest
    Halt = "Halt"               # catch it, record it, then start nothing further and return the record


@final
class Ledger:
    """The record of ONE execute() run - what the writes returned, what each produced, what failed, what a
    failure blocked - and the single raise-or-collect rule that writes it.

    Every dispatcher opens a Ledger over the groups it will walk, asks blocked(step) before each unit of
    work, feeds record(...) each settled outcome and closes with outcome(). The rule lives here, once.
    A Cancelled cuts through under ANY policy (an abort is a decision, not a failure). Any other exception
    re-raises under FailFast. Under BestEffort it is recorded as `step failed` drift and blocks its
    transitive dependents - a step whose declared prerequisite just failed must not run against state
    nobody put there, so it is reported as `step blocked` drift instead, naming the culprit. Under Halt it
    is recorded the same way and the run then stands still. blocked() answers "skip" for every later step,
    each reported as `step skipped` drift naming the culprit.

    Every one of those three sentences reads the culprit's FATE rather than assuming it (see _Fate), because
    "failed" is not always true and each place it was hardcoded was a place the record could lie. A Skew
    reads `step unconfirmed`, since a write whose reply could not cross may well have landed - which is why
    the worker refuses to call it a failure in the first place - and its dependents are blocked by a
    prerequisite that "did not settle" rather than one that failed. A halt() with no failure behind it names
    the step it stopped AT, with no verb at all. The returns of a clean write are collected in
    resolved order. The artifacts it produced are kept so a dependent can read them. A custom dispatcher
    that walks its groups through a Ledger inherits the kernel's entire failure semantics and its data-flow
    without re-deriving a line of either.

    Blocking follows every declared edge kind through the Graph, the kernel's one home for the dependency
    derivation, inverted lazily on the first failure so a clean run pays nothing. On a teardown run (the
    inverse partition) a failed step's dependents have already run, so blocking never fires and prune keeps
    its honest self-verifying semantics. A halt is edge-free and gates teardown too."""

    def __init__(self, groups: tuple[tuple[Step, ...], ...], on_error: OnError, observer: Observer, graph: Graph):
        self.__groups = groups
        self.__on_error = on_error
        self.__observer = observer
        self.__graph = graph   # the RUN's derivation, handed in - never a second one derived here
        self.__returns: list[Drift] = []
        self.__failures: list[Drift] = []
        self.__deferred: list[Drift] = []
        self.__culprits: dict[Step, list[Step]] = {}   # blocked step -> every failed step it stands on
        # Where each step sits in the DECLARATION, so a blocked step names its culprits in an order that
        # is a fact about the world rather than about the strategy that happened to walk it. Built once,
        # from the same tuple the derivation was taken over.
        self.__declared = {step: position for position, step in enumerate(graph.steps)}
        self.__halt: Step | None = None   # the failure that halted the run, once OnError.Halt fires
        # The state courier - what each settled step produced, indexed by producer, so assemble() can
        # mount a step's payload from exactly its prerequisites.
        self.__artifacts: dict[Step, Artifacts] = {}
        # WHAT BECAME of each settled step, so a sentence written later never assumes the fate was failure.
        # Read back by blocked() for a culprit and by the halt clause, which used to spell "failed" by hand.
        self.__fates: dict[Step, _Fate] = {}

    @property
    def groups(self) -> tuple[tuple[Step, ...], ...]:
        # What this record is being kept OVER, in the direction the caller walks them - the forward
        # partition for a converge, the inverted one for a teardown. Published for READING, so a custom
        # dispatcher can ask what it is recording without threading the groups through its own state and
        # read-only because the record's whole discipline is that it is returned, never reached into.
        return self.__groups

    def assemble(self, step: Step) -> Artifacts:
        # A step's payload, assembled from what its prerequisites produced, the data-flow read side. Only
        # the step's own dependencies contribute, so a step reads exactly what it declared an edge to and
        # nothing a sibling happened to leave lying around. The merge itself lives in mounted(), the one
        # home the read fan shares, so the two sides cannot disagree about what a step is handed.
        return Ledger.mounted(step, self.__graph.dependencies(step), self.__artifacts)

    @staticmethod
    def mounted(step: Step, prerequisites: Iterable[Step], produced: Mapping[Step, Artifacts]) -> Artifacts:
        """One step's payload, mounted from what its prerequisites produced - the data-flow merge, spoken
        ONCE. assemble() above builds the write side through it and the dispatchers' read fan builds the
        probe payloads through it, where each used to hand-roll its own copy of the same loop.

        A COLLISION IS REFUSED, never merged. Two prerequisites writing one key used to resolve by
        whichever landed later in derivation order, silently - no drift, no warning, nothing in the
        record. Measured at the fan-in shape this kernel exists to run. Ten thousand shards each
        producing one shared key collapsed to a single value. The other nine thousand nine hundred and
        ninety nine artifacts were destroyed with no trace. A payload that quietly loses data is the
        record lying by omission, the exact defect class the Ledger's own membership guard refuses.

        The refusal is deliberately PER CONSUMER: the same key produced by two steps is legal while no
        single step reads both, because a collision is a fact about one payload, never about the run. A
        run that wants one producer to win says so in the key itself - a namespace is the data contract
        doing its job."""
        payload: Artifacts = {}
        owners: dict[str, Step] = {}
        for prereq in prerequisites:
            artifacts = produced.get(prereq)
            if artifacts is None:
                continue
            for key, value in artifacts.items():
                first = owners.get(key)
                if first is not None:
                    named = f"two {Step.named(first)} instances" if Step.named(first) == Step.named(prereq) else f"{Step.named(first)} and {Step.named(prereq)}"
                    raise ValueError(
                        f"{Step.named(step)} reads `{key}` from two of its prerequisites - "
                        f"{named} both produced it. A merge would keep whichever landed later and the "
                        f"record would never say so, which is how a fan-in loses data without a trace. "
                        f"Namespace the keys (say `{Step.named(first).lower()}/{key}`) so the "
                        f"payload says who produced what."
                    )
                owners[key] = prereq
                payload[key] = value
        return payload

    def blocked(self, step: Step) -> bool:
        # The per-step gate. When the run has halted or a prerequisite failed, record WHY and answer
        # "skip it". The wave dispatchers ask through admit() instead.
        if self.__halt is not None:
            fate = self.__fates.get(self.__halt, _STOPPED)
            named = Step.named(self.__halt)
            # A decision to stop has no verb to speak, so it is named without one. halt() exists precisely
            # so a non-failure stop stops impersonating a failure. "Halted after X failed" was the last
            # place that lie survived.
            reason = f"after {named} {fate.clause}" if fate.clause else f"at {named}"
            self.__failures.append(DriftItem(Step.named(step), f"step skipped: the run halted {reason}"))
            return True
        culprits = self.__culprits.get(step)
        if culprits is None:
            return False
        # EVERY failure this step stands on, not the one that happened to fire first. Which of two
        # independent failures fires first is a fact about the Ordering, so naming only that one let the
        # same declaration with the same failures produce a different verdict under Kahn than under DFS.
        # Sorted by the declaration, so the sentence is a function of the world and of nothing else.
        named = ", ".join(Step.named(culprit) for culprit in sorted(culprits, key=self.__declared.__getitem__))
        noun = "prerequisite" if len(culprits) == 1 else "prerequisites"
        # The culprits' own fates decide the verb. They agree in every ordinary run, so the sentence a
        # thousand tests and one vault riddle already know is rendered byte for byte - and when they
        # disagree the neutral clause is the honest one, because no single verb is true of both.
        spoken = {self.__fates.get(culprit, _FAILED).clause for culprit in culprits}
        verb = spoken.pop() if len(spoken) == 1 else _UNCONFIRMED.clause
        self.__failures.append(DriftItem(Step.named(step), f"step blocked: {noun} {named} {verb}"))
        return True

    def admit(self, level: tuple[Step, ...]) -> tuple[Step, ...]:
        # The whole-WAVE gate. Report the blocked, hand back the rest to fan. Only correct for a wave,
        # where steps are mutually independent by construction, so a failure never blocks its wave-mates.
        return tuple(step for step in level if not self.blocked(step))

    def record(self, step: Step, produced: Changes, artifacts: Artifacts, exception: Fault | None) -> None:
        # The ONE raise-or-collect rule. The unit hook fires FIRST, before classification, so even the
        # failure FailFast is about to re-raise is the last thing the run traced - live progress that
        # never lies by omission.
        #
        # But the record is keyed by the run's OWN instances, guarded before anything is
        # written. A foreign step - most likely a deserialized clone a remote transport handed back -
        # would store artifacts under a key no dependency lookup ever reads, so the run would report
        # clean while its data-flow silently went missing. A proof that can lie by a boundary bug is
        # no proof, so the miss is loud. A remote dispatcher correlates at its own boundary and records
        # against the original its payload was built from (see tests/test_wire.py).
        if step not in self.__declared:
            raise ValueError(
                f"{Step.named(step)} is not a step of this run. The Ledger records by the run's own "
                f"instances, so a foreign step (a deserialized clone, say) would store artifacts nobody can "
                f"read and the run would report clean anyway. Correlate at the transport boundary and record "
                f"against the original the payload was built from."
            )
        self.__observer.stepped(step, produced, exception)
        if exception is not None:
            if isinstance(exception, Cancelled):
                raise exception   # an abort cuts through everything, including the two clauses below
            if isinstance(exception, Deferred):
                # A denial is DRIFT ABOUT THE WORLD, so it keeps out of the failures channel entirely.
                # Nothing broke, the pool was full and the sentence says exactly that. Its dependents are
                # still blocked, because a prerequisite that did not run left them nothing to stand on.
                # blocked() reads this fate, so their line says waited rather than failed.
                #
                # IT SITS ABOVE THE OnError CLAUSE ON PURPOSE, for the reason this record keeps
                # relearning. OnError is a policy about ERRORS and this is not one. Left below, a momentarily
                # full pool under the DEFAULT FailFast would abort the run and re-raise a BaseException out of
                # converge(), so a capacity limit would be indistinguishable from a crash for every caller who
                # never chose a policy. A denial is reported the same way whatever the policy, because there
                # is no failure for a failure policy to have an opinion about.
                #
                # WHICH RESTS ON A DENIAL REALLY MEANING THE WRITE NEVER RAN. That is guarded one layer
                # out rather than here. The permit is re-asked per attempt, so a pool that fills between two
                # tries once denied a write whose earlier attempt had already run and broken. This clause
                # then made the deferral its only fate - the RuntimeError discarded, the failures channel
                # empty and the sentence below claiming nothing broke. The attempt loop remembers a real
                # failure and re-raises THAT instead (see BaseRetry.around), so a Deferred arriving here
                # still carries the meaning this clause reads into it.
                self.__fates[step] = _DEFERRED
                self.__deferred.append(DriftItem(Step.named(step), f"step deferred: {exception}"))
                self.__blame(step)
                return
            if self.__on_error is OnError.FailFast:
                raise exception
            fate = _UNCONFIRMED if isinstance(exception, Skew) else _FAILED
            self.__fates[step] = fate
            self.__failures.append(DriftItem(Step.named(step), f"step {fate.verdict}: {exception.__class__.__name__}: {exception}"))
            if self.__on_error is OnError.Halt:
                self.__halt = step   # the run stands still: blocked() now skips every later step
            else:
                self.__blame(step)   # BestEffort: block only the failure's transitive dependents
        else:
            self.__artifacts[step] = artifacts   # a clean step's produce, kept for its dependents to read
            # The lineage seam. The attribution assemble() merges away for consumers is announced here,
            # per producer, as a read-only view of the very dict the dependents will read through.
            self.__observer.produced(step, MappingProxyType(artifacts))
            if produced:  # prune's residue (what survived) or converge's applied items - a no-op returns None
                self.__returns.extend(produced)

    def halt(self, culprit: Step) -> None:
        """Stand the run still, the way OnError.Halt does, for a reason that is NOT a failure.

        The stop-and-still-report path was reachable only through record() with an exception, so any other
        reason to stop - an error budget spent, a canary verdict, an operator pause - had to impersonate a
        failure to get there. That lie lands in the exact channel Idempotence and Isolation read as
        evidence: the record would say a step raised when nothing did. This sets the same field record()
        sets under Halt, so every later step is reported skipped naming the culprit and outcome() still
        returns the record, with no fabricated failure in it.

        Idempotent on purpose. A second reason to stop does not rewrite the first, because the run halted
        when it halted and the recap should name what actually stopped it."""
        if self.__halt is None:
            self.__halt = culprit

    def outcome(self) -> Statement:
        # The run's record, closed as one Statement. The do-returns, the failures and what each settled
        # step produced - which used to die right here, two lists leaving and the artifacts staying to be
        # garbage-collected with this Ledger.
        return Statement(self.__returns, self.__failures, self.__artifacts, self.__deferred)

    def __blame(self, failed: Step) -> None:
        # Mark every transitive dependent of the failed step as blocked by it, filling the culprits map.
        # A step downstream of two failures accumulates BOTH and blocked() names them in declaration
        # order. The walk is the RUN's own fallout(), the one home a counterfactual read shares - so what
        # a forecast predicts and what this records are the same set by construction, not by agreement.
        for dependent in self.__graph.fallout((failed,)):
            if dependent is not failed:
                self.__culprits.setdefault(dependent, []).append(failed)

