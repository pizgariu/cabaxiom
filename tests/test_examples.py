"""Example smoke tests: every script in examples/ runs to a clean exit, so the documentation cannot rot."""
import os
import pathlib
import subprocess
import sys
import unittest

_EXAMPLES = sorted((pathlib.Path(__file__).resolve().parents[1] / "examples").glob("*.py"))
# A throwaway git identity, so the example that drives a repository works on a runner with no global git config.
_ENV = {**os.environ, "GIT_AUTHOR_NAME": "smoke", "GIT_AUTHOR_EMAIL": "smoke@example.invalid",
        "GIT_COMMITTER_NAME": "smoke", "GIT_COMMITTER_EMAIL": "smoke@example.invalid"}


class ExampleSmokeTests(unittest.TestCase):
    def test_every_example_runs_to_a_clean_exit(self):
        self.assertTrue(_EXAMPLES, "no example scripts found")
        for example in _EXAMPLES:
            with self.subTest(example=example.name):
                result = subprocess.run(
                    [sys.executable, str(example)],
                    capture_output=True, text=True, timeout=120, env=_ENV,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
