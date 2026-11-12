# Contributing

## Getting it running

```
pip install -e ".[dev]"
pytest                      # the suite, with coverage
```

Python 3.12 is the floor. `requires-python` in `pyproject.toml` is the one place that says so.

## The gate

Everything below has to pass before a commit lands.

```
ruff check .
mypy                               # strict, the kernel and the batteries, set in pyproject
lint-imports                       # the four layers point one way
pytest                             # 100% coverage is enforced, not aspired to
```

Coverage is a gate rather than a metric. A line the suite cannot reach is a line to delete or a case to
write. `# pragma: no cover` is for code that genuinely cannot run in a test, never for code nobody got
round to covering.

## What 1.0.0 froze

The forty-three names `cabaxiom` exports will not move, change signature or change meaning inside the 1.x
line. A change to what one of them is documented to do is a 2.0.0 conversation rather than a pull request.
A fix that makes one do what its documentation already says is an ordinary pull request.

`cabaxiom.core` and `cabaxiom.laboratory` are public and carry no such promise, so a name there can move in
a minor. [MIGRATING.md](MIGRATING.md) says which is which. A name graduates to the door when it has been
steady long enough to carry the promise, which is what the minors after the freeze are for.

## What a change looks like here

**A defect gets an entry in the same commit.** Every closed defect is written up with what it was, the
smallest thing that reproduced it, why nothing caught it and what the fix does. Write the entry against the
tree the fix ships in rather than from memory.

**A defect gets a test that went red first.** Plant the test, watch it fail on the unfixed tree, then fix.
A regression test that was never red proves nothing about the defect it names.

**A comment says the COST or the LIMIT.** How long, how many, what is NOT promised, which trade was taken.
It does not narrate what the line below it does, since the line already says that. A commit hash is never a
comment - describe the defect's shape, because a hash rots and tells a reader nothing.

**A refusal says what to write instead.** `Step.__init_subclass__` and the front door's `__getattr__` are
the house precedents. A refusal a reader cannot act on is a defect here.

**One commit, one thing.** The subject is one imperative line with no body and no trailer. The reasoning
lives in the changelog entry. No colon and no semicolon in it.

## Prose

The pages and the comments are read as much as the code, so they get the same care.

- No em dash and no en dash anywhere. A plain hyphen, a comma or a rewritten sentence.
- No semicolon as punctuation in prose, including inside comments, docstrings and error messages.
- No comma before `and`, `but` or `or` joining two halves of a sentence. No Oxford comma either.
- A number a page spells out is pinned in the suite, because a page cannot count and a reader should not
  have to.

## Where things live

| | |
|---|---|
| `benchmarks/` | the operation counts `tests/contract/test_cost.py` gates, plus their wall time |
| `docs/` | `architecture.md`, which is who holds whom and how a converge runs |
| `examples/` | runnable scripts, each one run to a clean exit by the suite |
| `src/cabaxiom/core/` | the kernel, four layers whose arrows `lint-imports` enforces |
| `src/cabaxiom/laboratory/` | the proofs and the rigs, which the kernel may never import |
| `tests/` | sorted by LEVEL - unit, property, integration, contract, battery, acceptance |

`benchmarks/` and `docs/` beyond `architecture.md` stay in the repository and out of the distribution. What
an sdist owes whoever unpacks it is the ability to rebuild the wheel and run the suite, which is the line
that decides what ships.
