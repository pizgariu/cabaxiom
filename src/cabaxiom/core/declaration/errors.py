"""The refusals, in one place - what the kernel raises when it will not proceed and who each one is for.

THREE BASES, DELIBERATELY UNRELATED. There is no shared root here and that absence is the design. A caller
who wants to hear about one of these has no business being handed the other two. Each base answers a
different question about who is at fault and what they would change to fix it.

- `Malformed` is a TypeError. The declaration has the wrong SHAPE - a string where a set of labels belongs,
  a bare class where a one-tuple does. Caught at class definition or at construction, before any world is
  read. You fix it by editing the declaration.
- `Unresolvable` is a ValueError. The declaration is well FORMED and still cannot become a run - a cycle,
  a prerequisite nobody supplied, a shape the chosen worker may not walk. You fix it by changing what you
  declared or what you handed the reconciler.
- `Misconfigured` is a ValueError. An AXIS was handed a value it cannot work with - a negative delay, a
  zero poll. Nothing about your steps is wrong. You fix the argument you passed to one small object.

EVERY ONE SUBCLASSES A BUILT-IN. That is what makes this change free to adopt. The kernel raised bare
ValueError and TypeError from these sites for its whole life, so `except ValueError` and every
`assertRaises(ValueError)` written against it keeps working unchanged. The names are additive. They let a
caller who WANTS to tell a cycle from a bad backoff do it by type instead of by matching message text,
which is the alternative this kernel already named as the wrong one (see `Unpublished`).

WHAT IS NOT HERE and why. `Cancelled`, `Deferred` and `Skew` live with the cancellation axis. They are
BaseExceptions because they are SIGNALS a run sends itself rather than refusals, so they must escape a domain's
own `except Exception`. `Unpublished` lives with the enclave. It is raised from a running hook rather than
while resolving, so the Retry axis dispatches on it and it belongs to that story. A refusal, by contrast,
never reaches a retry - nothing here is raised once a run is under way."""


class Malformed(TypeError):
    """A declaration whose SHAPE is wrong, refused before it can mean anything.

    The container is not what the slot takes (a class where a one-tuple belongs, the classic forgotten
    comma) or a label set is a bare string, which is the silent one - a string iterates into single
    characters, so `provides = "database"` would offer six capabilities named d, a, t, b, s and e and every
    match would miss without a word. Raised by `Step.__init_subclass__` at class definition where it can be,
    and by the Graph's construction guard for the per-instance slots no class hook can see."""


class Unresolvable(ValueError):
    """A well-formed declaration the kernel cannot turn into a run, refused at construction.

    Everything under this base is caught before a single step is touched, which is the whole point - the
    kernel would rather refuse a run than start one it cannot finish honestly. The leaves name the specific
    fault for a caller who wants to tell them apart, while catching the base catches every one."""


class Cycle(Unresolvable):
    """The dependency edges close a loop, so no order exists. Names the steps that could not be laid out."""


class Coverage(Unresolvable):
    """An Ordering did not return every supplied step exactly once - it dropped one or doubled one.

    Refused because the alternative is worse than a crash. A dropped step converges a SMALLER world with no
    error anywhere, so the run reports clean about a declaration it never fully read."""


class Seating(Unresolvable):
    """A partition seats a step where its own shape's rule forbids - a dependency sharing a group with its
    dependent under a shape that fans that group, so the two would run at once and the edge would be
    ignored while the run still reported clean."""


class Pairing(Unresolvable):
    """A worker and a shape that must not be composed - the worker overlaps where the shape's rule allows a
    dependency to sit, so a step could run beside its own prerequisite. Raised by `RunMode.resolve`, which
    asks the PAIR rather than the worker's own class, so a decorator cannot launder the mismatch."""


class Presence(Unresolvable):
    """A hard edge names something the run does not contain - `requires` or `mandates` naming an absent
    class, `demands` a capability nobody provides, `needs` an instance that was never supplied.

    The soft counterparts trust an absent name and derive a dead end instead, which is why this is its own
    refusal rather than a fact about the derivation. It fires the moment membership is final."""


class DataFlow(Unresolvable):
    """A step consumes an artifact key no prerequisite of it produces.

    The DATA plane's own refusal, deliberately not an edge kind - declaring a key creates no order. The
    payload is mounted from a step's DIRECT prerequisites, so a key nothing upstream produces arrives as an
    absent entry the hook cannot tell from a real one, so the run reports clean against a world nobody
    supplied. A producer sitting two hops up or beside rather than above is exactly as absent."""


class Identity(Unresolvable):
    """Two steps in one run that are not distinguishable by identity - the same instance handed twice or a
    decorator like `dataclass(eq=True)` making two of them compare equal.

    Identity IS the kernel's dependency addressing. Every derived structure is keyed by instance, so two
    equal steps collapse into ONE graph node and the run would be refused blaming an Ordering that did
    nothing wrong."""


class Misconfigured(ValueError):
    """An axis handed a value it cannot work with - a negative delay, a zero poll, a byte ceiling below one.

    Nothing about the steps is wrong here, which is why this is not an `Unresolvable`. The declaration was
    never reached. One small object was constructed with an argument outside its own domain and says so
    where it is built rather than misbehaving quietly at the moment it is finally used."""
