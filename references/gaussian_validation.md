# Gaussian Validation

Gaussian TS/Freq validation should be node-scoped.

Record:

- input path;
- output path;
- method and basis;
- charge and multiplicity;
- termination summary;
- number of imaginary frequencies;
- whether the imaginary mode matches the target elementary step;
- parsed energy when available.

One imaginary frequency is necessary but not sufficient for an accepted TS. The
mode must support the current phase claim, and connectivity must be validated in
a separate evidence layer.
