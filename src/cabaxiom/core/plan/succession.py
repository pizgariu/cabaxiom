"""Succession. What the dependency structure does when one declaration succeeds another - the four channels
of the derivation's delta and what the successor is left leaning on."""
from collections.abc import Iterable, Mapping, Sequence
from typing import final

from ..declaration.step import Step
from ..declaration.vocabulary import Vocabulary
from .graph import Declared, Graph, Match


@final
class Shift:
    """One declared name seen twice. The present steps it resolved to BEFORE and the ones it resolves to
    NOW. The unit every delta channel is made of, because a NAME is what the derivation actually looks up -
    an edge is only the trace a lookup leaves, so a lookup that found nothing leaves none.

    `gained` and `lost` are the two differences, which is what a reader wants. The instances this name
    reaches only now and the ones it no longer reaches. Reporting per name rather than per edge is also the
    only compression a fan-in needs, since fifty wanters against three providers is fifty Shifts and never a
    hundred and fifty edges.

    THE BEFORE SIDE MAY BE ABSENT. That is what a recognised survivor made expressible. Two declarations
    of one step used to be two views of ONE object, so every name was on both sides by construction. A step
    recognised by its identifier is a DIFFERENT object whose declaration is allowed to differ, so a name the
    successor is the first to declare has no predecessor at all. Its `was` is empty, which is the same answer
    a name that resolved to nothing gives, so both mean the coupling is new.

    Its identity reads off the AFTER side. A Shift is a finding about the successor's declaration, so `step`
    answers the step that is in the run now, never the predecessor it continues.

    A RECORD, like every value the kernel mints. It holds the Matches the derivations produced behind
    read-only properties, so a structural finding cannot be rewritten after the comparison that minted it.
    It carries step INSTANCES, not the per-instance labels Explanation and Indictment mint, because instance
    identity is the kernel's dependency addressing and a label tally spanning two declarations would need a
    numbering neither declaration owns."""

    __slots__ = ("__before", "__after", "__paired")

    def __init__(self, before: Match | None, after: Match, paired: Mapping[Step, Step]):
        self.__before = before
        self.__after = after
        # The correspondence, held so gained and lost can compare a rebuilt instance against the one it
        # continues. Without it every match of a recognised survivor reads as gained AND lost at once, since
        # the two sides hold different objects for the same concern and a fan-in that never moved would
        # report as having swapped its whole match set.
        self.__paired = paired

    @property
    def step(self) -> Step:
        return self.__after.step

    @property
    def slot(self) -> str:
        return self.__after.slot

    @property
    def name(self) -> Declared:
        return self.__after.name

    @property
    def soft(self) -> bool:
        return self.__after.soft

    @property
    def was(self) -> tuple[Step, ...]:
        return self.__before.matched if self.__before is not None else ()

    @property
    def now(self) -> tuple[Step, ...]:
        return self.__after.matched

    @property
    def gained(self) -> tuple[Step, ...]:
        # What this name reaches only after the change, in the new derivation's order. Read through the
        # correspondence, so a match that was merely rebuilt is not mistaken for a match that arrived.
        known = set(self.was)
        return tuple(step for step in self.now if self.__continues(step) not in known)

    @property
    def lost(self) -> tuple[Step, ...]:
        # What this name no longer reaches, in the old derivation's order.
        kept = {self.__continues(step) for step in self.now}
        return tuple(step for step in self.was if step not in kept)

    def __continues(self, step: Step) -> Step:
        return self.__paired.get(step, step)

    def __repr__(self) -> str:
        return (f"Shift({Step.named(self.step)}.{self.slot} {self.__after.label} "
                f"{len(self.was)} -> {len(self.now)})")


