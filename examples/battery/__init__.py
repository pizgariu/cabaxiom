"""Ready-made Steps for real domains - shipped as EXAMPLES, deliberately not as kernel API.

Three of them and each answers a question the kernel itself refuses to answer. `setup` declares a
development machine (directories, files, symlinks, a line in a profile, a key in a config). `repository`
reconciles one repository or a fleet, to an organisation standard, so the residual reads as a compliance
report. `data` puts a warehouse under contract - a schema, a table, a load, a freshness window, a quality
gate - and traces lineage by listening on what each step produced.

They live here rather than in the wheel because they are a DEMONSTRATION and a demonstration that ships
as public API is a promise nobody asked for. The kernel is domain-agnostic on purpose. The moment a
`Table` or a `Symlink` sits inside it, that claim needs an asterisk and every one of these would have to
be versioned and deprecated like the kernel around it.

Nothing here is imported by the kernel. Everything here imports the kernel through its public front door
and nothing deeper, which is what makes them honest examples - if a battery needed a private seam, the
seam would be the thing to fix."""
