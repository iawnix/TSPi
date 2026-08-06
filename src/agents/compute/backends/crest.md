# CREST Backend Policy

- CREST is a distinct conformer-search backend even though it invokes xTB internally.
- Preserve charge, UHF state, method, solvent, optimization level, search level, thread count, input geometry, and ensemble provenance.
- Report termination, artifact completeness, conformer count, best-structure energy, relative-energy coverage, and ensemble-count consistency as program facts.
- A completed CREST search generates candidate structures only; it does not select an endpoint, establish a global minimum, validate a TS, or prove connectivity.
