---
name: mechanism-reasoning
description: Form, compare, and revise reaction-mechanism hypotheses using explicit species identities, atom mappings, elementary steps, alternatives, and falsifiers.
---

# ResearchAgent Mechanism Reasoning

[Chinese version](SKILL.zh-CN.md)

Use this Skill to define and challenge reaction-mechanism hypotheses, identify
elementary steps and competing pathways, or decide which observation would
distinguish alternatives. It reasons over inspected source outputs and explicitly cited research results; it does not
replace transition-state validation, IRC, or energetics.

Define species, composition, charge, spin or electronic state, atom mapping,
bond changes, environment, and reversibility explicitly. Put the current mechanism hypothesis in the Node proposal and predictions/falsifying observations in its plan. Explain support or conflict in Result conclusions with evidence. Independently compared approaches can use alternative_to. Research dependencies do not define chemical connectivity.

Record the observations, scientific criteria, unresolved questions and next steps with research_update using the existing node_id and a note. Publish a reusable conclusion with research_result, citing collected materials and stating limitations. A completed computation does not establish a scientific conclusion.

Separate species identity, elementary-step connectivity, saddle evidence,
energetics, kinetics, and robustness into questions that can fail independently.
Preserve competing mechanisms and unexpected results. When evidence challenges
the framing, revise the current proposal or create a related Node for an independent new question, preserving earlier results.

## References

- [reaction_mapping.md](../chemical-input/references/reaction_mapping.md) and
  [molecular_preparation.md](references/molecular_preparation.md): species,
  mapping, and input preparation.
- [pathway_model.md](references/pathway_model.md): pathway hypotheses and chemical
  connectivity.
- [mechanism_reflection.md](references/mechanism_reflection.md): distinguishable
  hypotheses and falsifiers.
- [strategy_reflection.md](references/strategy_reflection.md): reframing after
  repeated or unexpected results.