@final
class Rift:
    """The verdict of a succession check, over five channels. The one silent loss, the three ways structure
    moved and what the successor is left standing on.

    `quieted` is the silent class and the only channel that votes. A SOFT name (`expects`, `prepares`, `wants`, `uses`)
    of a step present in BOTH declarations that resolved to at least one instance before and resolves to
    nothing now. Its whole match set left with the leavers, so the edge goes quiet instead of failing. The
    hard flavours of the same loss are not here on purpose, since `requires` and `demands` raise through
    Graph.demand() the moment membership is final, so they are loud already, though they still appear under
    `standing` below.

    `materialised` is the opposite direction. A name that matched nothing before and matches something now.
    `widened` and `narrowed` are the middle. A name that matched and still matches, having gained or lost
    instances. A change that both takes and gives can put ONE name in both, a fan-in that swapped its only
    provider having gained one and lost one, so these two are DIRECTIONS, not a partition. They partition
    cleanly exactly when one declaration contains the other, which is the merge case.

    `standing` is one-sided and holds Matches, not Shifts. Every name of the successor matching nothing at
    all, whatever it matched before. It is what this declaration leans on the world to have already done,
    which is what a soft edge MEANS - information, not an accusation - and `quieted` is precisely the subset
    of it that used to be met.

    `estranged` is the sixth channel and it reports the READING rather than the world. It is non-empty only
    when NOT ONE step was recognised across the change while both declarations hold kinds in common, so it
    names those kinds. That is the shape a successor rebuilt from fresh unnamed objects takes. The
    direction it fails in is what earns it a channel. Nothing is recognised, so no name pairs, so every other
    channel comes back EMPTY and the verdict reads as a clean bill over a declaration whose every edge was in
    truth torn down and remade.

    A suspicion and not a certainty, in the spirit of a Severance, because a full swap of one instance of a
    kind for another is an ordinary transition and from two declarations alone the two are the same picture.
    That is also why ONE survivor silences it. A survivor anchors the comparison, while a provider swapped
    beside it is then reported honestly as a fan-in that both gained and lost. Two declarations sharing no
    kind are simply disjoint and an empty predecessor shares nothing either, so the assumption reading
    passes through unremarked. The fix it asks for is an `identifier` on the steps that persist, which is what lets
    a declaration built from data be recognised at all or the shared instances the older rule needs.

    `torn` is true when `quieted` or `estranged` is not empty, so a Rift is truthy exactly when torn, so it
    reads as the finding it is. The two vote for one reason. A quieted edge is an ordering promise the
    previous declaration kept and this one silently does not. An estrangement is that same condition with
    no bound on it and no way to say which edges. The other four never vote, since a new coupling, a wider
    fan-in, a thinner one and a standing lean are all structure moving exactly as declared."""

    __slots__ = ("__quieted", "__materialised", "__widened", "__narrowed", "__standing", "__estranged")

    def __init__(self, quieted: Sequence[Shift], materialised: Sequence[Shift], widened: Sequence[Shift],
                 narrowed: Sequence[Shift], standing: Sequence[Match], estranged: Sequence[type[Step]] = ()):
        self.__quieted = tuple(quieted)
        self.__materialised = tuple(materialised)
        self.__widened = tuple(widened)
        self.__narrowed = tuple(narrowed)
        self.__standing = tuple(standing)
        self.__estranged = tuple(estranged)

    @property
    def quieted(self) -> tuple[Shift, ...]:
        return self.__quieted

    @property
    def materialised(self) -> tuple[Shift, ...]:
        return self.__materialised

    @property
    def widened(self) -> tuple[Shift, ...]:
        return self.__widened

    @property
    def narrowed(self) -> tuple[Shift, ...]:
        return self.__narrowed

    @property
    def standing(self) -> tuple[Match, ...]:
        return self.__standing

    @property
    def estranged(self) -> tuple[type[Step], ...]:
        return self.__estranged

    @property
    def torn(self) -> bool:
        return bool(self.__quieted) or bool(self.__estranged)

    def __bool__(self) -> bool:
        return self.torn

    def __repr__(self) -> str:
        return (f"Rift(torn={self.torn}, quieted={len(self.quieted)}, materialised={len(self.materialised)}, "
                f"widened={len(self.widened)}, narrowed={len(self.narrowed)}, standing={len(self.standing)}, "
                f"estranged={len(self.estranged)})")


