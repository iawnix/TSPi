# Planning and revisiting research questions

Use this reference for compound research or when evidence changes the next useful action. Node relations organize questions; local plans describe methods. User Task control remains in the task tools.

## Choose a useful question size

A question deserves its own Node when it can have an independently interpreted conclusion, be pursued separately, or supply evidence to several other questions. A different command, parameter or initial structure alone is not a new question. Build the known useful questions now; expand the graph when a distinct question emerges.

| Study | Useful organization | Attempts within a question |
| --- | --- | --- |
| Molecular property | One property question | Input preparation, convergence repair, repeat calculation |
| Competing reaction paths | Separately investigated paths, shared method checks, comparison | Initial geometries, optimization retries and path validation |
| Periodic DFT | Numerical convergence and the physical comparison when independently useful | k-point/cutoff samples; retain the parameter set and table as materials |
| MD/free energy | Equilibration, sampling adequacy or state comparison when separately interpretable | Replicate trajectories and statistical windows |
| Model fitting | Shared data assessment and independently compared models | Parameter searches and repeated fits |
| Theory/derivation | Independently useful lemmas or approximation checks | Algebra, symbolic manipulation and local revisions; Jobs are optional |

A root question is optional. Several task entries can represent independent questions. Use `part_of` from a subquestion to its broader question; a shared question can have several parents. `requires` records an actual research dependency, not the order in which tool calls occurred. Use `alternative_to` when approaches really are alternatives. Comparisons cite exact input Results.

After creating or choosing the relevant Nodes, read the current task and bind its entries and focus:

```json
{
  "action": "set_research",
  "expected_revision": 3,
  "research": {
    "entry_node_ids": ["node_returned_for_the_study"],
    "focus_node_ids": ["node_returned_for_path_A", "node_returned_for_path_B"]
  }
}
```

Substitute actual returned IDs and revision. This replaces both navigation lists. Task focus is not a lock, ownership or permission to spend resources. A shared Node can remain open when one task finishes. Read-only browsing uses `research_read {ref}` or `{ref, field:"relations"}` and the returned pagination; it does not need a focus update.

## Let evidence change the plan

On recovery, relate the current findings and pending Jobs to the user's objective and delivery criteria. Continue a method when another attempt has a reason to be informative. If a method reaches its limit, assess the remaining authorized approaches. If a Job is running and independent work remains, pursue it; wait on the task only when those Job outcomes are needed before further useful work.

An execution error warrants diagnosis; it does not by itself refute the scientific idea. Update the existing question's method after inspecting the failure. A candidate-specific negative finding is useful evidence and need not terminate the broader question or assignment.

To revisit a closed question, read its current fields, reopen it with `research_update`, and record the reason and evidence in the note. Create another Node only for an independent question or separately pursued branch. Preserve old Jobs, files and Results. Reuse exact prior evidence where applicable; repeating an external action requires checking its original receipt.

Correct a published conclusion with a new Result and `supersedes`. Select it as the current assessment when appropriate. Review affected comparisons and reports using the supplied notices. A notice requests scientific review; it does not automatically invalidate every downstream conclusion or launch recalculations.

## Retain progress and finish the assignment

Plans and notes explain decisions. New Results, fixed materials and actual Job milestones provide recoverable progress. Editing a plan, making more Nodes or citing the same evidence in a different combination does not replenish progress allowance. For derivation or planning assignments, retain the useful derivation or plan itself as a Result/material.

Finish against the user's delivery criteria, with the relevant immutable evidence and limitations. A negative or inconclusive conclusion may satisfy the actual assignment; it does not authorize weakening a requested claim. Closed Nodes and successful processes are not completion evidence by themselves. Stop repeated uninformative attempts within the stated limits, and distinguish a local failed method from a task-wide blocker.
