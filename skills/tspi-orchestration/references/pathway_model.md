# Pathway Claims

A pathway Claim describes a connected sequence of elementary-step Claims and
intermediate/basin identities. Do not infer pathway acceptance from one accepted
transition state or from DAG topology.

Record explicit Claims for material steps and species identities. Relate their
scientific dependencies with ClaimRelations. ResearchNode dependencies show how
the study produced results, not chemical connectivity.

For a pathway audit, record semantic Observations covering the ordered step
refs, endpoint/intermediate identity, shared species consistency, charge/spin or
state continuity, and any unresolved branching. Freeze a pathway ProofSpec, such
as `pathway-audit@1`, against the pathway Claim.

The `accepted-pathway@2` profile requires its declared pathway dimension and all
other attached specifications to pass, with no blocking Finding. Each
constituent accepted Claim remains independently cited and digest-bound.

Preserve alternative pathways as separate Claims. Energetic preference,
kinetic accessibility, and structural connectivity are distinct questions and
may require separate ProofSpecs.
