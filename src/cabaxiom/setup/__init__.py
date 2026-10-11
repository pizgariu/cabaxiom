"""cabaxiom.setup - batteries for declaring a development environment as desired state.

Not part of the kernel. Import it explicitly. Each battery is a Step, so a declared setup CONVERGES
to the machine you want, SELF-VERIFIES by re-probing, proves IDEMPOTENT under Idempotence (a second
run is a clean no-op) and REVERSES under prune. Compose the batteries with `expects` and `needs` like
any Step and hand the lot to a Reconciler.

    from cabaxiom import Reconciler
    from cabaxiom.setup import Directory, File

    class ConfigDir(Directory):
        def __init__(self): super().__init__("~/.config/app")

    Reconciler((Directory("build"), File("build/marker", "ready"))).converge()
"""
from .config import JsonKey
from .filesystem import Directory, File, LineInFile, Symlink

__all__ = ["Directory", "File", "Symlink", "LineInFile", "JsonKey"]

