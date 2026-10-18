"""Enclosure. Does nesting reconcilers silently void a declared ordering? The fractal claim's own guard."""
from collections.abc import Sequence
from typing import final

from ..declaration.step import Step
from ..plan.graph import Graph, Match
from .enclave import Enclave
from .fanout import Fanout
from .reconciler import Reconciler


@final
class Severed:
    """One ordering intent an enclave boundary voids.

    `leaner` declared `named` in `slot` and `resolver` is a step that would answer it - but they sit at
    different levels of the tree, so the leaner's own Graph never saw the resolver and the edge resolved to
    nothing there. Both labels are qualified by their level path, so a reader can find them.

    `boundary` and `against` are the two steps that stand for them at their deepest common level. The fix is
    always to order `boundary` after `against` there, which is why they are reported rather than left to be
    worked out. `inverted` is the sharper finding - the common level orders them the OTHER way, so the
    intent is not merely unguarded, it is contradicted.

    A RECORD, like every value the kernel mints - read-only properties over private slots."""

    __slots__ = ("__leaner", "__slot", "__named", "__resolver", "__boundary", "__against", "__inverted")

    def __init__(self, leaner: str, slot: str, named: str, resolver: str,
                 boundary: str, against: str, inverted: bool):
        self.__leaner = leaner
        self.__slot = slot
        self.__named = named
        self.__resolver = resolver
        self.__boundary = boundary
        self.__against = against
        self.__inverted = inverted

    @property
    def leaner(self) -> str:
        return self.__leaner

    @property
    def slot(self) -> str:
        return self.__slot

    @property
    def named(self) -> str:
        return self.__named

    @property
    def resolver(self) -> str:
        return self.__resolver

    @property
    def boundary(self) -> str:
        return self.__boundary

    @property
    def against(self) -> str:
        return self.__against

    @property
    def inverted(self) -> bool:
        return self.__inverted

    def __repr__(self) -> str:
        how = "ordered the other way" if self.__inverted else "unordered"
        return (f"Severed({self.__leaner}.{self.__slot} {self.__named} -> {self.__resolver}, "
                f"{self.__boundary} {how} against {self.__against})")


@final
class Severance:
    """The fractal soundness verdict. Airtight exactly when severed is empty.

    Each `Severed` is an ordering a step declared and the nesting does not honour. `inverted` is the subset
    where the common level actively orders the pair the wrong way round, which is the sharper reading of the
    same structure. `boundaries` counts the enclave levels walked, so a caller can tell an airtight tree from
    a tree with nothing to check."""

    __slots__ = ("__severed", "__boundaries")

    def __init__(self, severed: Sequence[Severed], boundaries: int):
        self.__severed = tuple(severed)
        self.__boundaries = boundaries

    @property
    def severed(self) -> tuple[Severed, ...]:
        return self.__severed

    @property
    def inverted(self) -> tuple[Severed, ...]:
        # The sharper subset. Not merely unguarded, yet ordered against the declared intent.
        return tuple(cut for cut in self.__severed if cut.inverted)

    @property
    def boundaries(self) -> int:
        return self.__boundaries

    @property
    def airtight(self) -> bool:
        return not self.__severed

    def __bool__(self) -> bool:
        # Truthy when something was cut, the Indictment polarity - this verdict reports a finding.
        return bool(self.__severed)

    def __repr__(self) -> str:
        return (f"Severance(airtight={self.airtight}, severed={len(self.__severed)}, "
                f"inverted={len(self.inverted)}, boundaries={self.__boundaries})")


