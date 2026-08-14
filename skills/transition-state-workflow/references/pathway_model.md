# Pathway Claims

Represent a multi-step route with explicit versioned Claims rather than a
special workflow branch. A parent pathway Claim may cite child elementary-step
or intermediate Claims through its free-form `details` and normal Claim refs.
The Root Agent decides the decomposition and ordering.

Each elementary-step Claim should state its endpoint identity and required
transition-state Gates. Intermediate Claims should state the structure or basin
identity that connects adjacent steps. Register facts and evaluate the relevant
TS/Freq, connectivity, stereochemistry, endpoint, intermediate, or electronic
Gates separately.

For final route acceptance, create Evidence whose facts include the complete
step/intermediate audit and evaluate `pathway_audit`. The
`accepted-pathway/1` audit policy requires a passing `pathway_audit` result for
the same target Claim. A supporting child step does not by itself accept the
parent pathway.

If the strict pathway decision is negative or inconclusive, record that fact
and the remaining alternatives. The Kernel does not decide whether another
scientifically meaningful route should be explored.
