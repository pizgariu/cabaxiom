"""The record layer - what a run says about itself, live while it happens and frozen once it has.

The Ledger is the run's single writer of fates and artifacts, an Observer is the trace it fires through as
it goes, the Records are the verdicts it mints when it is done (Residual, Reading, Explanation), a Diagram
draws one for a human. A Warrant is the signed claim that a reading was really taken by the run that
says so.

Deliberately BELOW the run layer rather than beside it. A record must not be able to reach into the thing
it records, so this layering is what stops it - the run imports the record, never the other way."""

from .diagram import Diagram, Dot, Mermaid, Node, Tone
from .ledger import Ledger, OnError, Reading, Statement
from .observer import Chorus, Journal, Logging, Observer, Pass, Span, Stamp, Timing
from .records import Arrow, Casualty, Explanation, Residual
from .warrant import Ceiling, Charter, Warrant

__all__ = [
    "Arrow",
    "Diagram",
    "Dot",
    "Mermaid",
    "Tone",
    "Ledger",
    "OnError",
    "Reading",
    "Statement",
    "Chorus",
    "Journal",
    "Logging",
    "Observer",
    "Pass",
    "Span",
    "Stamp",
    "Timing",
    "Casualty",
    "Explanation",
    "Node",
    "Residual",
    "Ceiling",
    "Charter",
    "Warrant",
]
