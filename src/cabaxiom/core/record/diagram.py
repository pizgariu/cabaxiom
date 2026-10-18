"""Diagram - HOW a resolved run becomes a drawing. Graphviz DOT, Mermaid or a format of your own."""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from itertools import combinations
from typing import TYPE_CHECKING, NamedTuple, final, override

from ..declaration.vocabulary import EdgeKind, Vocabulary

if TYPE_CHECKING:
    from .records import Explanation


@final
class Tone(NamedTuple):
    # How ONE mark is painted, said once per language: DOT node attributes and a Mermaid classDef body.
    # A mark is a plain word (`failed`, `blocked`), so the vocabulary a caller marks with stays free of
    # colours, while the palette that turns those words into paint is the diagram's business alone.
    dot: str
    mermaid: str

    @classmethod
    def speaking(cls, kind: EdgeKind) -> "Tone":
        # How ONE edge kind is drawn, derived from what the kind IS rather than listed beside it. A hard
        # edge is bold (the resolution enforces it), a soft INDIRECT lean is dashed (it reaches its steps
        # through providers and trusts the world for them). Everything else is a plain arrow. The
        # kind's own colour rides through. The vocabulary knows no drawing syntax and the walk knows no
        # slot names, which is the seam the registry cut.
        if kind.hard:
            return cls(f'color="{kind.colour}", penwidth=2', "==>")
        if kind.addressing.indirect:
            return cls(f'color="{kind.colour}", style=dashed', "-.->")
        return cls(f'color="{kind.colour}"', "-->")


# The shipped palette, keyed by the words a run's own values already use. `failed` is the culprit, `blocked`
# every step that would not run because a prerequisite failed, `skipped` what a halt never starts and
# `settling` the failure's own group-mates, which are indeterminate by shape rather than doomed. Anything
# unmarked is untouched by the failure, which is the same thing as saying a recovery may stand on it.
PALETTE: Mapping[str, Tone] = {
    "failed": Tone('fillcolor="#ffc9c9", color="#e03131", style="rounded,filled", penwidth=2',
                   "fill:#ffc9c9,stroke:#e03131,stroke-width:2px,color:#5c0000"),
    "blocked": Tone('fillcolor="#ffd8a8", color="#e8590c", style="rounded,filled"',
                    "fill:#ffd8a8,stroke:#e8590c,color:#5c2600"),
    "skipped": Tone('fillcolor="#e9ecef", color="#868e96", style="rounded,filled"',
                    "fill:#e9ecef,stroke:#868e96,color:#343a40"),
    "settling": Tone('fillcolor="#ffec99", color="#f08c00", style="rounded,filled"',
                     "fill:#ffec99,stroke:#f08c00,color:#5c3d00"),
}


# The default language's tones, kept as the reference palette a reader or a test consults - the walk
# itself tones each run from the run's OWN vocabulary, so this table is documentation of the default
# language, never the styling authority.
STYLING: Mapping[str, Tone] = {kind.slot: Tone.speaking(kind) for kind in Vocabulary.shipped()}


