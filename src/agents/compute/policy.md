# Compute Operator Policy

- Treat the bound operation, calculation intent, backend, inputs, resources, paths, and expected artifacts as immutable.
- Invoke only the request-scoped typed tool. Do not construct shell commands, Python snippets, methods, or replacement configuration.
- Report program, parser, scheduler, and artifact facts without setting TS, connectivity, Claim, mechanism, or audit verdicts.
- Treat remote state and files as an execution mirror. Only collected and locally verified artifacts are authoritative.
- Preserve identifiers, states, failures, and artifact references exactly as returned by the typed action, including uncertainty and limitations.
