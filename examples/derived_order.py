"""Read the run before running it - what was derived, why and what one failure would cost.

Nothing here touches the world. Every verb in this example is a read of the RUN rather than a read of
reality, so the whole thing is a picture of a deployment that has not started yet.

The stack is a small one and every slot in the language earns its place in it:

    Vault      provides "secrets"
    Postgres   provides "storage", contends for "db"
    Migrate    demands "storage", contends for "db"     <- may never run beside Postgres
    Cache      expects Postgres, softly
    Api        demands "secrets", expects Cache
    Smoke      needs THAT Api instance, by identity

Four things come out of it, in order:

  explain()   the groups the dispatcher will walk plus one Reason per declaration actually written.
              "Api depends on Vault" is not enough to act on when eight slots can draw that edge, so
              each Reason names the slot, the thing that was written and whether it was hard.

  contends    Postgres and Migrate are mutually independent - nothing orders them - so a wave shape
              would happily run them together. The seating splits the wave instead, which is what
              `contends` means and why it is not an edge.

  foresee()   if Vault failed, what would this run lose? The answer comes off the same derivation,
              not off a simulation. It separates what DEPENDS on the failure from what merely
              sits after it in the run.

  Mermaid()   the same picture as text you can paste into a README. A dashed arrow is a soft
              declaration, so you can see at a glance which edges the run would survive without.
"""
import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Mermaid, Parallel, Reconciler, Step
except ModuleNotFoundError:                                  # running from a checkout, not an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Mermaid, Parallel, Reconciler, Step


class Vault(Step):
    provides = frozenset({"secrets"})

    async def assess(self):
        return self.verified()


class Postgres(Step):
    provides = frozenset({"storage"})
    contends = frozenset({"db"})

    async def assess(self):
        return self.verified()


class Migrate(Step):
    demands = ("storage",)
    contends = frozenset({"db"})

    async def assess(self):
        return self.verified()


class Cache(Step):
    expects = (Postgres,)

    async def assess(self):
        return self.verified()


class Api(Step):
    demands = ("secrets",)
    expects = (Cache,)

    async def assess(self):
        return self.verified()


class Smoke(Step):
    async def assess(self):
        return self.verified()


def main() -> None:
    vault, postgres, migrate, cache = Vault(), Postgres(), Migrate(), Cache()
    api = Api()
    smoke = Smoke()
    smoke.needs = (api,)                 # by IDENTITY - that one Api, not every Api in the run

    # Handed in scrambled. Nothing below tells the kernel an order.
    reconciler = Reconciler((smoke, cache, migrate, api, vault, postgres), dispatcher=Parallel())
    told = reconciler.explain()

    print("Resolved waves:")
    for index, group in enumerate(told.groups):
        print(f"    wave {index + 1}: {', '.join(group)}")
    print()

    print("Why each step sits where it does:")
    for group in told.groups:
        for name in group:
            for reason in told.because(name):
                weight = "hard" if reason.hard else "soft"
                print(f"    {reason}   ({weight})")
    print()

    seats = {name: index for index, group in enumerate(told.groups) for name in group}
    print("Contention (Postgres and Migrate both name 'db' while nothing orders them):")
    print(f"    Postgres is in wave {seats['Postgres'] + 1}, Migrate in wave {seats['Migrate'] + 1}")
    print("    -> the seating split the wave, because a wave runs together and these two may not")
    print()

    print("If Vault failed, before anything runs:")
    forecast = reconciler.foresee(vault)
    print(f"    {forecast}")
    print(f"    blocked  {', '.join(forecast.blocked) or 'nothing'}    (depends on it, transitively)")
    print(f"    skipped  {', '.join(forecast.skipped) or 'nothing'}    (a later wave, under FailFast)")
    print(f"    settling {', '.join(forecast.settling) or 'nothing'}    (its own wave, already in flight)")
    print(f"    starves  {', '.join(forecast.starves) or 'nothing'}    (it is the only provider)")
    print()
    print("    Read `blocked` for what it is. BestEffort records the failure and keeps going, so those")
    print("    steps still run - against state nobody put there. This read is what says so.")
    print()

    print("The same run as Mermaid (paste it into a README and GitHub draws it):")
    print()
    for line in Mermaid()(told).splitlines():
        print(f"    {line}")
    print()

    residual = asyncio.run(reconciler.converge())
    print(f"Converged for real: residual {'empty -> verified' if not residual else residual}")


if __name__ == "__main__":
    main()