@final
class Enclosure:
    """Does the nesting honour what the steps inside it declared? The guard the fractal claim never had.

    An Enclave is a whole reconciler joining a parent run as ONE step, so each reconciler derives its Graph
    over its OWN selection. So a step inside an enclave that declares `expects = (Network,)` while the Network
    lives in the parent gets a dead end. Derivation is total, an absent name is trusted to the world and
    nothing raises. The parent, meanwhile, orders the enclave only by the ENCLAVE's own declarations. The
    inner step can genuinely run before Network converges, the author's intent is voided without a sound,
    and neither level's explain() can see it, because every existing read is scoped to one reconciler's
    selection by design. Enclosure asks the cross-level question no verb asks.

    It walks the tree through the Enclave seam. For every declared name of every step it finds the
    steps that would answer it at OTHER levels. Note the "every", not "every unresolved": a name that
    matches one instance locally AND another instance a level up is exactly as unguarded on the second one,
    and only counting names that matched NOTHING would miss it. For each such pair it asks the deepest
    common level whether the resolver's representative precedes the leaner's. Ordered means the intent
    survives the boundary, because an Enclave's apply() is the whole inner converge, so an enclave ordered
    first has finished entirely before the other one starts.

    Pure structure. It derives nothing, runs nothing and touches no world - the reconcilers handed to it
    already resolved theirs at construction, which is also why a cycle or a missing hard edge has already
    raised long before this is asked. Sync and async trees alike, since neither colour reaches structure.

    SEVERED IS A SUSPICION, NOT AN ERROR. An enclave may genuinely trust the outer world to have converged
    on its own schedule, for instance under a watch() loop converging the parent until clean. That reads as
    severed here. Empty is a proof the nesting is airtight. Non-empty is a list to be read, plus the fix,
    when there is one, is always the boundary edge the record names."""

    def __init__(self, top: Reconciler) -> None:
        # The whole tree is walked HERE, so a tree with nothing to check is refused at construction rather
        # than answered with a vacuous airtight - the Itinerary precedent, where a path of one waypoint is
        # not a path. Everything read is the subclass contract the reconcilers call deliberately stable.
        self.__steps: dict[tuple[str, ...], tuple[Step, ...]] = {}
        self.__graphs: dict[tuple[str, ...], Graph] = {}
        self.__at: dict[Step, tuple[str, ...]] = {}
        self.__labels: dict[Step, str] = {}
        self.__owner: dict[tuple[str, ...], Step] = {}
        self.__fanned: list[str] = []
        self.__walk(top, ())
        if len(self.__steps) < 2:
            # A fanout is a boundary this reader genuinely cannot cross, so it is named rather than walked
            # past. Its inner graph does not exist until a verb runs and is a different graph on the next
            # pass, so any verdict about it would describe a run nobody will make - and reporting airtight
            # over an unread boundary is the one answer worse than refusing.
            fanned = (f" The tree does hold a fanout ({', '.join(self.__fanned)}), whose inner graph is "
                      f"built per pass, so there is nothing standing to read. Nesting a fanout inside an "
                      f"Enclave puts the boundary somewhere this can see." if self.__fanned else "")
            raise ValueError(
                "Enclosure needs a tree with at least one Enclave. A flat reconciler has no boundary that "
                f"could void an ordering, so the question does not arise.{fanned}"
            )

    # noinspection PyProtectedMember
    def __walk(self, reconciler: Reconciler, path: tuple[str, ...]) -> None:
        # Depth-first through the Enclave seam. Labels are per level and per instance, the Explanation
        # scheme (a kind's first instance keeps the bare name, later ones are numbered), then qualified by
        # the path so two enclaves of one kind cannot collide across the tree.
        steps = tuple(step for group in reconciler._partition for step in group)
        self.__steps[path] = steps
        self.__graphs[path] = reconciler._graph
        # The numbering rule comes from its one home - this copied it a third time, so a copied rule is
        # a rule that can drift. What is Enclosure's OWN business is the PATH prefix, since a name here
        # must say which level it was read at.
        for step, label in Step.labelled(steps).items():
            self.__at[step] = path
            self.__labels[step] = "/".join((*path, label))
            if isinstance(step, Fanout):
                self.__fanned.append(self.__labels[step])
            if isinstance(step, Enclave):
                below = (*path, label)
                self.__owner[below] = step
                self.__walk(step._reconciler, below)

    def __elsewhere(self, declared: Match, path: tuple[str, ...]) -> tuple[Step, ...]:
        # Every step in the WHOLE tree that would answer this name, minus the ones at the leaner's own
        # level, which its Graph already resolved (or already knows it did not).
        name = declared.name
        answering: list[Step] = []
        for step in self.__at:
            if self.__at[step] == path:
                continue
            if isinstance(name, str):
                if name in step.provides:
                    answering.append(step)
            elif isinstance(name, type):
                if type(step) is name:
                    answering.append(step)
            elif step is name:
                answering.append(step)
        return tuple(answering)

    def __representative(self, step: Step, common: tuple[str, ...]) -> Step:
        # The step at the common level that stands for this one. Itself when it lives there, otherwise the
        # enclave on its path that the common level actually holds.
        path = self.__at[step]
        if path == common:
            return step
        return self.__owner[path[: len(common) + 1]]

    def prove(self) -> Severance:
        # For every cross-level pair, ask the deepest common level whether the order survives the boundary.
        # closure() walks PREREQUISITES, so the resolver's representative being inside the leaner's closure
        # means it converges first, which is the intent honoured. The reverse containment is the inverted
        # case. Neither means the boundary simply does not order them.
        severed: list[Severed] = []
        for path, steps in self.__steps.items():
            graph = self.__graphs[path]
            for step in steps:
                for declared in graph.matching(step):
                    for resolver in self.__elsewhere(declared, path):
                        # The deepest level holding both is the longest shared prefix of the two paths.
                        where = self.__at[resolver]
                        depth = 0
                        while depth < min(len(path), len(where)) and path[depth] == where[depth]:
                            depth += 1
                        common = path[:depth]
                        leaning = self.__representative(step, common)
                        answering = self.__representative(resolver, common)
                        # WHICH way the declaration points is the KIND's answer, never a second spelling
                        # here - an ordinary kind puts the declaring step after what it named, a `precedes`
                        # kind reverses it. Assuming the first meant this reader certified a genuinely
                        # broken tree airtight and levelled its sharpest accusation at a sound one, which
                        # is the exact inverse of the one job it has.
                        first, second = ((answering, leaning) if declared.kind.precedes
                                         else (leaning, answering))
                        above = self.__graphs[common]
                        if second in above.closure((first,)):
                            continue                      # the intent survives the boundary
                        inverted = first in above.closure((second,))
                        severed.append(Severed(
                            self.__labels[step], declared.slot, declared.label, self.__labels[resolver],
                            self.__labels[leaning], self.__labels[answering], inverted,
                        ))
        return Severance(severed, len(self.__steps) - 1)
