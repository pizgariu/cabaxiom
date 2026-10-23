#!/usr/bin/env python3
"""An organisation standard reconciled across a FLEET of repositories and proven.

This is the pitch for battery.repository: stop asking "is every repo compliant?" and prove it. Declare the
standard once, hand every repo's copy to one Reconciler and read the residual as a compliance report -
an EMPTY residual proves the whole fleet conforms, a non-empty one NAMES the repos that resist.

It runs against a fake in-memory GitHub (the transport is injectable), so it needs no token and no
network - the same throwaway-world rehearsal the kernel is built on.
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    from battery.repository import GitHub, RepoSetting
    from cabaxiom import Reconciler
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from battery.repository import GitHub, RepoSetting
    from cabaxiom import Reconciler


class FakeHub:
    """A throwaway GitHub. A `locked` repo ignores writes, standing in for one you cannot fix from here
    (a permission, an archived repo) - so the residual has something honest to name."""

    def __init__(self, repos: dict, locked: set) -> None:
        self.repos = repos
        self.locked = locked

    def transport(self, method, url, headers, body):
        repo = "/".join(url.split("/repos/", 1)[1].split("/")[:2])
        settings = self.repos[repo]
        if method == "PATCH" and repo not in self.locked:
            settings.update(json.loads(body))
        return 200, dict(settings)


async def main() -> None:
    fleet = {
        "acme/api": {"has_issues": True},
        "acme/web": {"has_issues": False},      # drifted and fixable
        "acme/cli": {"has_issues": True},
        "acme/legacy": {"has_issues": False},   # drifted and LOCKED - cannot be fixed from here
    }
    fake = FakeHub(fleet, locked={"acme/legacy"})
    gh = GitHub("no-token-needed", transport=fake.transport)

    def standard() -> list:
        return [RepoSetting(gh, repo, "has_issues", True) for repo in fleet]

    print("The standard: every repo must have has_issues = True.\n")

    print("Compliance check (read-only, names who does not conform):")
    report = await Reconciler(standard()).assess()
    for item in report:
        print(f"    x {item.name}: {item.message}")
    print(f"  {len(report)} of {len(fleet)} repos out of standard\n")

    print("Enforce it (apply patches every drifted repo, then the loop RE-READS to judge):")
    residual = await Reconciler(standard()).converge()
    print(f"    patched: {', '.join(item.name for item in residual.applied)}")
    if residual:
        print("    but the re-probe is the judge, not the API call and one did not take:")
        for item in residual:
            print(f"        ! {item.name}: {item.message}")
        print("    acme/legacy is locked - the patch returned, reality did not change and the")
        print("    self-verifying loop REFUSES to call it done. On a fleet you fully control the")
        print("    residual is EMPTY and that empty residual is the proof every repo conforms.")
    else:
        print("    residual empty -> the whole fleet conforms, proven by re-probe")

    assert [item.name for item in residual] == ["acme/legacy"]
    assert fake.repos["acme/web"]["has_issues"] is True          # the fixable one was brought into line

    print("\nDeclared once, enforced across the fleet and the residual is a proof, not a promise.")


if __name__ == "__main__":
    asyncio.run(main())
