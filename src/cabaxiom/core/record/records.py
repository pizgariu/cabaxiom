"""The immutable verdicts the kernel mints - the Residual a run returns, the Explanation of what it
resolved and the Casualty a failure would cost. Lifted out of reconciler.py so the engine module holds
the operational verbs and this one holds the frozen records they hand back - and imported straight back
into the engine, so a Reconciler still returns exactly these."""
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import final

from ..declaration.drift import Artifacts, Drift
from ..declaration.errors import Unresolvable
from ..declaration.held import _Held
from ..declaration.step import Step
from ..declaration.vocabulary import EdgeKind
from .diagram import Dot, Mermaid
from .ledger import Statement

# ONE RESOLVED EDGE AS AN EXPLANATION CARRIES IT - the dependent's label, the prerequisite's label and the
# declaration slot that drew it. A Diagram walks these to draw arrows, a caller reads them to see why an
# order came out as it did. Named so neither side counts positions.
type Arrow = tuple[str, str, str]


@final
class Residual(_Held[Drift]):
    """What converge() and prune() return - the run's residual as a FROZEN sequence (empty == verified
    success), carrying its channels apart instead of encoding them into message prefixes.

    The sequence view is the whole proof set, so callers that test truthiness, iterate, index or compare
    against a plain list behave unchanged - equality is by items against any sequence, which is what keeps
    `assertEqual(residual, [])` the assertion it always was. `failures` is THIS run's failure records (the
    dispatcher's own channel - `step failed`, `step blocked`, `step skipped`), told apart from the re-probe
    findings that make up the rest of the view - a consumer used to have to parse a message prefix to ask
    "did anything break or is the world merely still drifting". `applied` records what apply() changed
    the transaction summary the residual cannot give.

    A RECORD, like every other value the kernel mints. It was the LAST one that was still mutable. A returned
    proof accepted append(), its applied channel accepted writes and a slice silently dropped the channel
    - so a verdict could be falsified by the caller's own hand after the run that minted it. Every channel
    is a tuple behind a read-only property now, slicing hands back a plain tuple (the channels stay with
    the run that produced them). What was true when the run ended stays true."""

    __slots__ = ("__failures", "__vetoed", "__applied", "__produced")

    def __init__(self, residual: Sequence[Drift], *, failures: Sequence[Drift] = (), applied: Sequence[Drift] = (), produced: Mapping[Step, Artifacts] | None = None,
                 vetoed: Sequence[Drift] = ()):
        super().__init__(residual)
        self.__failures = tuple(failures)
        self.__vetoed = tuple(vetoed)
        self.__applied = tuple(applied)
        self.__produced = {step: dict(artifacts) for step, artifacts in (produced or {}).items()}

    # THE FOUR VERDICTS A RUN CAN CLOSE ON, each minted by the factory named for it. The constructor stays
    # public and unchanged, so every caller and every test that builds a Residual by hand keeps working. What
    # the factories take away is the knowledge a caller had to carry - which channel a refusal rides beside,
    # that failures stay empty when nothing broke, that a teardown's proof is the residue itself. Four
    # sites in the reconciler each spelled one of those rules out in a ten-line comment. Each rule is said
    # once here, so a site that mints the wrong verdict now reads wrong at a glance.

    @classmethod
    def refused(cls, reasons: Sequence[Drift], *, beside: Sequence[Drift], produced: Mapping[Step, Artifacts]) -> "Residual":
        # A WARRANT SAID NO before anything was written. The reasons ride in the sequence view beside the
        # channel THIS verb's residual is made of - a converge's deviations, a teardown's footprint - so a
        # refused run cannot read as verified, while `vetoed` keeps them apart so no caller reads a policy
        # decision as a crash. Nothing broke and nothing was applied, so both of those channels stay empty.
        return cls([*reasons, *beside], vetoed=reasons, produced=produced)

    @classmethod
    def converged(cls, residual: Sequence[Drift], *, failures: Sequence[Drift], applied: Sequence[Drift],
                  produced: Mapping[Step, Artifacts] | None) -> "Residual":
        # A CONVERGE RAN TO ITS POLICY'S END. The sequence is whatever the convergence policy handed back as
        # the final residual, the failures are the last cycle's own and `applied` is the diary of every pass.
        return cls(residual, failures=failures, applied=applied, produced=produced)

    @classmethod
    def pruned(cls, statement: Statement) -> "Residual":
        # A TEARDOWN RAN. The residue each prune() returned (what SURVIVED) concatenated with the dispatcher's
        # own failures and deferrals is the whole proof set. There is no re-assessment channel on purpose -
        # a read after a teardown measures deviation from a world that should EXIST, so it would report a
        # successful teardown as everything being missing. The survived residue IS the proof. The order
        # of the three groups inside it does not matter, since it is a (name, message) proof set.
        return cls([*statement.returns, *statement.failures, *statement.deferred], failures=statement.failures, produced=statement.produced)

    @property
    def vetoed(self) -> tuple[Drift, ...]:
        # Why a Warrant refused to let this run write, non-empty ONLY when one did. Kept apart from failures
        # because nothing broke and apart from the deviations because the world drifting and a policy
        # refusing are two different facts and a caller acts differently on each. Its items ride in the
        # sequence view too, so a refused run cannot read as verified.
        return self.__vetoed

    @property
    def failures(self) -> tuple[Drift, ...]:
        return self.__failures

    @property
    def produced(self) -> Mapping[Step, Artifacts]:
        # What each settled step produced, keyed by instance - a PHOTOGRAPH of the run's final pass, never
        # an accumulator. Artifacts are level-triggered like everything else here. A clean no-op re-apply
        # returns the same artifacts it would have produced fresh, so the last pass's map is complete for
        # every step that settled, so a step that failed or was blocked in that pass is honestly absent,
        # agreeing with the failures channel instead of contradicting it. (`applied` accumulates and this
        # does not, on purpose. applied is a diary and a diary accumulates, produced is a photograph and a
        # photograph is retaken.) Copied at construction, exposed read-only - what was true when the run
        # ended stays true.
        return MappingProxyType(self.__produced)

    @property
    def applied(self) -> tuple[Drift, ...]:
        return self.__applied

    def __repr__(self) -> str:
        return f"Residual({list(self._held)!r}, failures={self.__failures!r}, applied={self.__applied!r})"


