"""Data lineage as a TRACE, not a framework - an Observer listening on produced()."""
import json
from collections.abc import Mapping
from typing import TextIO, final, override

from ..observer import Observer
from ..step import Step


@final
class Lineage(Observer):
    """One JSONL line per clean producer, straight off the kernel's own attribution seam - which step
    produced which artifacts, per pass - with not one line added to any step.

    The produced() hook is the source. The Ledger announces every clean step's artifacts as it records
    them, so the lineage IS the run's record, never a parallel bookkeeping that could disagree with it.
    Steps are named the way every kernel read names them - the class name, with later instances of one
    kind numbered in the order this trace first saw them - and a value that does not speak JSON is
    written as its repr, because a lineage that crashes on a handle is worse than one that names it.

    Hand it a sink (a file opened for append, a StringIO in a rehearsal) and compose it with Chorus if
    the run already has an observer. The teardown's producers ride the same hook, so a prune's
    attributions land here too."""

    def __init__(self, sink: TextIO) -> None:
        self.__sink = sink
        self.__passes = 0
        self.__tally: dict[str, int] = {}
        self.__labels: dict[Step, str] = {}

    @override
    def began(self) -> None:
        self.__passes += 1

    @override
    def produced(self, step: Step, artifacts: Mapping[str, object]) -> None:
        label = self.__labels.get(step)
        if label is None:
            name = step.__class__.__name__
            count = self.__tally[name] = self.__tally.get(name, 0) + 1
            label = self.__labels[step] = name if count == 1 else f"{name}#{count}"
        line = {"pass": self.__passes, "step": label, "artifacts": dict(artifacts)}
        self.__sink.write(json.dumps(line, default=repr) + "\n")

