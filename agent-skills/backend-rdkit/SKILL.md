---
name: ts-backend-rdkit
description: Private RDKit structure and conformer guidance for an isolated TS backend operator.
---

# RDKit Backend

- Use RDKit only through a bound typed adapter with explicit molecule, charge, stereochemistry, seed, and conformer settings.
- Preserve atom mapping and declared stereochemistry. Report sanitization, embedding, force-field, and conformer facts separately.
- A generated or minimized conformer is a structure artifact, not evidence of TS character or pathway connectivity.
- Never infer missing stereochemistry or silently replace failed structures.
