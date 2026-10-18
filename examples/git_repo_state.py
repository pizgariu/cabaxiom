"""Drive a real git repository toward a desired state, then prove it with an empty residual.

This is the fullest of the three examples. Three Steps own one concern each and talk to git
through plain subprocess calls:

  GitConfig      ensure a set of repo-local `git config` entries hold the values you want
  InitialCommit  ensure the repository has at least one commit (after GitConfig, since a
                 commit needs an author identity that GitConfig sets)
  LocalBranch    ensure a named local branch exists (after InitialCommit, since a branch
                 must point at a commit)

The `expects` edges form the chain GitConfig -> InitialCommit -> LocalBranch. The steps are
handed to the Reconciler in a scrambled order on purpose and the default Kahn ordering
resolves them back into a runnable sequence.

Every step's drift() is a genuine read of the repository and every apply() is a genuine
mutation. converge() applies the plan and then RE-PROBES: the residual it returns is the
proof. An empty residual means the repository now matches the desired state, verified by
reading it back, not merely assumed because apply() did not raise.

Run it:

    python examples/git_repo_state.py

Expected stdout - the plan lists every pending change (the three config keys, the missing
initial commit and the missing branch), the first converge reports what it changed and
returns an empty residual, a second converge is a clean no-op (idempotent) and
a direct git inspection confirms the config, the commit and the branch are all in place. The
example builds a throwaway repository in a temp directory and deletes it on the way out, so
it runs anywhere with git installed.
"""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Reconciler, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Reconciler, Step


def run_git(repo: str, args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    # One place that shells out to git. Reads pass check=False and inspect the return code
    # themselves (an unset config key or a missing HEAD is expected, not an error). Writes
    # pass check=True so a real failure surfaces loudly.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


class GitConfig(Step):
    """Ensure a set of repo-local git config entries hold the desired values."""

    def __init__(self, repo: str, desired: dict[str, str]):
        self.repo = repo
        self.desired = dict(desired)

    def _current(self, key: str) -> str | None:
        completed = run_git(self.repo, ["config", "--local", "--get", key])
        return completed.stdout.strip() if completed.returncode == 0 else None

    def assess(self, inputs):
        drifted = []
        for key, want in self.desired.items():
            have = self._current(key)
            if have != want:
                shown = repr(have) if have is not None else "unset"
                drifted.append(DriftItem(key, f"want {want!r}, have {shown}"))
        return Assessment(deviation=drifted), {}

    def apply(self, inputs):
        changed = []
        for key, want in self.desired.items():
            if self._current(key) != want:
                run_git(self.repo, ["config", "--local", key, want], check=True)
                changed.append(DriftItem(key, f"set to {want!r}"))
        return changed or None, {}


class InitialCommit(Step):
    """Ensure the repository has a first commit, so a branch has something to point at."""

    expects = (GitConfig,)

    def __init__(self, repo: str):
        self.repo = repo

    def assess(self, inputs):
        head = run_git(self.repo, ["rev-parse", "--verify", "-q", "HEAD"])
        if head.returncode != 0:
            return Assessment(deviation=[DriftItem("HEAD", "repository has no commits yet")]), {}
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        if not self.assess(inputs)[0].deviation:
            return None, {}
        readme = Path(self.repo) / "README.md"
        readme.write_text("# Managed by cabaxiom\n", encoding="utf-8")
        run_git(self.repo, ["add", "README.md"], check=True)
        run_git(self.repo, ["commit", "-m", "Seed the repository"], check=True)
        return [DriftItem("HEAD", "created the initial commit")], {}


class LocalBranch(Step):
    """Ensure a named local branch exists."""

    expects = (InitialCommit,)

    def __init__(self, repo: str, name: str):
        self.repo = repo
        self.name = name

    def assess(self, inputs):
        listed = run_git(self.repo, ["branch", "--list", self.name])
        if not listed.stdout.strip():
            return Assessment(deviation=[DriftItem(f"branch:{self.name}", "local branch is missing")]), {}
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        if not self.assess(inputs)[0].deviation:
            return None, {}
        run_git(self.repo, ["branch", self.name], check=True)
        return [DriftItem(f"branch:{self.name}", "created local branch")], {}


def report(residual) -> None:
    if residual.applied:
        print("  applied this run:")
        for item in residual.applied:
            print(f"    + {item}")
    else:
        print("  applied this run: nothing")
    if residual:
        print("  residual (still wrong):")
        for item in residual:
            print(f"    ! {item}")
    else:
        print("  residual: empty -> desired state verified by re-probe")


async def main() -> None:
    repo = tempfile.mkdtemp(prefix="reconciler-git-")
    try:
        run_git(repo, ["init", "-q"], check=True)
        branch_name = "feature/login"
        desired_config = {
            "user.name": "Reconciler Bot",
            "user.email": "bot@example.test",
            "commit.gpgsign": "false",
        }

        # Handed in scrambled - branch before commit before config. Kahn resolves the after
        # edges, so the reconciler still runs config -> commit -> branch.
        steps = [
            LocalBranch(repo, branch_name),
            InitialCommit(repo),
            GitConfig(repo, desired_config),
        ]
        reconciler = Reconciler(steps)

        print(f"Throwaway repository: {repo}")
        print()
        print("Plan (what converge would do, in resolved order):")
        plan = await reconciler.assess()
        if plan:
            for item in plan:
                print(f"    - {item}")
        else:
            print("    nothing to do")
        # Handed in as branch, commit, config. The plan comes back the other way round, which is the
        # only order that works. The commit needs the identity and the branch needs the commit.
        pending = [item.name for item in plan]
        assert pending.index("user.name") < pending.index("HEAD") < pending.index(f"branch:{branch_name}")
        print()

        print("First converge:")
        first = await reconciler.converge()
        report(first)
        assert not first   # empty because every step's drift() re-read git, not because nothing raised
        print()

        print("Second converge (should be a clean no-op):")
        again = await reconciler.converge()
        report(again)
        assert not again.applied   # no second commit, no re-set config: the writes are all guarded reads
        print()

        print("Direct git inspection:")
        name = run_git(repo, ["config", "--local", "--get", "user.name"]).stdout.strip()
        head = run_git(repo, ["rev-parse", "--short", "HEAD"]).stdout.strip()
        branch = run_git(repo, ["branch", "--list", branch_name]).stdout.strip()
        print(f"    user.name = {name!r}")
        print(f"    HEAD      = {head}")
        print(f"    branch    = {branch}")

        # Asked of git directly, behind the kernel's back. An empty residual is a claim about the world,
        # so the world gets the last word on whether it was true.
        assert name == desired_config["user.name"]
        assert head                             # a commit exists for the branch to point at
        assert branch_name in branch
    finally:
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())