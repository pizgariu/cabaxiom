"""The suite's one shared root. It is why `from support import ...` resolves from every subdirectory.

pytest puts the directory of the first conftest it finds on sys.path (rootdir-relative "rootdir" import
mode), so the shared doubles in support.py are importable from unit/, property/, integration/ and the rest
without every file spelling a path. The file is otherwise empty on purpose - fixtures live next to the
tests that use them."""
