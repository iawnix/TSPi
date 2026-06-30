# Candidate Generation

Candidate generation creates artifacts that test a structured mechanism
hypothesis. It does not create free-floating candidates.

For fresh endpoint-based searches, candidate generation must be parented to a
closed `n000` endpoint/preflight node and must carry:

```json
{
  "hypothesis_ref": {
    "hypothesis_id": "hyp_0001",
    "prediction_ids": ["pred_mode_001", "pred_conn_001"]
  }
}
```

The candidate-generation rationale should state which parts of the hypothesis
drive the strategy:

- reaction-center forming and breaking bonds;
- transferred atoms such as H/proton candidates;
- concerted vs stepwise elementary-step model;
- charge and multiplicity;
- ground-state, open-shell, spin-crossing, or excited-state assumptions;
- whether PT, ET, HAT, PCET, radical character, or spin-density changes are
  expected or only possible.

Reactant/product endpoints define the target connectivity basins for later
validation. They do not by themselves determine the TS-search method. Do not
default to QST2/QST3 merely because reactant and product structures are
available. Prefer QST2/QST3 only when the endpoints are optimized, the atom map
is reliable, the conformations are compatible, and the hypothesis is a single
elementary step without an evident intermediate. Otherwise compare the
reaction-center model against constrained or relaxed scans, NEB/string, dimer
or eigenvector-following, conformer/intermediate searches, or other candidate
strategies before choosing a route.

Common strategy layers:

- constrained scans for simple reaction-center coordinates;
- NEB or string methods for coupled forming/breaking coordinates;
- conformer or pose generation when endpoint geometry is uncertain;
- intermediate generation for stepwise hypotheses;
- dimer searches or QST-like guesses when the hypothesis and endpoint
  compatibility justify that strategy;
- diabatic or crossing-point candidates only when the hypothesis justifies
  non-adiabatic or spin-surface exploration.

A candidate is not a TS proof. Register candidates as evidence with
`quality.hypothesis_id`, then open a `tsfreq_validation` node for Gaussian or
another appropriate validation route.
