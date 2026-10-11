"""Repository standards as desired state - a setting, a topic. Each is a Step, so a whole fleet of repos
reconciles at once, an empty residual PROVES every repo conforms and a non-empty one names the repos
that do not. Hand many repos' standards to one Reconciler and read the residual as a compliance report."""
from typing import override

from ..drift import Artifacts, Assessment, Changes, Drift, DriftItem, FlowAssessment, FlowOutcome
from ..step import Step
from ._github import GitHub


class _Standard(Step):
    """The data-flow bridge the repo standards share, the sibling of setup's Fixture. A standard reads and
    patches GitHub synchronously and ferries no artifacts, so the base adapts the kernel's async data-flow
    contract to the plain finding-returning shape each standard implements. A concrete standard overrides
    the underscored helpers and never touches the kernel contract."""

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
        return []

    def _apply(self) -> Changes:
        return None

    def _prune(self) -> list[Drift]:
        return []

    def _footprint(self) -> list[Drift]:
        return []


class RepoSetting(_Standard):
    """A repository setting on GitHub that must hold a value - `has_issues`, `allow_squash_merge`,
    `default_branch`. Reads the repo, drifts when the setting differs and patches it to converge. It
    ENFORCES, it does not tear down. A setting has no absent state to restore, so prune is a no-op."""

    def __init__(self, github: GitHub, repo: str, key: str, value: object) -> None:
        self._github = github
        self._repo = repo
        self._key = key
        self._value = value

    @override
    def _drift(self) -> list[Drift]:
        current = self._github.get(f"/repos/{self._repo}").get(self._key)
        if current == self._value:
            return []
        return [DriftItem(self._repo, f"{self._key} is {current!r}, want {self._value!r}")]

    @override
    def _apply(self) -> list[Drift] | None:
        if self._github.get(f"/repos/{self._repo}").get(self._key) == self._value:
            return None
        self._github.patch(f"/repos/{self._repo}", {self._key: self._value})
        return [DriftItem(self._repo, f"{self._key} set to {self._value!r}")]


class RepoTopic(_Standard):
    """A topic that must be present on a repo. GitHub stores topics as a set, so this is a genuine
    present-or-absent standard. apply adds the topic when missing, prune removes it, footprint reports
    it when present. The topic set is read and rewritten whole, the way the API models it."""

    def __init__(self, github: GitHub, repo: str, topic: str) -> None:
        self._github = github
        self._repo = repo
        self._topic = topic

    def _topics(self) -> list[str]:
        names = self._github.get(f"/repos/{self._repo}/topics")["names"]
        return list(names)

    @override
    def _drift(self) -> list[Drift]:
        return [] if self._topic in self._topics() else [DriftItem(self._repo, f"topic {self._topic!r} missing")]

    @override
    def _apply(self) -> list[Drift] | None:
        topics = self._topics()
        if self._topic in topics:
            return None
        self._github.put(f"/repos/{self._repo}/topics", {"names": [*topics, self._topic]})
        return [DriftItem(self._repo, f"topic {self._topic!r} added")]

    @override
    def _prune(self) -> list[Drift]:
        topics = self._topics()
        if self._topic not in topics:
            return []
        self._github.put(f"/repos/{self._repo}/topics", {"names": [name for name in topics if name != self._topic]})
        return []

    @override
    def _footprint(self) -> list[Drift]:
        return [DriftItem(self._repo, f"topic {self._topic!r} present")] if self._topic in self._topics() else []

