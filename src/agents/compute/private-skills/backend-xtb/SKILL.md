---
name: ts-backend-xtb
description: Private xTB execution guidance for the isolated TS backend operator.
---

# xTB Backend

- Treat charge, UHF state, solvent, method, optimization level, and input geometry as immutable.
- Report convergence, energy, geometry, and program-failure facts from typed results only.
- xTB output may screen or refine candidates but does not establish final TS/Freq or connectivity support.
- Keep all authoritative artifacts in the local attempt directory after collection.