class Diagram(ABC):
    """The open axis for HOW a resolved run becomes a drawing. Subclass it, implement four small seams and
    render any Explanation your own way - the kernel ships Dot and Mermaid on exactly this base.

    render() is CONCRETE and owns the WALK, which is the whole point of the axis existing. Which nodes there
    are, which group each sits in, what identity each is given and in what order the arrows come are facts
    about the RUN, not about a file format, so they are settled once here and no format can answer them
    differently. What genuinely differs between DOT and Mermaid is syntax and syntax is the four seams.

    Node identity is POSITIONAL, minted here for every format. A label carries punctuation the diagram
    languages refuse (`Directory#2`), so squeezing that punctuation into underscores is how two distinct
    steps quietly become one node, since `Api#2` and `Api_2` are different runs and the same id. Counting
    cannot collide, while the real label rides as the node's displayed text where it belongs.

    A drawing is READ-ONLY tooling over what explain() already resolved. Nothing here re-derives an edge or
    re-resolves an order, so a picture that disagreed with its run would mean explain() disagreed with it.

    `marks` paints a run's state onto the drawing - a mapping of label to a plain word this diagram's palette
    knows (`failed`, `blocked`, `skipped`, `settling`). A Casualty hands its own straight over, so a failure
    forecast reads as colour, so an unmarked node is exactly a node a recovery may stand on."""

    def __init__(self, tones: Mapping[str, Tone] | None = None):
        # The palette is composed, not hardcoded, so a domain repaints the shipped words or adds its own
        # vocabulary without touching the walk. Resolved via None so no shared default leaks across
        # instances, the kernel's rule for every injected default.
        self._tones = dict(PALETTE if tones is None else tones)

    @final
    def render(self, explanation: "Explanation", marks: Mapping[str, str] | None = None) -> str:
        painted = {} if marks is None else marks
        identity = {label: f"n{position}" for position, label
                    in enumerate(label for group in explanation.groups for label in group)}
        # The arrows are toned from the RUN's own vocabulary, not from a table frozen at import. The
        # reading says which kinds it spoke, so a grown kind arrives already styled and a format never
        # holds a second vocabulary that could disagree with the derivation's.
        tones = {kind.slot: Tone.speaking(kind) for kind in explanation.vocabulary}
        lines = list(self.opening())
        for index, group in enumerate(explanation.groups):
            members = tuple((identity[label], label, painted.get(label)) for label in group)
            lines.extend(self.grouped(f"{explanation.shape} {index}", index, members))
        for dependent, prerequisite, slot in explanation.arrows:
            lines.append(self.arrow(identity[prerequisite], identity[dependent], slot, tones[slot]))
        # Contention, drawn as what it is - a LINK, not an arrow. Every pair, because every pair of
        # contenders genuinely excludes the other and a chain of consecutive links would claim the ends do
        # not - which is the sort of convenient half-truth the whole plane exists to refuse. A format that
        # says nothing here draws nothing, since a drawing that is silent about a constraint is honest in a
        # way that a directed arrow standing in for an undirected one would not be.
        for resource, holders in explanation.contention:
            for first, other in combinations(holders, 2):
                drawn = self.contended(identity[first], identity[other], resource)
                if drawn:
                    lines.append(drawn)
        used = tuple(dict.fromkeys(mark for mark in painted.values() if mark in self._tones))
        lines.extend(self.closing(used))
        return "\n".join(lines)

    @abstractmethod
    def opening(self) -> tuple[str, ...]:
        # The document's first lines - the graph declaration and whatever defaults this format sets once.
        ...

    @abstractmethod
    def grouped(self, title: str, index: int, members: tuple[tuple[str, str, str | None], ...]) -> tuple[str, ...]:
        # ONE group of the run as a cluster. Its title is the shape's own noun plus the index (`wave 0`
        # runs at once, `chain 0` runs in series), with each member being (node id, displayed label, mark or
        # None). Emit the cluster and the nodes inside it.
        ...

    @abstractmethod
    def arrow(self, prerequisite: str, dependent: str, slot: str, tone: Tone) -> str:
        # ONE landed arrow, drawn in run order - the prerequisite's node id, the dependent's, the
        # declaration slot that produced the edge plus the tone the walk derived for that slot from the
        # run's own vocabulary - handed in, so a format renders a kind it has never heard of.
        ...

    def contended(self, one: str, other: str, resource: str) -> str:
        """ONE pair of steps that may never run at the same time plus the resource that holds them apart.

        Undirected on purpose, which is why it is not arrow(). An arrow says one thing runs before another
        and this says neither may run BESIDE the other, in any order - drawing it with a head would put back
        exactly the false dependency `contends` exists to avoid, this time in the picture rather than in the
        derivation.

        DEFAULTED, unlike the four seams above. The default draws nothing. Those four are abstract
        because a format that cannot do them is not a diagram. This one is different. A format may have no
        syntax for an undirected link at all, so a drawing that stays silent about a constraint tells no
        lie, where one that borrowed an arrow would. It also keeps every Diagram written before this release
        working untouched, which is what a defaulted hook on an open axis is for."""
        return ""

    @abstractmethod
    def closing(self, used: tuple[str, ...]) -> tuple[str, ...]:
        # The document's last lines, handed exactly the marks this drawing actually used, so a format that
        # declares its classes up front (Mermaid) emits only the ones in play and none it does not need.
        ...

    @staticmethod
    def _escaped(label: str) -> str:
        # A label as a quoted string literal in the backslash convention DOT reads. Mermaid spells the same
        # escape as an entity and overrides this. A label is minted by the kernel from a class name plus an
        # optional #n, so the escape is a formality - written anyway, because a domain naming a class with a
        # quote deserves a diagram rather than a syntax error.
        return '"' + label.replace("\\", "\\\\").replace('"', '\\"') + '"'


