"""Diagram - the axis that renders a resolved run, with Mermaid and Graphviz DOT on it.

A diagram is a strategy over an Explanation and nothing else. It is handed a run that has already been
resolved, it re-derives nothing and it cannot reach the Reconciler, the Graph or a Step - so a rendering
bug can produce an ugly picture and never a wrong run. That is the whole reason the seam is drawn here
rather than as a method on the engine.

It reads the Explanation's reasons rather than its edges, which is what makes the picture worth having.
A flat arrow says two steps are ordered. A labelled one says WHICH declaration ordered them, while a dashed
one says the declaration was soft, so a reader can see at a glance which edges the run would still be
correct without."""
from abc import ABC, abstractmethod
from typing import final

from ._compat import override
from .records import Explanation, Reason


class Diagram(ABC):
    """Strategy for rendering an Explanation as source text in some drawing language.

    __call__ takes the record and returns the text. There is no file handling and no rendering, because a
    caller who wants a PNG has a renderer already and one who wants to paste into a README wants the text.

    The shared work is here and the per-language work is not. Both renderers group the same steps, label
    the same arrows and dash the same soft ones, so a subclass answers only how its own language spells
    those things - which is the test of whether this axis is real."""

    @abstractmethod
    def __call__(self, explanation: Explanation) -> str:
        ...

    @staticmethod
    def _drawn(explanation: Explanation) -> tuple[Reason, ...]:
        # The arrows worth drawing, which is every declaration that resolved to something. A soft miss is
        # honest in a text explanation and noise in a picture, since it has no other end to point at.
        return tuple(reason for reason in explanation.reasons if reason.matched)

    @staticmethod
    def _labelled(reason: Reason, drawn: str) -> str:
        # An arrow carries its slot and, when the slot is addressed by something other than the step's own
        # kind, the name that was written. `expects Cache -> Cache` says the name twice, so it says it once.
        return reason.slot if reason.name == drawn else f"{reason.slot} {reason.name}"


@final
class Mermaid(Diagram):
    """Mermaid `flowchart`, which GitHub renders inline in a README or an issue.

    Groups become subgraphs, so the wave or chain structure is what a reader sees first. Steps are keyed by
    name, which is what the Explanation carries - two steps of one class therefore share a node, which is
    the honest picture of a drawing made from names rather than from identities."""

    @override
    def __call__(self, explanation: Explanation) -> str:
        drawn = ["flowchart TD"]
        for index, group in enumerate(explanation.groups):
            drawn.append(f'    subgraph g{index}["{explanation.shape} {index + 1}"]')
            drawn.extend(f"        {self.__key(step)}[{step}]" for step in group)
            drawn.append("    end")
        for reason in self._drawn(explanation):
            for found in reason.matched:
                arrow = "-->" if reason.hard else "-.->"
                label = self._labelled(reason, found)
                drawn.append(f"    {self.__key(found)} {arrow}|{label}| {self.__key(reason.step)}")
        return "\n".join(drawn)

    @staticmethod
    def __key(step: str) -> str:
        # Mermaid node ids take no quotes and no punctuation, while a step name is a Python identifier, so
        # the name IS the id. The label carries the readable form in case that ever stops being true.
        return step


@final
class Dot(Diagram):
    """Graphviz DOT, for a caller who wants a rendered file rather than a block in a README.

    Where Mermaid dashes a soft edge, DOT styles it - the second renderer is where you find out whether
    the axis was real, because the two languages agree on nothing except what has to be drawn. Both group
    the same steps, label the same arrows and mark the same soft ones, while neither reaches past the
    Explanation to do it. What differs is only how each language spells those three things.

    Groups become clusters, which is the DOT spelling of a subgraph that gets a box drawn round it - the
    `cluster_` prefix is not decoration, it is what makes Graphviz draw the box at all."""

    @override
    def __call__(self, explanation: Explanation) -> str:
        drawn = ["digraph run {", "    rankdir=TB;", '    node [shape=box];']
        for index, group in enumerate(explanation.groups):
            drawn.append(f"    subgraph cluster_{index} {{")
            drawn.append(f'        label="{explanation.shape} {index + 1}";')
            drawn.extend(f'        "{step}";' for step in group)
            drawn.append("    }")
        for reason in self._drawn(explanation):
            for found in reason.matched:
                style = "" if reason.hard else ", style=dashed"
                label = self._labelled(reason, found).replace('"', "'")
                drawn.append(f'    "{found}" -> "{reason.step}" [label="{label}"{style}];')
        drawn.append("}")
        return "\n".join(drawn)
