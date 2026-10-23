"""Acceptance - the idempotence guarantee, read the way an operator reads it.

Every step here goes through the public door and touches a real directory. A unit test asks whether a
method returned the right value. This asks whether the promise on the README's front page holds when
somebody actually runs the thing twice, which is a different question and one a mock cannot answer."""
import asyncio
import pathlib

from battery.setup import Directory, File
from pytest_bdd import given, scenarios, then, when

from cabaxiom import Reconciler, Residual, Step
from cabaxiom.laboratory import Idempotence, Proof

scenarios("features/idempotence.feature")

CONTENT = '[core]\nmode = "fast"\n'


class World:
    """What one scenario holds - the directory it plays in, the declaration and what the last verb answered."""

    def __init__(self, home: pathlib.Path) -> None:
        self.home = home
        self.config = home / "app" / "config.toml"
        self.residual: Residual | None = None
        self.proof: Proof | None = None

    def declaration(self) -> tuple[Step, ...]:
        # Fresh instances per call, because a Step is frozen after construction and a declaration is
        # rebuilt for every run - the same way a caller would write it.
        home, config = self.home, self.config

        class AppDir(Directory):
            def __init__(self) -> None:
                super().__init__(home / "app")

        class Config(File):
            expects = (AppDir,)

            def __init__(self) -> None:
                super().__init__(config, CONTENT)

        return (Config(), AppDir())          # handed out of order on purpose, the kernel sorts it


@given("an empty working directory", target_fixture="world")
def _empty_directory(tmp_path: pathlib.Path) -> World:
    return World(tmp_path)


@given("a declaration of a directory holding a configuration file")
def _declaration(world: World) -> None:
    assert not world.config.exists()          # the world really is empty before anything runs


@given("the declaration has already been converged once")
def _converged_once(world: World) -> None:
    residual = asyncio.run(Reconciler(world.declaration()).converge())
    assert residual == [], "the precondition itself failed to converge"


@given("somebody overwrote the configuration file with the wrong content")
def _drifted(world: World) -> None:
    world.config.write_text("# not what was declared\n")


@when("the operator converges the declaration")
@when("the operator converges the declaration again")
def _converge(world: World) -> None:
    world.residual = asyncio.run(Reconciler(world.declaration()).converge())


@when("the operator asks for an idempotence proof of the declaration")
def _prove(world: World) -> None:
    world.proof = asyncio.run(Idempotence(Reconciler(world.declaration())).prove())


@then("the residual is empty")
def _residual_empty(world: World) -> None:
    assert world.residual is not None
    assert world.residual == [], f"the run left work behind - {list(world.residual)}"


@then("the applied channel is empty")
def _applied_empty(world: World) -> None:
    assert world.residual is not None
    assert world.residual.applied == (), f"a settled world was written to - {world.residual.applied}"


@then("the applied channel names both the directory and the file")
def _applied_both(world: World) -> None:
    # A battery reports by PATH, which is what an operator reading the run actually recognises.
    assert world.residual is not None
    assert sorted(item.name for item in world.residual.applied) == [str(world.config.parent), str(world.config)]


@then("the applied channel names only the file")
def _applied_file_only(world: World) -> None:
    assert world.residual is not None
    assert [item.name for item in world.residual.applied] == [str(world.config)]


@then("the configuration file exists on disk with the declared content")
def _file_on_disk(world: World) -> None:
    assert world.config.read_text() == CONTENT


@then("the proof is stable")
def _proof_stable(world: World) -> None:
    assert world.proof is not None
    assert world.proof.stable, f"churned={world.proof.churned} residual={list(world.proof.residual)}"


@then("the proof reports no churn")
def _proof_no_churn(world: World) -> None:
    assert world.proof is not None
    assert world.proof.churned == ()
