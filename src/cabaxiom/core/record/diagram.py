"""Diagram - HOW a resolved run becomes a drawing. Graphviz DOT, Mermaid or a format of your own."""
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, NamedTuple, final, override

from ..declaration.vocabulary import EdgeKind, Vocabulary

# ONE MEMBER OF A DRAWN GROUP, as the seam hands it to a format. The node id the format addresses it by
# (minted positionally by render, so no label can collide), the label a human reads and the mark a
# forecast painted on it or None. Three abstract formats spelled this by hand and a fourth written by a
# domain had to reproduce the positions by eye. PUBLIC because grouped() is a seam on an open base.
type Node = tuple[str, str, str | None]

if TYPE_CHECKING:
    from .records import Explanation


@final
class Tone(NamedTuple):
    # How ONE mark is painted, said once per language as DOT node attributes and a Mermaid classDef body.
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
        # Contention, drawn as what it is - a LINK and never an arrow, since an arrow would say one runs
        # before the other and put back the exact false dependency `contends` exists to avoid.
        #
        # ONE HUB PER RESOURCE rather than one link per pair. Drawing every pair was the honest reading of
        # the claim and it is quadratic in the holders of one resource. A step per shard all naming one pool
        # is the fan-in shape this kernel advertises. A thousand of them rendered 53 MB of DOT over half a
        # million lines, which no renderer finishes and no reader wants. A chain of consecutive links would
        # have been the cheap lie, claiming the ends do not exclude each other. A hub tells the whole truth
        # in n edges. Everything touching this node excludes everything else touching it.
        for index, (resource, holders) in enumerate(explanation.contention):
            lines.extend(self.contending(f"x{index}", resource, tuple(identity[held] for held in holders)))
        used = tuple(dict.fromkeys(mark for mark in painted.values() if mark in self._tones))
        lines.extend(self.closing(used))
        return "\n".join(lines)

    @abstractmethod
    def opening(self) -> tuple[str, ...]:
        # The document's first lines - the graph declaration and whatever defaults this format sets once.
        ...

    @abstractmethod
    def grouped(self, title: str, index: int, members: tuple[Node, ...]) -> tuple[str, ...]:
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

    def contending(self, hub: str, resource: str, holders: tuple[str, ...]) -> tuple[str, ...]:
        """ONE resource and every step it holds apart, as a hub node the holders all touch.

        Undirected on purpose, which is why this is not arrow(). An arrow says one thing runs before
        another. This says none of them may run BESIDE any other, in any order. Drawing it with a head would
        put back exactly the false dependency `contends` exists to avoid, in the picture this time
        rather than in the derivation.

        A HUB rather than a link per pair. The pairwise form said the same thing and said it n squared
        times, which a fan of shards on one pool reaches without trying - 1000 of them drew 53 MB. A chain
        of consecutive links would have been the cheap way out and a lie, since it claims the ends do not
        exclude each other. The hub claims what is true, that everything touching it excludes everything
        else touching it, in one node and n edges.

        `hub` is a node id minted by render, distinct from every member id, so a format addresses the node
        without inventing a name that could collide with a label.

        DEFAULTED, unlike the four seams above. The default draws nothing. Those four are abstract because
        a format that cannot do them is not a diagram. This one is different - a format may have no syntax
        for an undirected link at all, so a drawing that stays silent about a constraint tells no lie where
        one that borrowed an arrow would."""
        return ()

    @abstractmethod
    def closing(self, used: tuple[str, ...]) -> tuple[str, ...]:
        # The document's last lines, handed exactly the marks this drawing actually used, so a format that
        # declares its classes up front (Mermaid) emits only the ones in play and none it does not need.
        ...

    @staticmethod
    def _escaped(label: str) -> str:
        # A label as a quoted string literal in the backslash convention DOT reads. Mermaid spells the same
        # escape as an entity and overrides this. A node label is minted by the kernel from a class name plus
        # an optional #n, so there the escape is a formality - written anyway, because a domain naming a class
        # with a quote deserves a diagram rather than a syntax error. A CONTENDED RESOURCE is not a formality.
        # A slot is an EdgeKind name, refused at construction unless it is an identifier, so it carries no
        # syntax whatever vocabulary declared it. A resource is whatever string the domain wrote.
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
    def grouped(self, title: str, index: int, members: tuple[Node, ...]) -> tuple[str, ...]:
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
    def contending(self, hub: str, resource: str, holders: tuple[str, ...]) -> tuple[str, ...]:
        # dir=none because the constraint has no direction. constraint=false keeps the links out of the
        # ranking, since the layout is the run's ORDER and contention says nothing about order. The hub is
        # drawn small and grey so it reads as a constraint rather than as a step.
        return (
            f"    {hub} [label={self._escaped(resource)}, shape=point, width=0.12, color=gray50];",
            *(f"    {hub} -> {held} [dir=none, style=dotted, constraint=false, color=gray50];"
              for held in holders),
        )

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

    @override
    @staticmethod
    def _escaped(label: str) -> str:
        # Mermaid knows no backslash escape inside a quoted label, only entity codes, so the shared DOT rule
        # closed the label at the first quote and spilled the rest of an identifier into the diagram as
        # syntax. A step built from data carries whatever name the data had.
        return '"' + label.replace('"', "#quot;") + '"'

    def __init__(self, tones: Mapping[str, Tone] | None = None, *, theme: str = ""):
        super().__init__(tones)
        self.__theme = theme

    @override
    def opening(self) -> tuple[str, ...]:
        return (self.__theme, "graph LR") if self.__theme else ("graph LR",)

    @override
    def grouped(self, title: str, index: int, members: tuple[Node, ...]) -> tuple[str, ...]:
        lines = [f"    subgraph cluster_{index}[{self._escaped(title)}]"]
        lines.extend(f"        {node}[{self._escaped(label)}]" for node, label, _ in members)
        lines.append("    end")
        lines.extend(f"    class {node} {mark}" for node, _, mark in members if mark in self._tones)
        return tuple(lines)

    @override
    def arrow(self, prerequisite: str, dependent: str, slot: str, tone: Tone) -> str:
        return f"    {prerequisite} {tone.mermaid}|{slot}| {dependent}"

    @override
    def contending(self, hub: str, resource: str, holders: tuple[str, ...]) -> tuple[str, ...]:
        # A dotted OPEN link, Mermaid's -.- , which carries no arrowhead - exactly the shape of the claim,
        # since these exclude each other and none comes first. The hub wears the resource name in a round
        # node, so the label is said once instead of once per link.
        return (
            f"    {hub}(({self._escaped(resource)}))",
            *(f"    {hub} -.- {held}" for held in holders),
        )

    @override
    def closing(self, used: tuple[str, ...]) -> tuple[str, ...]:
        # Mermaid declares its classes, so only the marks this drawing actually used are emitted.
        return tuple(f"    classDef {mark} {self._tones[mark].mermaid};" for mark in used)