@final
class Dot(Diagram):
    """Graphviz DOT, ready for `dot -Tsvg run.dot -o run.svg`. Groups become dashed clusters, arrows carry
    the slot that produced them, while a marked node is filled from the palette."""

    @override
    def opening(self) -> tuple[str, ...]:
        return ("digraph run {", "    rankdir=LR;", "    compound=true;",
                "    node [shape=box, style=rounded];")

    @override
    def grouped(self, title: str, index: int, members: tuple[tuple[str, str, str | None], ...]) -> tuple[str, ...]:
        lines = [f"    subgraph cluster_{index} {{",
                 f"        label={self._escaped(title)};",
                 "        style=dashed;"]
        for node, label, mark in members:
            paint = self._tones.get(mark or "")
            attributes = f"label={self._escaped(label)}"
            if paint is not None:
                attributes += f", {paint.dot}"
            lines.append(f"        {node} [{attributes}];")
        lines.append("    }")
        return tuple(lines)

    @override
    def arrow(self, prerequisite: str, dependent: str, slot: str, tone: Tone) -> str:
        return f"    {prerequisite} -> {dependent} [label={self._escaped(slot)}, {tone.dot}];"

    @override
    def contended(self, one: str, other: str, resource: str) -> str:
        # dir=none because the constraint has no direction. constraint=false keeps the link from swaying never sways
        # the ranking. The layout is the run's ORDER and contention says nothing about order.
        return (f"    {one} -> {other} [label={self._escaped(resource)}, dir=none, style=dotted, "
                f"constraint=false, color=gray50, fontcolor=gray50];")

    @override
    def closing(self, used: tuple[str, ...]) -> tuple[str, ...]:
        # DOT paints each node inline, so the marks need no declaration block and the document just closes.
        return ("}",)


@final
class Mermaid(Diagram):
    """Mermaid flowchart, ready to paste into any Markdown that renders it - a README, a pull request, a
    wiki. The same reading as Dot in the format that displays inline.

    An optional `theme` is emitted as Mermaid's init directive before the graph, so a caller restyles the
    whole drawing without subclassing anything. That is the seam CABAL's tactical map stands on."""

    def __init__(self, tones: Mapping[str, Tone] | None = None, *, theme: str = ""):
        super().__init__(tones)
        self.__theme = theme

    @staticmethod
    @override
    def _escaped(label: str) -> str:
        # Mermaid reads no backslash escape inside a quoted label, so the quote goes in as the entity Mermaid
        # spells it with. Quoting at all is what carries a pipe through, the character that would otherwise
        # close an edge label and leave the rest of the line standing as syntax.
        return '"' + label.replace('"', "#quot;") + '"' 

    @override
    def opening(self) -> tuple[str, ...]:
        return ((self.__theme, "graph LR") if self.__theme else ("graph LR",))

    @override
    def grouped(self, title: str, index: int, members: tuple[tuple[str, str, str | None], ...]) -> tuple[str, ...]:
        lines = [f"    subgraph cluster_{index}[{self._escaped(title)}]"]
        lines.extend(f"        {node}[{self._escaped(label)}]" for node, label, _ in members)
        lines.append("    end")
        lines.extend(f"    class {node} {mark}" for node, _, mark in members if mark in self._tones)
        return tuple(lines)

    @override
    def arrow(self, prerequisite: str, dependent: str, slot: str, tone: Tone) -> str:
        return f"    {prerequisite} {tone.mermaid}|{slot}| {dependent}"

    @override
    def contended(self, one: str, other: str, resource: str) -> str:
        # A dotted OPEN link: Mermaid's -.-| |- carries a label with no arrowhead, which is exactly the
        # shape of the claim - these two exclude each other and neither comes first.
        return f"    {one} -.-|{resource}| {other}"

    @override
    def closing(self, used: tuple[str, ...]) -> tuple[str, ...]:
        # Mermaid declares its classes, so only the marks this drawing actually used are emitted.
        return tuple(f"    classDef {mark} {self._tones[mark].mermaid};" for mark in used)
