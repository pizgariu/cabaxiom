"""The refusals this kernel raises, named by what went wrong rather than by what it happened to hit.

THREE UNRELATED BASES AND NO SHARED ROOT ABOVE THEM, which is the decision worth arguing for. A caller
who wants to hear about a malformed declaration has no business being handed a misconfigured axis, so a
common ancestor would let one `except` swallow both. The three answer to different people - a Malformed
is the author of a Step, an Unresolvable is whoever assembled the run, a Misconfigured is whoever wired
the strategies - and giving them one parent would be modelling the fact that they are all errors, which
is the least interesting thing about them.

EVERY ONE SUBCLASSES THE BUILT-IN IT REPLACES, so nothing written against the previous release breaks. An
`except ValueError` still catches a cycle, an `assertRaises(TypeError)` still catches a bad slot and a
caller who wants the finer answer opts into it by naming the finer type."""


class Malformed(TypeError):
    """The declaration has the wrong SHAPE - a bare class where a one-tuple belongs, a string where a set
    of labels belongs, an instance where a type does.

    A TypeError, because that is what it is. The classic case is the forgotten comma, `expects = (Reactor)`
    is the class Reactor and not a one-tuple, which would otherwise surface deep inside the derivation as
    something unrecognisable. Raised at class definition where it can be and at construction where the
    value is only known then."""


class Unresolvable(ValueError):
    """The declaration is well formed and still cannot become a run.

    A ValueError, because the shapes are all right and the VALUES cannot be reconciled. Everything under
    it is a distinct reason, so a caller can tell a cycle from a missing prerequisite without reading a
    message, since a message can change without breaking anybody's handling."""


class Cycle(Unresolvable):
    """The edges close a loop, so no order exists. Names the steps that could not be laid out."""


class Coverage(Unresolvable):
    """An Ordering did not hand back every supplied step exactly once.

    The strategy is the kernel's own extension point, so a custom one that drops or duplicates a step is
    caught the moment it answers rather than showing up later as a step that silently never ran."""


class Presence(Unresolvable):
    """Something named is not in the run - a hard edge pointing at an absent step, a scope naming a type
    nothing supplied, a forecast asked about a step the run does not contain.

    The one refusal a soft edge deliberately does not raise. Soft means trust the world if it is absent,
    hard means say so. This is the word for hard."""


class Identity(Unresolvable):
    """Two steps in one run that identity cannot tell apart.

    IDENTITY IS THE DEPENDENCY CURRENCY. Every structure the kernel derives is keyed by step, so two steps
    that compare equal collapse into ONE node and the run silently reconciles a smaller world than it was
    handed."""


class Misconfigured(ValueError):
    """An AXIS was handed a value it cannot work with - a retry budget below one, a deadline in the past,
    a pass ceiling of zero.

    Nothing about the steps is wrong here, which is exactly why it is not an Unresolvable. The declaration
    would resolve fine while the strategy wired around it will not."""
