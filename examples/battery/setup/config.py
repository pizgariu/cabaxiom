"""Configuration setup batteries - a key in a JSON file. Reconcile app or editor config to a desired
declaration, catch drift when something rewrites it and reverse the key cleanly."""
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, override

from cabaxiom import Drift

from ._base import Fixture

_MISSING: Any = object()


class JsonKey(Fixture):
    """A key in a JSON file that must hold a value. The key is a name or a path of names into nested
    objects (`("editor", "tabSize")`). Absent or different is drift, apply sets it - creating the file,
    its parents and any intermediate objects - prune removes just that key and footprint reports the
    current value if the key is there. The value round-trips as JSON, so it compares and writes exactly."""

    def __init__(self, path: str | Path, key: str | Sequence[str], value: Any) -> None:
        super().__init__(path)
        self._key: tuple[str, ...] = (key,) if isinstance(key, str) else tuple(key)
        self._value = value

    @property
    def _dotted(self) -> str:
        return ".".join(self._key)

    def _load(self) -> Any:
        # The one read every verb shares, so the ownership guard sits here once instead of on each.
        self._claim("a regular file")
        return json.loads(self.path.read_text()) if self.path.is_file() else {}

    def _get(self, data: Any) -> Any:
        node = data
        for name in self._key:
            if not isinstance(node, dict) or name not in node:
                return _MISSING
            node = node[name]
        return node

    def _write(self, data: Any) -> None:
        # Atomic, so two keys converging into one file cannot interleave halves and leave the caller
        # holding a document that is no longer valid JSON.
        self._replace(json.dumps(data, indent=2) + "\n")

    @override
    def _drift(self) -> list[Drift]:
        current = self._get(self._load())
        if current is _MISSING:
            return self._at(f"key {self._dotted} absent")
        if current != self._value:
            return self._at(f"key {self._dotted} differs")
        return []

    @override
    def _apply(self) -> list[Drift] | None:
        data = self._load()
        if self._get(data) == self._value:
            return None
        # Refuse to write into a document or through a branch, that is not an object. prune() already
        # holds this standard (it walks away from a non-object path rather than delete something else),
        # and apply must agree with its own teardown. Silently replacing a value with an object would
        # destroy data this step never owned and could never put back.
        if not isinstance(data, dict):
            raise TypeError(
                f"{self.path} holds a JSON {data.__class__.__name__}, not an object. JsonKey sets a key "
                f"inside an object, so it will not overwrite a document of another shape."
            )
        node = data
        for name in self._key[:-1]:
            if name not in node:
                node[name] = {}
            branch = node[name]
            if not isinstance(branch, dict):
                raise TypeError(
                    f"{self.path} holds {json.dumps(branch)} at {name!r}, not an object, so the key "
                    f"path {self._dotted} cannot be set without destroying it."
                )
            node = branch
        node[self._key[-1]] = self._value
        self._write(data)
        return self._at(f"key {self._dotted} set")

    @override
    def _prune(self) -> list[Drift]:
        data = self._load()
        node = data
        for name in self._key[:-1]:
            branch = node.get(name) if isinstance(node, dict) else None
            if not isinstance(branch, dict):
                return []                       # the path does not lead anywhere, nothing to remove
            node = branch
        if isinstance(node, dict) and self._key[-1] in node:
            del node[self._key[-1]]
            self._write(data)
        return []

    @override
    def _footprint(self) -> list[Drift]:
        current = self._get(self._load())
        return [] if current is _MISSING else self._at(f"key {self._dotted} = {json.dumps(current)}")
