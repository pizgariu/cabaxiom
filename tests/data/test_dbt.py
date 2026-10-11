"""DbtRun against the files dbt itself writes - offline by construction. The command is the seam, so
the fake dbt here is a Python one-liner writing target/run_results.json exactly where dbt would and
the REAL subprocess path is proven without dbt anywhere near the dependencies."""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from cabaxiom import Idempotence, Reconciler
from cabaxiom.data import DbtRun


def _recorded(project: Path, statuses: dict[str, str], generated_at: str | None = "2026-08-08T10:00:00+00:00") -> None:
    target = project / "target"
    target.mkdir(parents=True, exist_ok=True)
    results = {"results": [{"unique_id": node, "status": status} for node, status in statuses.items()]}
    if generated_at is not None:
        results["metadata"] = {"generated_at": generated_at}
    (target / "run_results.json").write_text(json.dumps(results), encoding="utf-8")


def _fake_dbt(statuses: dict[str, str]) -> tuple[str, ...]:
    # A command that does what dbt does where dbt would. It writes run_results.json under ./target.
    script = (
        "import json, pathlib\n"
        "target = pathlib.Path('target'); target.mkdir(exist_ok=True)\n"
        f"nodes = {json.dumps(statuses)}\n"
        "payload = {'results': [{'unique_id': node, 'status': status} for node, status in nodes.items()],\n"
        "           'metadata': {'generated_at': '2026-08-08T10:00:00+00:00'}}\n"
        "(target / 'run_results.json').write_text(json.dumps(payload))\n"
    )
    return (sys.executable, "-c", script)


class DbtRunTests(unittest.IsolatedAsyncioTestCase):
    def _project(self) -> Path:
        keeper = tempfile.TemporaryDirectory()
        self.addCleanup(keeper.cleanup)
        return Path(keeper.name)

    async def test_it_converges_by_running_the_command_and_believing_only_the_re_read(self):
        project = self._project()
        run = DbtRun(project, command=_fake_dbt({"model.demo.orders": "success", "test.demo.not_null": "pass"}))
        reconciler = Reconciler((run,))
        residual = await reconciler.converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["dbt run recorded: 2 nodes settled"])
        self.assertEqual(residual.produced[run][f"{project.name}/nodes"], 2)
        proof = await Idempotence(reconciler).prove()
        self.assertTrue(proof.stable)   # the second converge is the level-triggered no-op, dbt never re-ran

    def test_no_recorded_run_is_the_first_drift(self):
        run = DbtRun(self._project(), command=_fake_dbt({}))
        assessment, pointers = run.assess({})
        self.assertEqual([item.message for item in assessment.deviation],
                         ["no run recorded: target/run_results.json does not exist"])
        self.assertEqual(pointers, {})

    def test_a_failed_node_is_deviation_and_a_warning_is_advice(self):
        project = self._project()
        _recorded(project, {"model.demo.orders": "success", "model.demo.refunds": "error",
                            "test.demo.recent": "warn", "seed.demo.codes": "skipped"})
        assessment, pointers = DbtRun(project).assess({})
        self.assertEqual({item.name: item.message for item in assessment.deviation},
                         {"model.demo.refunds": "status error", "seed.demo.codes": "status skipped"})
        self.assertEqual([item.message for item in assessment.advisory], ["status warn"])
        self.assertEqual(pointers[f"{project.name}/nodes"], 1)   # only the settled node counts

    def test_a_freshness_budget_makes_an_old_run_stale(self):
        project = self._project()
        _recorded(project, {"model.demo.orders": "success"}, generated_at="2026-08-08T10:00:00+00:00")
        ran_at = datetime.fromisoformat("2026-08-08T10:00:00+00:00").timestamp()   # derived, not guessed
        fresh = DbtRun(project, within=600.0, now=lambda: ran_at + 30.0)
        assessment, pointers = fresh.assess({})
        self.assertEqual(list(assessment.deviation), [])
        self.assertEqual(pointers[f"{project.name}/ran_at"], ran_at)
        stale = DbtRun(project, within=600.0, now=lambda: ran_at + 7200.0)
        assessment, _ = stale.assess({})
        self.assertEqual([item.message for item in assessment.deviation],
                         ["stale: the recorded run is 7200s old against a budget of 600s"])

    def test_a_run_without_a_moment_cannot_be_judged_fresh_and_says_so(self):
        project = self._project()
        _recorded(project, {"model.demo.orders": "success"}, generated_at=None)
        assessment, pointers = DbtRun(project, within=600.0, now=lambda: 0.0).assess({})
        self.assertEqual([item.message for item in assessment.deviation],
                         ["the recorded run carries no generated_at to be fresh by"])
        self.assertNotIn(f"{project.name}/ran_at", pointers)

    def test_a_command_that_cannot_finish_raises_the_exit_code(self):
        # An infra failure must never be mistaken for a run that finished badly. Without the raise, a
        # stale success would still be lying in run_results for the re-probe to believe.
        project = self._project()
        run = DbtRun(project, command=(sys.executable, "-c", "raise SystemExit(2)"))
        with self.assertRaises(RuntimeError) as refused:
            run.apply({})
        self.assertIn("exited 2", str(refused.exception))
        self.assertIn("must not be mistaken for one that finished badly", str(refused.exception))

    async def test_prune_leaves_the_warehouse_standing(self):
        project = self._project()
        _recorded(project, {"model.demo.orders": "success"})
        reconciler = Reconciler((DbtRun(project),))
        self.assertEqual(await reconciler.prune(), [])
        self.assertTrue((project / "target" / "run_results.json").exists())   # nothing was un-built

    def test_a_mangled_run_results_reads_as_a_run_that_recorded_nothing(self):
        # A hand-edited or truncated file is not a crash, it is a reading. No nodes settled, so the
        # deviation channel carries the emptiness the freshness rule already knows how to speak.
        project = self._project()
        target = project / "target"
        target.mkdir(parents=True)
        (target / "run_results.json").write_text('"not even a mapping"', encoding="utf-8")
        assessment, pointers = DbtRun(project, within=600.0, now=lambda: 0.0).assess({})
        self.assertEqual([item.message for item in assessment.deviation],
                         ["the recorded run carries no generated_at to be fresh by"])
        self.assertEqual(pointers[f"{project.name}/nodes"], 0)

        (target / "run_results.json").write_text('{"results": "not a list"}', encoding="utf-8")
        assessment, pointers = DbtRun(project).assess({})
        self.assertEqual(list(assessment.deviation), [])   # nothing listed, nothing wrong to report
        self.assertEqual(pointers[f"{project.name}/nodes"], 0)

    def test_an_empty_command_is_refused_at_construction(self):
        with self.assertRaises(ValueError) as refused:
            DbtRun(self._project(), command=())
        self.assertIn("The command is the seam", str(refused.exception))


if __name__ == "__main__":
    unittest.main()

