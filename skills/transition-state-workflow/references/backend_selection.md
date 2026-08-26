# Backend Selection

The Root Agent selects a backend from the scientific question, uncertainty,
system size, electronic structure, desired observable, available artifacts,
cost, and live environment. The capability catalog is not a priority list.

Consider:

- whether the method can represent charge, spin, excited state, metal center,
  multireference character, solvent, and constraints;
- whether the task produces the observation needed to discriminate Claims;
- candidate quality and atom mapping;
- whether lower-cost exploration is scientifically informative rather than only
  cheaper;
- whether a higher-level recalculation is needed for robustness;
- live local/remote software and scheduler readiness.

Gaussian is a first-class candidate generator for direct TS optimization,
relaxed scans, QST, and follow-up characterization. xTB/CREST can efficiently
explore conformers and rough paths. ASE NEB can provide path images. QBICS can
address crossing searches. None is universally first.

Record the method choice and falsifiable purpose in the ResearchNode/Claim. If a
method changes, preserve the prior intent and use a recalculation record or a
new Node when the scientific objective changes.
