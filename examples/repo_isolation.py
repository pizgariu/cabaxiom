#!/usr/bin/env python3
"""One repository, many standards - which one will not hold? Isolation hunts it.

A fleet check names the repos out of standard. But a single repo can carry a dozen standards and when
it will not fully converge you want the ONE that is the blocker, not a wall of residual. Isolation
delta-debugs the standards down to the minimal one that still will not settle and mints an Indictment
naming it - here, a default_branch that is locked and cannot be moved.

Runs against a fake in-memory GitHub, so no token and no network.
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    from battery.repository import GitHub, RepoSetting
    from cabaxiom import Reconciler
    from cabaxiom.laboratory import Isolation, Stall
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from battery.repository import GitHub, RepoSetting
    from cabaxiom import Reconciler
    from cabaxiom.laboratory import Isolation, Stall


class FakeHub:
    """One repo whose `frozen` keys ignore writes - a default_branch you cannot move from here, an
    archived flag - so a standard over one of them can never be met and Isolation has a real blocker."""

    def __init__(self, settings: dict, frozen: set) -> None:
        self.settings = settings
        self.frozen = frozen

    def transport(self, method, url, headers, body):
        if method == "PATCH":
            for key, value in json.loads(body).items():
                if key not in self.frozen:
                    self.settings[key] = value
        return 200, dict(self.settings)


async def main() -> None:
    fake = FakeHub(
        {"has_issues": False, "allow_merge_commit": True, "default_branch": "master"},
        frozen={"default_branch"},        # locked - this repo's default branch cannot be moved from here
    )
    gh = GitHub("no-token-needed", transport=fake.transport)
    repo = "acme/api"

    # Each standard is its own named Step, so the Indictment can name the standard, not a line number.
    class HasIssues(RepoSetting):
        def __init__(self) -> None:
            super().__init__(gh, repo, "has_issues", True)

    class SquashOnly(RepoSetting):
        def __init__(self) -> None:
            super().__init__(gh, repo, "allow_merge_commit", False)

    class DefaultMain(RepoSetting):
        def __init__(self) -> None:
            super().__init__(gh, repo, "default_branch", "main")

    def standards() -> list:
        return [HasIssues(), SquashOnly(), DefaultMain()]

    print(f"{repo} carries three standards: HasIssues, SquashOnly, DefaultMain.\n")

    print("Enforce them:")
    residual = await Reconciler(standards()).converge()
    print("    patched, then re-read. residual (what will not hold):")
    for item in residual:
        print(f"        ! {item.message}")

    print("\nHunt the blocker (Isolation delta-debugs the standards):")
    indictment = await Isolation(standards(), charge=Stall()).isolate()
    for name in indictment.dismissed:
        print(f"    . {name} - clears in isolation")
    print(f"    GUILTY: {indictment.accused[0]} - the one standard that will not settle")

    assert indictment.accused == ("DefaultMain",)

    print("\nThree standards narrowed to the one structurally unsatisfiable here. On a repo with")
    print("twenty standards and a noisy residual, this is how you find the blocker, not guess it.")


if __name__ == "__main__":
    asyncio.run(main())
