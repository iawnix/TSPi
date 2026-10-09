# Name resolution

Prepare the chemical.resolve@1 Job with --name ORIGINAL, optionally --lookup-name NORMALIZED; use the generic preparation command described in the Skill.
Global --output selects the JSON file; --config accepts an absolute name-resolver TOML path.
Defaults read RESEARCH_AGENT_NAME_RESOLVER_CONFIG or RESEARCH_AGENT_INSTALL_ROOT/etc/name-resolver.toml.
Managed Jobs do not inherit Host environment variables. The installer binds the installed
resolver path in each local `structure.environment.RESEARCH_AGENT_NAME_RESOLVER_CONFIG`
entry in job.toml. Explicit bindings are preserved; remote targets need a target-local
configuration path. After changing a binding, prepare a new request before submitting.
Enabled PubChem/OPSIN backends retain request provenance, time, response digests and candidates.
Neutral water uses a versioned built-in rule without a network lookup. HTTP 404, rate limits
and network failures remain explicit diagnostics. resolved means one deterministic candidate;
ambiguous means multiple candidates or unspecified stereochemistry; draft is an unconfirmed
model candidate; unresolved means no usable result. Enumerate stereoisomers explicitly when
in scope. Do not interpret a network failure as proof that the chemical structure does not exist.
