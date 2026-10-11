"""A dbt project's run state as desired state, read from the files dbt itself writes.

No dbt in the dependencies and none needed here. dbt records every run in `target/run_results.json`,
so assess() reads THAT - the statuses per node, the moment the run was generated - and apply() runs the
command the domain configured (`dbt build` by default) through the standard library's subprocess. The
seam is the COMMAND, which is what makes the battery honest and the suite offline. A test points it at
a script that writes run_results the way dbt would and the real subprocess path is proven without dbt
installed.

The re-read is the judge, exactly as the repository beachhead learned it. apply() refuses a non-zero
exit loudly (a run that could not even finish must not be mistaken for a run that finished badly) and
everything softer than that - a failed model, a skipped seed, a warned test - is what the re-probe
reads out of run_results and reports on the channel it deserves - failures as deviation, warnings as
advisory, because advice never dirties a proof."""
import json
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import final, override

from ..drift import Artifacts, Assessment, Drift, DriftItem, FlowAssessment, FlowOutcome
from ..step import Step

# The statuses dbt writes that mean "this node is where it should be" and the one that is advice.
_SETTLED = frozenset({"success", "pass"})
_ADVICE = frozenset({"warn"})


@final
class DbtRun(Step):
    """One dbt project converged. A recorded run exists, it is complete, every node settled - and,
    when a freshness budget is given, it happened recently enough to still count.

    assess() never runs dbt. It reads `target/run_results.json`. No file is "never ran", a node whose
    status is neither settled nor a warning lands in deviation naming the node and the status, a
    warning lands in advisory and a run older than `within` seconds is stale. apply() is the
    level-triggered no-op when the reading is already clean and otherwise runs the command in the
    project directory - a non-zero exit RAISES with the exit code, because an infra failure that never
    rewrote run_results would otherwise leave a fresh-looking success for the re-probe to believe.

    Prune is a deliberate no-op. Un-building models is a data loss with extra steps, the Loaded
    doctrine one battery over. The artifacts speak pointers - the node count and the run's moment
    cross the run, the warehouse stays where it is."""

    def __init__(self, project: str | Path, command: tuple[str, ...] = ("dbt", "build"),
                 within: float | None = None, now: Callable[[], float] = time.time) -> None:
        self._project = Path(project).expanduser()
        if not command:
            raise ValueError("DbtRun command is empty. The command is the seam - ('dbt', 'build') or your own.")
        self._command = command
        self._within = within
        self._now = now

    def __results(self) -> dict[str, object] | None:
        recorded = self._project / "target" / "run_results.json"
        if not recorded.exists():
            return None
        decoded: object = json.loads(recorded.read_text(encoding="utf-8"))
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def __nodes(results: dict[str, object]) -> list[tuple[str, str]]:
        listed = results.get("results", [])
        if not isinstance(listed, list):
            return []
        return [(str(node.get("unique_id", "?")), str(node.get("status", "?")))
                for node in listed if isinstance(node, dict)]

    def __moment(self, results: dict[str, object]) -> float | None:
        metadata = results.get("metadata")
        stamped = metadata.get("generated_at") if isinstance(metadata, dict) else None
        if not isinstance(stamped, str):
            return None
        return datetime.fromisoformat(stamped).timestamp()

    def __reading(self) -> tuple[list[Drift], list[Drift], Artifacts]:
        # ONE read serves every verb, the mirror by construction - what is wrong, what is advice and
        # the pointers this project's state amounts to.
        results = self.__results()
        name = self._project.name
        if results is None:
            return [DriftItem(name, "no run recorded: target/run_results.json does not exist")], [], {}
        wrong: list[Drift] = [DriftItem(node, f"status {status}") for node, status in self.__nodes(results)
                              if status not in _SETTLED and status not in _ADVICE]
        advice: list[Drift] = [DriftItem(node, f"status {status}") for node, status in self.__nodes(results) if status in _ADVICE]
        moment = self.__moment(results)
        if self._within is not None:
            if moment is None:
                wrong.append(DriftItem(name, "the recorded run carries no generated_at to be fresh by"))
            else:
                age = self._now() - moment
                if age > self._within:
                    wrong.append(DriftItem(name, f"stale: the recorded run is {age:.0f}s old against a budget of {self._within:.0f}s"))
        settled = sum(status in _SETTLED for _, status in self.__nodes(results))
        pointers: Artifacts = {f"{name}/nodes": settled}
        if moment is not None:
            pointers[f"{name}/ran_at"] = moment
        return wrong, advice, pointers

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        wrong, advice, pointers = self.__reading()
        return Assessment(deviation=wrong, advisory=advice), pointers

    @override
    def apply(self, inputs: Artifacts) -> FlowOutcome:
        wrong, _, _ = self.__reading()
        if not wrong:
            _, _, pointers = self.__reading()
            return None, pointers   # the level-triggered no-op: the recorded run already satisfies the declaration
        exited = subprocess.run(self._command, cwd=self._project, check=False).returncode
        if exited != 0:
            raise RuntimeError(
                f"{' '.join(self._command)} exited {exited} in {self._project}. A run that could not "
                f"finish must not be mistaken for one that finished badly - read what it printed and "
                f"what target/run_results.json now records."
            )
        wrong, _, pointers = self.__reading()
        built = pointers.get(f"{self._project.name}/nodes", 0)
        return [DriftItem(self._project.name, f"dbt run recorded: {built} nodes settled")], pointers

    @override
    def prune(self, inputs: Artifacts) -> FlowOutcome:
        # Un-building models is a data loss with extra steps. The rows the models materialised do not
        # belong to this battery to destroy, so the teardown leaves the warehouse standing.
        return [], {}