@final
class _Declared(dict[str, tuple[tuple[str, tuple[str, ...]], ...]]):
    # A slot this run does not carry is refused BY NAME, since CPython's KeyError repeats the key back and
    # names nothing else. Every slot the vocabulary knows is present here, empty when no step wrote it, so a
    # key that misses is a typo or a slot that does not exist rather than a run that happened not to use it.
    def __missing__(self, slot: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
        raise Unresolvable(
            f"{slot} is not a declaration slot. This run carries {', '.join(sorted(self))}. A slot no step "
            f"wrote is present and empty rather than absent, so a miss here is the name and not the run."
        )


@final
class Explanation:
    """What the Reconciler resolved, surfaced read-only. The groups the dispatcher walks in run order, the
    resolved dependency edges behind that order plus the declarations that produced them.

    `groups` is the resolved run structure, each inner tuple one group of step labels - a wave (independent
    within, sequential between) under a level dispatcher or a chain (sequential within, concurrent between)
    under a chain fanner. Labels are PER INSTANCE: a kind's first instance keeps the bare type name and later
    ones are numbered in run order (`Directory`, `Directory#2`), so a duplicate-free run reads exactly as
    type names while two instances of one kind never collide.

    `dependencies` is the run's edge mapping, read off the Graph the resolution derived, so it is total by
    construction: every edge kind the vocabulary declares (or ever grows) appears here, resolved to present
    instances - the arrows behind the group order and the mapping an exporter overlays on the groups.
    `declared` then says WHY each arrow exists: ONE mapping keyed by declaration slot, each entry pairing a
    step label with the names it declares there, sparse (a step declaring nothing in a slot is omitted) and
    in run order. Its keys are the vocabulary's own slots plus `provides` and `contends`, the declarations
    the vocabulary does not drive - so when the vocabulary grows an edge kind, this read carries it with no
    new field, where six fields fixed by name used to make every new kind a signature change. This is
    exactly the partition assess() and converge() walk, so it explains the real run and re-resolves nothing.

    A RECORD, like every value the kernel mints. The fields are already tuples all the way down and the
    read-only properties over private slots keep a reader from reassigning what a run resolved.
    """

    __slots__ = ("__groups", "__shape", "__arrows", "__declared", "__vocabulary")

    def __init__(self, groups: tuple[tuple[str, ...], ...], *,
                 shape: str,
                 arrows: tuple[Arrow, ...],
                 declared: Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]],
                 vocabulary: tuple[EdgeKind, ...]):
        self.__groups = groups
        self.__shape = shape
        self.__arrows = arrows
        self.__declared = MappingProxyType(_Declared(declared))   # a read-only view, frozen like every channel
        self.__vocabulary = vocabulary

    @property
    def groups(self) -> tuple[tuple[str, ...], ...]:
        return self.__groups

    @property
    def shape(self) -> str:
        # The run shape's own noun for ONE group, straight off the Partition the resolution built: "wave"
        # when the group members run at once, "chain" when they run in series. It is what makes a drawn
        # group readable, since the same tuple of labels means opposite things under the two fans.
        return self.__shape

    @property
    def arrows(self) -> tuple[Arrow, ...]:
        # Every arrow the resolution LANDED, as (dependent, prerequisite, slot) in run order - the edge
        # view with its cause attached, read off the Graph's per-name matching so nothing here is
        # re-derived and already ORIENTED - a `precedes` kind lands with its declarer on the prerequisite
        # side. Deliberately NOT deduplicated, exactly as matching() is not. A prerequisite reached
        # by both `expects` and `wants` is two declarations that both landed, so collapsing them would
        # hide one. A declaration that matched NOTHING contributes no arrow, which is the difference
        # between this and the declaration mappings below.
        return self.__arrows

    @property
    def dependencies(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        # The resolved edges per step, in run order, duplicates collapsed - a PROJECTION of the arrows
        # above rather than a second stored field. Storing both would be two views of one fact that
        # nothing kept in agreement, a shape this kernel has paid for before.
        gathered: dict[str, dict[str, None]] = {}
        for dependent, prerequisite, _slot in self.__arrows:
            gathered.setdefault(dependent, {})[prerequisite] = None
        return tuple((dependent, tuple(prerequisites)) for dependent, prerequisites in gathered.items())

    @property
    def vocabulary(self) -> tuple[EdgeKind, ...]:
        # The kinds this run SPOKE, riding with the reading so a drawing styles a custom kind's arrows
        # without ever being handed a second vocabulary that could disagree with the derivation's.
        return self.__vocabulary

    @property
    def declared(self) -> Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]]:
        # The declarations behind the arrows, keyed by slot - the vocabulary's kinds plus `provides` and
        # `contends`. One mapping instead of fields fixed by name, so a grown vocabulary reads through
        # unchanged.
        return self.__declared

    @property
    def contention(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        # Which resources are contended and by whom - the reason two steps were seated apart. Keyed by
        # RESOURCE rather than by step, since the constraint belongs to the resource and a reader arrives
        # asking "what is holding these two apart". A PROJECTION of declared["contends"], exactly as
        # dependencies projects arrows - one fact, one home. Sparse in the way that matters. A label only
        # ONE step names constrains nothing, so it is left out, because a declaration that reads as a
        # constraint while constraining nothing is the kind of half-truth this record exists to avoid.
        named: dict[str, list[str]] = {}
        for label, resources in self.__declared.get("contends", ()):
            for resource in resources:
                named.setdefault(resource, []).append(label)
        return tuple((resource, tuple(holders)) for resource, holders in named.items() if len(holders) > 1)

    def dot(self, marks: Mapping[str, str] | None = None) -> str:
        """This run as a Graphviz DOT digraph, ready for `dot -Tsvg`.

        The convenience for the shipped Dot format. `marks` paints a run's state onto it, a mapping of
        label to `failed`, `blocked`, `skipped` or `settling` - a Casualty hands its own straight over.
        Reach for `Dot(...).render(self)` when the palette needs changing or write your own Diagram."""
        return Dot().render(self, marks)

    def mermaid(self, marks: Mapping[str, str] | None = None) -> str:
        """This run as a Mermaid flowchart, ready to paste into any Markdown that renders Mermaid.

        The same reading as dot(), in the format a README or a pull request displays inline."""
        return Mermaid().render(self, marks)

    def __repr__(self) -> str:
        # One line. Each group a parenthesised set of labels, the groups joined in run order.
        flow = " -> ".join("(" + ", ".join(group) + ")" for group in self.groups) or "()"
        return f"Explanation({flow})"


@final
class Casualty:
    """What ONE step's failure would cost this run, read before anything runs - explain()'s counterfactual.

    `blocked` is the BestEffort answer - the failure's transitive dependents, each of which would be reported
    `step blocked` instead of running, because a step whose prerequisite failed would otherwise converge
    against state nobody put there. It is not a simulation - it is the Graph's `fallout()`, the same walk the
    Ledger runs when it actually blames a failure, so the forecast cannot drift from the handling.

    `skipped` and `settling` are the Halt answer. Halt is deliberately split in two because it is NOT a
    property of the graph. Halt stops the run by RUN POSITION, so what survives depends on the shape the
    dispatcher walks. `skipped` is every step in a strictly later group, which no dispatcher can start once
    the run has halted, while `settling` is the failure's own group-mates, which are indeterminate - a
    fanning dispatcher admitted the whole group at once so they settle.

    `starves` is a severity note, not a further casualty. It lists the capabilities this step is the only
    present provider of. Every step wanting one of them already stands in `blocked` (a capability edge fans
    to every provider, so they all depend on it), yet a FUTURE declaration missing this step would fail
    differently. A `demands` on a starved capability raises at resolution, while a `wants` goes quiet.

    `contained` is true when nothing else would be blocked, so a Casualty is truthy when it is NOT, so it
    reads as the finding it is."""

    __slots__ = ("__failed", "__blocked", "__skipped", "__settling", "__starves")

    def __init__(self, failed: str, blocked: Sequence[str], skipped: Sequence[str],
                 settling: Sequence[str], starves: Sequence[str]):
        self.__failed = failed
        self.__blocked = tuple(blocked)
        self.__skipped = tuple(skipped)
        self.__settling = tuple(settling)
        self.__starves = tuple(starves)

    @property
    def failed(self) -> str:
        return self.__failed

    @property
    def blocked(self) -> tuple[str, ...]:
        return self.__blocked

    @property
    def skipped(self) -> tuple[str, ...]:
        return self.__skipped

    @property
    def settling(self) -> tuple[str, ...]:
        return self.__settling

    @property
    def starves(self) -> tuple[str, ...]:
        return self.__starves

    @property
    def marks(self) -> dict[str, str]:
        # Each affected label paired with WHAT would happen to it, the four channels above flattened into
        # one per-step reading. A drawing paints straight from this, so a picture of a forecast and the
        # forecast itself are one value seen twice rather than two that could disagree. A label absent
        # here is a step this failure does not touch, which is the same thing as saying a recovery may
        # stand on it.
        painted = {self.__failed: "failed"}
        for label in self.__skipped:
            painted[label] = "skipped"
        for label in self.__settling:
            painted[label] = "settling"
        for label in self.__blocked:
            painted[label] = "blocked"   # last, since a blocked step is the sharper reading of a skipped one
        return painted

    @property
    def contained(self) -> bool:
        return not self.__blocked

    def __bool__(self) -> bool:
        return bool(self.__blocked)

    def __repr__(self) -> str:
        return (f"Casualty({self.__failed}: blocked={len(self.__blocked)}, skipped={len(self.__skipped)}, "
                f"settling={len(self.__settling)}, starves={len(self.__starves)})")


