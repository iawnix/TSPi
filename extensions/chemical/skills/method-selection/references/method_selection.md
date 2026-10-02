# Backend Selection

The Root Agent selects a backend from the scientific question, uncertainty,
system size, electronic structure, desired observable, available artifacts,
cost, and live environment. Use the capability catalog to check accepted tasks
and parameters.

Consider:

- whether the method can represent charge, spin, excited state, metal center,
  multireference character, solvent, and constraints;
- whether the task produces the Finding needed to discriminate Claims;
- candidate quality and atom mapping;
- whether lower-cost exploration is scientifically informative rather than only
  cheaper;
- whether a higher-level recalculation is needed for robustness;
- live local/remote software and scheduler readiness.

Gaussian is a first-class candidate generator for direct TS optimization,
relaxed scans, QST, and follow-up characterization. xTB/CREST can efficiently
explore conformers and rough paths. The registered `ase.neb` capability uses
ASE path optimization with xTB energies and forces by default, and can
explicitly select the Gaussian CLI calculator for per-image energies and
forces. External DMECP workflows
can address crossing searches. Choose their order from the current research question.

Record the method choice and falsifiable purpose in the ResearchNode/Claim. If a
method changes, preserve the prior intent and use a recalculation record or a
new Node when the scientific objective changes.
