# QBICS dMECP Candidate Generation

Use this for QBICS `dmecp` setup, execution, and triage. It is a candidate-generation route, not final TS validation.
For structured mechanism-analysis records from dMECP branches, read
`references/mechanism_analysis_sources.md`; dMECP can support fragment-state and
reaction-center hypotheses but does not by itself validate an accepted TS.

## When To Use

Prefer dMECP for AB+C=A+BC-like atom transfer, substitution, or bond switching where reactant and product diabatic states have clear fragment charge/spin definitions.

Use caution for intramolecular proton transfer, HAT/PCET, oxygen-site rearrangement, or resonance-equivalent endpoints. In those systems, fragment definitions are mechanism hypotheses and must be reflected on if they fail.

## Required Input Checks

- One starting complex geometry in `mol`; dMECP does not need `mol2`.
- `scf type u`.
- Total `charge` and `spin2p1` match the whole system.
- Every atom appears exactly once across all `frag1` lines and exactly once across all `frag2` lines.
- Fragment charges sum to total charge for both `frag1` and `frag2`.
- Fragment spin multiplicities are chemically plausible.
- Do not mix `frag` and `orb` state definitions unless deliberate; `orb1/2` takes priority.

## Minimal Input Pattern

```text
basis
    def2-svp
end

mol
    <coordinates>
end

scf
    type     u
    charge   <total_charge>
    spin2p1  <total_multiplicity>
end

mecp
    num_steps   200
    energy_cov  1.E-5
    grad_cov    1.E-3
    dr_cov      1.E-3
    # Reactant diabatic state.
    frag1 <charge> <spin> <atom_range>
    frag1 <charge> <spin> <atom_range>
    # Product diabatic state.
    frag2 <charge> <spin> <atom_range>
    frag2 <charge> <spin> <atom_range>
end

task
    dmecp b3lyp
end
```

Use `pseudopotential def2-ecp` when the selected def2 basis requires ECPs for heavy atoms.

## Outputs To Preserve

- `<prefix>-mecp.xyz`: latest/final candidate structure.
- `<prefix>-mecp-traj.xyz`: dMECP trajectory.
- `<prefix>.mwfn`, `<prefix>-ref.mwfn`, and logs if present.
- Full QBICS log, including host, SCF diagnostics, `<S^2>`, and termination text.

Run QBICS from `nodes/<node_id>/outputs` or a node-local scratch directory with
final artifacts copied back into `nodes/<node_id>/outputs`. QBICS writes logs,
candidate structures, trajectories, `.mwfn` files, and restart-like artifacts
relative to its current working directory; running it from the workspace root
mixes branches and breaks explorer provenance. Large scratch may be excluded
from mirror sync, but the evidence-bearing log and candidate geometry must be
node-scoped.

Prefer the node-scoped wrapper for direct QBICS invocations:

```bash
python /home/iaw/.codex/skills/transition-state-workflow/scripts/ts_node_exec.py \
  --workspace /path/to/tssearch_system \
  --node-id n490_qbics_dmecp_candidate \
  -- qbics-linux-cpu-mpi ../inputs/qbics_input.inp
```

## Triage

For each branch:

- parse convergence against `energy_cov`, `grad_cov`, and `dr_cov` when available;
- inspect final and trajectory reaction-center bond lengths;
- check whether the candidate collapsed to reactant/product or wrong atom transfer;
- inspect `<S^2>` for open-shell branches;
- record `claim_status=candidate_found` only for a usable candidate geometry;
  use `claim_status=rejected` with `outcome=chemical_failure`,
  `outcome=wrong_endpoint`, or `outcome=wrong_mode` for chemically refuted
  branches; use `claim_status=not_evaluated`, `outcome=numerical_failure`, and
  a diagnostic `outcome_code` for computational failures.

If QBICS writes `<prefix>-mecp.xyz` after an SCF failure, close the node with:

```text
claim_status=not_evaluated
outcome=numerical_failure
outcome_code=qbics_scf_nonconverged_but_candidate_written
```

Such a structure may be used as a Gaussian initial guess only after explicit caveat.

## Common Failures

| Symptom | Likely cause | Tree action |
|---|---|---|
| `SCF does NOT converge` | unstable diabatic state, poor guess, bad fragment model | close or branch with new fragments/SCF settings |
| `<S^2>` far from expected | spin contamination or state mixing | mark `spin_contamination_or_state_mixing` |
| no candidate geometry | SCF failed before geometry step | close branch |
| candidate endpoint-side | fragment hypothesis does not locate barrier | close as collapsed endpoint |
| candidate n210-like but nonconverged | usable only as Gaussian guess | create Gaussian validation child |

## Required Reflection

The reflection must say whether dMECP was chemically appropriate for this mechanism. For noncanonical dMECP cases, explain whether failure points to a wrong fragment-state model, state mixing, endpoint non-distinctness, or a reaction better treated by QST/NEB/dimer/scan.
