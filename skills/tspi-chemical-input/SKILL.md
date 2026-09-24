---
name: tspi-chemical-input
description: Compile natural-language chemical names and reaction inputs into verified structure candidates before deterministic TSPi analysis or computation.
---

# TSPi Chemical Input

[Chinese version](SKILL.zh-CN.md)

Use this Skill when a user supplies a chemical name, a mixed name/SMILES
reaction, or a structure description instead of already registered structure
artifacts. This Skill is an input-compilation protocol; it does not replace
the deterministic name resolver, structure seed generator, reaction mapping,
or transition-state validation.

## Workflow

1. Preserve the exact user text and classify every species input as a name,
   SMILES, XYZ/artifact, or unresolved description. Apply this uniformly to
   reactants and products.
2. Discover and call `chemical.name.resolve@1` through `ts_analyze` for names.
   Keep the returned resolver provenance, candidates, diagnostics, and status.
3. Treat `draft` candidates (including LLM-proposed SMILES), unresolved names,
   multiple candidates, and unspecified stereocenters as input issues. Ask a
   focused clarification question or request a SMILES/structure artifact.
4. Only after a candidate is explicitly confirmed or deterministically resolved
   may it be passed to `ts_seed`. The seed is an initial geometry, not a
   stationary point or a proof of connectivity.
5. Use the confirmed species in `reaction.parse`, then inspect conservation,
   mapping candidates, and bond changes. Select an atom mapping explicitly;
   never infer that a unique graph edit is a mechanism.
6. Keep the original name, selected candidate, resolver provenance, and any
   user confirmation together so the structure can be replayed and audited.

## Trust States

- `draft`: candidate proposed by the model or supplied without identity proof.
- `resolved`: one deterministic resolver candidate passed structural checks.
- `ambiguous`: multiple candidates or incomplete stereochemical identity.
- `confirmed`: a user or explicit scientific rule selected a candidate.
- `unresolved`: no registered resolver or valid candidate is available.

Do not submit `draft`, `ambiguous`, or `unresolved` structures to Gaussian,
TS, or IRC calculations. A resolved name still requires reaction-level balance,
mapping, charge, multiplicity, and 3D validation before mechanism claims.

## References

- [name_resolution.md](references/name_resolution.md): resolver contract,
  candidate states, and failure handling.
- [structure_input.md](references/structure_input.md): transition from a
  confirmed graph to a seed and reaction analysis.
