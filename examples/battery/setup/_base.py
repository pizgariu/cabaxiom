"""The shared base for the setup batteries."""
import os
import stat
import tempfile
from pathlib import Path
from typing import override

from cabaxiom import Artifacts, Assessment, Changes, Drift, DriftItem, FlowAssessment, FlowOutcome, Step


class Fixture(Step):
    """A desired-state fixture over a single filesystem path, the base every setup battery stands on.

    It holds the target path and three helpers - `_at`, which phrases a finding as Drift keyed by that
    path, so a residual reads as exactly the paths still wrong, `_claim`, the ownership guard that
    refuses a path holding something other than this fixture's own kind, plus `_replace`, the atomic
    write every battery routes its content through. What present, missing or changed MEANS is each
    concrete fixture's own judgement (a file compares content, a directory compares existence) and the
    base stays out of it. A fixture is a Step like any other, so it self-verifies by re-probing and
    reverses through prune. It composes with `expects` and `needs` - a File ordered after the
    Directory that holds it, a Symlink after its target.

    THE DATA-FLOW BRIDGE lives here, once. A fixture reads and writes the filesystem synchronously and
    ferries no artifacts, so the base adapts the kernel's async data-flow contract to the plain
    finding-returning shape each battery actually implements. assess() packs a subclass's `_drift` and
    `_footprint` into the Assessment's deviation and footprint channels and apply()/prune() wrap a
    subclass's `_apply`/`_prune` with the empty artifacts a filesystem step produces. A concrete fixture
    overrides the underscored helpers and never touches the kernel contract, the same way ThreadDispatcher
    lets a blocking domain ride the async engine without speaking coroutines."""

    def __init__(self, path: str | Path) -> None:
        # expanduser at the door, so the documented `~/.config/app/config.toml` declaration means the
        # caller's home directory and not a literal `~` directory under whatever the working directory
        # happens to be. Every battery inherits it, so one expansion covers the whole surface.
        self.path = Path(path).expanduser()

    @override
    def assess(self, inputs: Artifacts) -> FlowAssessment:
        return Assessment(deviation=self._drift(), footprint=self._footprint()), {}

    @override
    def apply(self, inputs: Artifacts) -> FlowOutcome:
        return self._apply(), {}

    @override
    def prune(self, inputs: Artifacts) -> FlowOutcome:
        return self._prune(), {}

    def _drift(self) -> list[Drift]:
        # What is out of desired state at this path, empty when it already holds. Overridden by every
        # battery. The default reports nothing, so a fixture that only owns a footprint stays quiet here.
        return []

    def _apply(self) -> Changes:
        # Close the gap and report what changed, None for a clean no-op. Overridden by every battery.
        return None

    def _prune(self) -> list[Drift]:
        # Remove what this fixture owns and report what SURVIVED the teardown. Overridden by every battery.
        return []

    def _footprint(self) -> list[Drift]:
        # What this fixture owns that a teardown would remove, for the assessment's footprint channel.
        return []

    def _at(self, message: str) -> list[Drift]:
        # One drift item, keyed by this fixture's path. Drift, apply's change report and footprint all
        # speak through it, so every finding names the path it is about.
        return [DriftItem(str(self.path), message)]

    def _standing(self) -> str:
        # What actually stands AT the path, named for an error message. Read through lstat, never stat,
        # because the question is what IS there and not what it points at - a symlink must report as a
        # symlink instead of impersonating its target. An empty string means the path is free.
        try:
            mode = self.path.lstat().st_mode
        except OSError:
            return ""
        if stat.S_ISLNK(mode):
            return "a symlink"
        if stat.S_ISDIR(mode):
            return "a directory"
        if stat.S_ISREG(mode):
            return "a regular file"
        if stat.S_ISFIFO(mode):
            return "a FIFO"
        return "a special file"

    def _claim(self, kind: str) -> None:
        # The ownership guard. A fixture reads and writes only where its OWN kind stands or where
        # nothing stands yet. Anything else at the path belongs to somebody else - a symlink leading out
        # of the declaration entirely, a FIFO whose open would block until a reader appears, a directory
        # where a file belongs - so refuse it loudly rather than follow it. This is the standard Symlink
        # already holds when it refuses to replace a real file, applied to every battery. The declared
        # path is the only thing a fixture may touch.
        standing = self._standing()
        if standing not in ("", kind):
            raise FileExistsError(
                f"{self.path} is {standing}, not {kind}. Refusing to act through it - remove what "
                f"stands there or declare the path this fixture actually owns."
            )

    def _replace(self, content: str) -> None:
        # The atomic write. Build the whole new content in a sibling temp file, then rename it over the
        # path. A reader sees the old content or the new one and never a half-written one, a crash mid
        # write leaves the original standing and two fixtures racing the same path cannot interleave
        # halves of each other's writes into a corrupt file. The temp file is a SIBLING because
        # os.replace is only atomic within one filesystem and it is removed if anything fails, so a
        # failed write leaves no litter behind.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(handle, "w") as opened:
                opened.write(content)
            os.replace(temporary, self.path)
        except OSError:
            Path(temporary).unlink(missing_ok=True)
            raise
