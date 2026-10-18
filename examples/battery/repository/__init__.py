"""cabaxiom.repository - reconcile a repository or a whole fleet to an organisation standard.

Not part of the kernel. Import it explicitly. Each standard is a Step, so many repos' standards go to
ONE Reconciler and the residual reads as a compliance report - empty PROVES every repo conforms, a
non-empty residual NAMES the repos that do not and Isolation narrows a stubborn fleet to the one
standard still failing. The GitHub client is stdlib urllib only and its transport is injectable so a
run rehearses offline. For file standards - a required LICENSE, a gitignore entry - reach for the
batteries in cabaxiom.setup (File, LineInFile, JsonKey), which operate on a checked-out repo path.

    from cabaxiom import Reconciler
    from cabaxiom.repository import GitHub, RepoSetting, RepoTopic

    gh = GitHub(token)
    fleet = [RepoSetting(gh, repo, "has_issues", True) for repo in ("acme/api", "acme/web")]
    residual = Reconciler(fleet).converge()   # empty means the fleet conforms, proven by re-probe
"""
from ._github import GitHub
from .standards import RepoSetting, RepoTopic

__all__ = ["GitHub", "RepoSetting", "RepoTopic"]
