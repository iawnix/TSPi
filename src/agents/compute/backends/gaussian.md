# Gaussian Backend Policy

- Gaussian supports both candidate generation and later validation. Candidate
  uses include relaxed scans encoded in the input route, QST searches, direct
  TS optimization, intermediate optimization, and single-point ranking.
- Report normal or error termination, optimization and frequency parser facts, route mismatches, and bounded failure diagnostics.
- A normal termination or one imaginary frequency is a program fact, not a TS, connectivity, or mechanism verdict.
- A Gaussian result produced under a `candidate_search` node remains
  candidate-level even when the same job also printed frequencies. Gate
  ownership comes from the validation node and registered evidence, not the
  backend name or route convenience.