@final
class Succession:
    """Does the dependency structure carry over when one declaration succeeds another? Two derivations and
    no world. The only member of the proof family that touches nothing at all.

    Idempotence, Reversibility and Isolation all mint their verdicts by RUNNING, so they need a rehearsal
    world and their docstrings say so in capitals. This one reads structure and nothing else, so it runs in
    a pre-commit hook, in a review, in CI on a laptop, against production declarations, with no sandbox and
    no risk. That is the whole trade. It can prove less, yet it can prove it anywhere.

    It takes the same two declarations as a Transition, on purpose - Succession(previous, desired) is the
    pre-flight of Transition(previous, desired). It answers the question a Cutover cannot. A survivor's
    soft edge whose whole match set walked out with the leavers goes QUIET, so a quiet edge is not a
    failure. It is an ordering promise that stopped being kept. Nothing raises, nothing is logged, the run
    just stops waiting for something. Point it at (ours, ours + theirs) instead and the same read answers
    the merge question. Point it at ((), mine) and it answers what a declaration assumes the world provides.

    IDENTITY, AND THE TRAP THAT IS NOW A CHANNEL. Survivors are matched by `Step.paired`, which recognises a
    step by its own name where it has one and falls back to instance identity where it does not, so a
    declaration rebuilt from data is comparable at all and one written before identifiers existed compares exactly
    as it always did. The trap the old rule set is what the `estranged` channel now reports. A successor
    rebuilt from FRESH unnamed instances has no survivors, so no name pairs, so every channel comes back
    empty and the verdict reads as a clean bill over a declaration whose every edge was torn down and remade.
    Reporting it beat refusing it, because a full swap of one instance of a kind for another is an ordinary
    transition and from two declarations alone THE TWO ARE THE SAME PICTURE. So the two cases that are
    legitimately survivorless stay legal and unremarked, an empty predecessor and two genuinely disjoint
    sides, while the one shape that is usually a mistake is named rather than hidden.

    A NAME PAIRS BY WHAT IT SAYS. Two views of one object had the same names in the same order, so they used
    to pair positionally. A recognised survivor is a different object whose declaration may legitimately
    differ, a name added or a name dropped, so names now pair by slot and by what they name - and an
    instance-addressed name is read through the correspondence, which is what keeps `uses=(db,)` against a
    rebuilt db one name rather than a swap. A name the successor is the first to declare has no predecessor,
    and a name it dropped has no successor. The first materialises if it resolves. The second is silent
    on purpose, because an edge the author deleted is a decision and only an edge the author still believes
    in is a finding.

    There is NO open axis here and none is missing. Every question this asks is decided by the derivation
    itself, so a strategy seam would be ceremony. And no async twin, for the plainest reason in the kernel -
    colour comes from touching the world, which this never does."""

    def __init__(self, previous: Iterable[Step], desired: Iterable[Step],
                 vocabulary: Vocabulary | None = None):
        # Both derivations happen HERE, not in compare(). The Graph VETS every declaration as it derives, so
        # a value in the wrong slot raises at CONSTRUCTION, before a single question is asked. The kernel's
        # oldest discipline, free in a citizen that never touches a world to begin with. ONE vocabulary
        # for both sides - a delta read across two languages would classify nothing but the translation.
        self.__previous = tuple(previous)
        self.__desired = tuple(desired)
        self.__before = Graph(self.__previous, vocabulary)
        self.__after = Graph(self.__desired, vocabulary)
        # The correspondence comes from its one home, the same call Transition makes to pick its leavers, so a
        # pre-flight cannot disagree with the transition it precedes about which steps survive.
        self.__paired = Step.paired(self.__previous, self.__desired)
        self.__estranged = () if self.__paired else self.__unrecognised()

    def compare(self) -> Rift:
        # Walk the DESIRED declaration once, in its own order. A step in both declarations is a SURVIVOR and
        # has a structure on each side, so its names pair up and classify. A joiner is deliberately not
        # compared. Every name it has would read as materialised, which is true of the step and false of the
        # declaration. It is exactly what would wreck the merge reading, where a newcomer's own internal
        # edges are not couplings at all. Survivor or joiner, every desired step still contributes its
        # standing leanings.
        quieted: list[Shift] = []
        materialised: list[Shift] = []
        widened: list[Shift] = []
        narrowed: list[Shift] = []
        standing: list[Match] = []
        for step in self.__desired:
            declared = self.__after.matching(step)
            predecessor = self.__paired.get(step)
            if predecessor is not None:
                before = {self.__spoken(match): match for match in self.__before.matching(predecessor)}
                for now in declared:
                    shift = Shift(before.get(self.__spoken(now)), now, self.__paired)
                    if not now.matched:
                        if shift.was and now.soft:
                            quieted.append(shift)   # it resolved before, resolves to nothing now and nothing will say so
                    elif not shift.was:
                        materialised.append(shift)   # a name that reached nothing or that nobody declared, now reaches something
                    else:
                        if shift.gained:
                            widened.append(shift)    # the fan-in grew
                        if shift.lost:
                            narrowed.append(shift)   # the fan-in thinned but still resolves
            standing.extend(match for match in declared if not match.matched)
        return Rift(quieted, materialised, widened, narrowed, standing, self.__estranged)

    def __unrecognised(self) -> tuple[type[Step], ...]:
        # Asked only when NOTHING paired, which is the condition that makes a verdict unreadable rather than
        # merely thin. One survivor is enough to anchor the comparison, while a swap of one provider for another
        # beside a survivor is then reported honestly as a fan-in that gained and lost - so a per-kind version
        # of this check fired on an ordinary swap and had to go.
        #
        # The KINDS standing on both sides are what makes the difference between a suspicion and nothing to
        # say. A successor rebuilt from fresh unnamed instances holds the same kinds as its predecessor and
        # two declarations that share no kind are simply disjoint, which is a legal thing to compare and
        # answers what the second one leans on the world to provide. An empty predecessor shares nothing
        # either, so the assumption reading passes through unremarked.
        shared = {step.__class__ for step in self.__previous} & {step.__class__ for step in self.__desired}
        return tuple(sorted(shared, key=lambda kind: kind.__name__))

    def __spoken(self, match: Match) -> tuple[str, object]:
        # What a declared name IS, in terms both declarations share, so the two sides key against each other
        # rather than against their own list positions. A class or a capability speaks for itself. An INSTANCE
        # is translated to the predecessor it continues, which is the whole reason `uses=(db,)` survives a
        # rebuilt db, while a joiner translates to itself and so pairs with nothing.
        name = match.name
        return match.slot, self.__paired.get(name, name) if isinstance(name, Step) else name
