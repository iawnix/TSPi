# Candidate Generation

Candidate generation creates hypotheses and artifacts for later validation.
For fresh endpoint-based searches, candidate generation should usually be
parented to an explicit closed `n000` endpoint/preflight node rather than to
workspace-level endpoint evidence alone.

Valid candidate sources include:

- constrained scans;
- NEB or string methods;
- dimer searches;
- QST-like guesses;
- reaction-network exploration;
- diabatic or crossing-point candidates when chemically justified.

A candidate is not a TS proof. Register candidates as evidence, then open a
`tsfreq_validation` node for Gaussian or another appropriate validation route.
