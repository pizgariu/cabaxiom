#!/usr/bin/env python3
"""A development environment declared as desired state, converged, PROVEN idempotent and reversed.

This is the pitch for battery.setup: a setup script that breaks on its second run is dead. Declare
what you want - directories, files, a config key, a gitignore line, a symlinked dotfile - hand it to a
Reconciler and it converges the machine, re-reads to prove it landed, certifies with Idempotence that
a second run changes nothing, self-heals when the world drifts and tears down cleanly through prune.

Everything runs against a throwaway temp home, so it is safe to run again and again - which is the
whole point.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

try:
    from battery.setup import Directory, File, JsonKey, LineInFile, Symlink
    from cabaxiom import Reconciler
    from cabaxiom.laboratory import Idempotence
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from battery.setup import Directory, File, JsonKey, LineInFile, Symlink
    from cabaxiom import Reconciler
    from cabaxiom.laboratory import Idempotence


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        appdir = home / ".config" / "myapp"
        config = appdir / "config.toml"

        # The declaration. Each Step is desired state, ordered with `expects` where it matters. The config
        # file after the directory that holds it, the dotfile after the config it points at.
        class AppDir(Directory):
            def __init__(self) -> None:
                super().__init__(appdir)

        class Config(File):
            expects = (AppDir,)

            def __init__(self) -> None:
                super().__init__(config, '[core]\nmode = "fast"\n')

        class Settings(JsonKey):
            expects = (AppDir,)

            def __init__(self) -> None:
                super().__init__(appdir / "settings.json", ("editor", "tabSize"), 4)

        class Gitignore(LineInFile):
            def __init__(self) -> None:
                super().__init__(home / "project" / ".gitignore", "*.pyc")

        class Dotfile(Symlink):
            expects = (Config,)

            def __init__(self) -> None:
                super().__init__(home / ".myapprc", config)

        def declaration() -> tuple:
            # Handed out of dependency order on purpose - the Reconciler resolves it.
            return (Dotfile(), Gitignore(), Config(), AppDir(), Settings())

        print("Declared dev environment:")
        for name in ("AppDir", "Config -> AppDir", "Settings -> AppDir", "Gitignore", "Dotfile -> Config"):
            print(f"    - {name}")

        print("\nFirst converge:")
        residual = await Reconciler(declaration()).converge()
        for item in residual.applied:
            print(f"    + {item.name}: {item.message}")
        print(f"  residual: {'empty -> desired state verified by re-probe' if not residual else residual}")
        assert not residual

        print("\nProving idempotence (a second run must be a clean no-op):")
        proof = await Idempotence(Reconciler(declaration())).prove()
        print(f"    churned: {list(proof.churned) or 'nothing'}")
        print(f"    stable:  {proof.stable}  -> the setup is idempotent, proven not trusted")
        assert proof.stable

        print("\nThe world drifts (someone rewrites the config):")
        config.write_text("[core]\nmode = \"slow\"\n")
        healed = await Reconciler(declaration()).converge()
        for item in healed.applied:
            print(f"    ~ {item.name}: {item.message}")
        print(f"  residual: {'empty -> self-healed' if not healed else healed}")
        assert config.read_text() == '[core]\nmode = "fast"\n'

        print("\nTeardown (prune, in reverse order):")
        residue = await Reconciler(declaration()).prune()
        for item in residue:
            print(f"    . {item.name}: {item.message}")
        if residue:
            print("  the config directory stays on purpose: JsonKey removed its key but left")
            print("  settings.json, a file it SHARES - prune never deletes what it did not fully own.")
            print("  Honest reversibility beats a reckless teardown.")
        assert not (home / ".myapprc").is_symlink()   # the symlink it owned is gone
        assert not config.is_file()                   # the file it owned is gone

    print("\nDeclared, converged, proven, healed, reversed - and never destructive. "
          "The machine did exactly what you said and said so.")


if __name__ == "__main__":
    asyncio.run(main())
