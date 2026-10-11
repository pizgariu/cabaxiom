"""Filesystem setup batteries - a directory and a file. Each is a Step, so a declared setup converges,
self-verifies by re-probing, proves idempotent under Idempotence and reverses under prune."""
from pathlib import Path
from typing import override

from ..drift import Drift
from ._base import Fixture


class Directory(Fixture):
    """A directory that must exist. Missing is drift, apply creates it and its parents, prune removes
    it only when EMPTY - it never deletes what it did not put there - and footprint reports it if
    present. A File or Symlink that lives inside it is ordered after it with `expects` or `needs`."""

    @override
    def _drift(self) -> list[Drift]:
        self._claim("a directory")
        return [] if self.path.is_dir() else self._at("directory missing")

    @override
    def _apply(self) -> list[Drift] | None:
        self._claim("a directory")
        if self.path.is_dir():
            return None
        self.path.mkdir(parents=True, exist_ok=True)
        return self._at("directory created")

    @override
    def _prune(self) -> list[Drift]:
        # rmdir only removes an empty directory, so a teardown never nukes contents a later step or the
        # user put there. A non-empty directory survives and says so, which keeps the residue honest.
        self._claim("a directory")
        if not self.path.is_dir():
            return []
        try:
            self.path.rmdir()
        except OSError:
            return self._at("directory not empty, left standing")
        return []

    @override
    def _footprint(self) -> list[Drift]:
        self._claim("a directory")
        return self._at("directory present") if self.path.is_dir() else []


class File(Fixture):
    """A file that must hold EXACT content. Missing or different content is drift, apply writes it
    (creating parent directories so a bare declaration just works), prune deletes it and footprint
    reports it if present. Declare a Directory before it with `expects` when the ordering is the point."""

    def __init__(self, path: str | Path, content: str) -> None:
        super().__init__(path)
        self._content = content

    @override
    def _drift(self) -> list[Drift]:
        self._claim("a regular file")
        if not self.path.is_file():
            return self._at("file missing")
        if self.path.read_text() != self._content:
            return self._at("content differs")
        return []

    @override
    def _apply(self) -> list[Drift] | None:
        self._claim("a regular file")
        if self.path.is_file() and self.path.read_text() == self._content:
            return None
        self._replace(self._content)
        return self._at("file written")

    @override
    def _prune(self) -> list[Drift]:
        self._claim("a regular file")
        if not self.path.is_file():
            return []
        self.path.unlink()
        return []

    @override
    def _footprint(self) -> list[Drift]:
        self._claim("a regular file")
        return self._at("file present") if self.path.is_file() else []


class Symlink(Fixture):
    """A symlink that must point at a given target - the dotfile move, `~/.vimrc` linked at your repo's
    `vimrc`. Missing or pointing elsewhere is drift. apply creates it, repointing a wrong link and
    creating parents but REFUSES to replace a real file that happens to sit at the path (it raises
    rather than delete what it did not put there). prune removes the link, never the target."""

    def __init__(self, path: str | Path, target: str | Path) -> None:
        super().__init__(path)
        self._target = Path(target)

    @override
    def _drift(self) -> list[Drift]:
        if self.path.is_symlink():
            return [] if self.path.readlink() == self._target else self._at("symlink points elsewhere")
        if self.path.exists():
            return self._at("path is a real file, not a symlink")
        return self._at("symlink missing")

    @override
    def _apply(self) -> list[Drift] | None:
        if self.path.is_symlink():
            if self.path.readlink() == self._target:
                return None
            self.path.unlink()
        elif self.path.exists():
            raise FileExistsError(f"{self.path} is a real file, refusing to replace it with a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.symlink_to(self._target)
        return self._at("symlink created")

    @override
    def _prune(self) -> list[Drift]:
        if not self.path.is_symlink():
            return []
        self.path.unlink()
        return []

    @override
    def _footprint(self) -> list[Drift]:
        return self._at("symlink present") if self.path.is_symlink() else []


class LineInFile(Fixture):
    """A single line that must be present in a file, idempotent and without duplicates - a shell
    profile export, a `.gitignore` entry. Absent is drift, apply appends it (creating the file and
    parents), prune removes every copy, footprint reports it if present. Order it after the File or
    Directory that owns the path when the ordering matters."""

    def __init__(self, path: str | Path, line: str) -> None:
        super().__init__(path)
        # ONE line, checked at construction against the same splitter the membership test uses. A line
        # holding a break is a block and a block can never be found again by a line-wise search, so the
        # step would report drift and append it afresh on every pass, growing the file forever and never
        # converging. Declaring the guard here means the mistake surfaces at build time, not as a file
        # that quietly doubles under a Controller.
        if line.splitlines() != [line]:
            raise ValueError(
                f"LineInFile takes ONE line, got {line!r}. A line break splits it into a block this "
                f"step could never find again, so it would append it on every pass. Declare one "
                f"LineInFile per line."
            )
        self._line = line

    def _lines(self) -> list[str]:
        # The one read every verb shares, so the ownership guard sits here once instead of on each.
        self._claim("a regular file")
        return self.path.read_text().splitlines() if self.path.is_file() else []

    @override
    def _drift(self) -> list[Drift]:
        return [] if self._line in self._lines() else self._at("line absent")

    @override
    def _apply(self) -> list[Drift] | None:
        lines = self._lines()
        if self._line in lines:
            return None
        self._replace("\n".join([*lines, self._line]) + "\n")
        return self._at("line added")

    @override
    def _prune(self) -> list[Drift]:
        lines = self._lines()
        if self._line not in lines:
            return []
        kept = [line for line in lines if line != self._line]
        self._replace("\n".join(kept) + ("\n" if kept else ""))
        return []

    @override
    def _footprint(self) -> list[Drift]:
        return self._at("line present") if self._line in self._lines() else []

