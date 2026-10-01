"""Select which steps take part in a run - by type, by tag and with a hard presence requirement.

Scope decides which of the handed steps a run touches, resolved once at construction so every
verb sees the same set:

  Scope()            everything (the default)
  Only(A, ...)       the named types PLUS their transitive dependencies (a targeted run stays
                     dependency-closed - a target never runs before what it declared it needs)
  Skip(B, ...)       everything EXCEPT the named types, no cascade
  WithTag(t, ...)    only steps carrying a named tag - the axis orthogonal to type
  WithoutTag(t, ...) everything except steps carrying a named tag

Steps declare dependencies three ways - `expects` (a soft edge on a kind), `needs` (a soft edge on
an instance) and `requires` (a HARD edge on a kind - absent means the run cannot proceed and
construction raises, where `expects` would silently trust an absent dependency).

The scenario is a deploy graph: Config -> Migrate -> Api, plus an independent Metrics sidecar.
Some steps are tagged "prod".

Run it:

    python examples/scoped_rollout.py

Expected stdout - the full run touches everything, Only(Api) pulls Config and Migrate along but
leaves Metrics out, Skip(Metrics) drops just the sidecar, WithTag("prod") keeps only the tagged
steps and a step that `requires` an absent one fails loudly at construction. All in memory.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Only, Reconciler, Skip, Step, WithoutTag, WithTag
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Only, Reconciler, Skip, Step, WithoutTag, WithTag


class Deploy(Step):
    """A deploy step that records the fact it ran, so a run's touched set is observable."""

    def __init__(self, name: str, ran: list, tags: frozenset[str] = frozenset()):
        self.name = name
        self.ran = ran
        self.tags = tags

    def apply(self, inputs):
        self.ran.append(self.name)


        return None, {}
class Config(Deploy):
    pass


class Migrate(Deploy):
    expects = (Config,)


class Api(Deploy):
    expects = (Migrate,)


class Metrics(Deploy):
    pass


async def run(label: str, scope) -> list:
    ran: list = []
    steps = [
        Api("api", ran, tags=frozenset({"prod"})),
        Config("config", ran, tags=frozenset({"prod"})),
        Migrate("migrate", ran, tags=frozenset({"prod"})),
        Metrics("metrics", ran),  # the sidecar is not tagged prod
    ]
    await Reconciler(steps, scope=scope).converge() if scope else await Reconciler(steps).converge()
    print(f"{label}: touched {ran}")
    return ran


async def main() -> None:
    everything = await run("full run (default Scope)", None)
    targeted = await run("Only(Api) - pulls its prerequisites, drops the unrelated sidecar", Only(Api))
    no_sidecar = await run("Skip(Metrics) - everything but the sidecar", Skip(Metrics))
    tagged = await run("WithTag('prod') - only the tagged steps", WithTag("prod"))
    untagged = await run("WithoutTag('prod') - everything but the tagged steps", WithoutTag("prod"))

    assert set(everything) == {"config", "migrate", "api", "metrics"}
    # Only is the one that could quietly be wrong. It is dependency-CLOSED, so naming Api drags Config
    # and Migrate in - and it stays ORDERED, so the target never runs ahead of what it asked for. This
    # list asserts both at once, which a set comparison would let slide.
    assert targeted == ["config", "migrate", "api"]
    assert "metrics" not in targeted   # closure pulls prerequisites, never the merely-present
    assert set(no_sidecar) == {"config", "migrate", "api"}   # Skip drops the named type and nothing else
    # Tag is the axis ORTHOGONAL to type: the two tag scopes partition the same run, with no overlap and
    # nothing dropped between them.
    assert set(tagged) | set(untagged) == set(everything)
    assert not set(tagged) & set(untagged)
    assert untagged == ["metrics"]
    print()

    print("A hard `requires` on an absent dependency fails loudly at construction:")

    class Vault(Step):
        pass

    class Secret(Step):
        requires = (Vault,)  # a Secret cannot be provisioned without a Vault present in the run

    refused = False
    try:
        Reconciler((Secret(),))  # Vault was not handed in
    except ValueError as error:
        refused = True
        print(f"    {error}")

    # AT CONSTRUCTION is the whole claim. Had the Reconciler been built and only failed later, this
    # would have passed with the run half done, which is exactly what `requires` promises not to allow.
    assert refused


if __name__ == "__main__":
    asyncio.run(main())

