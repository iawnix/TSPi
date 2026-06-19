# Backend Contract

`ts_backends` prepares and describes calculation tasks. A backend may create
inputs, commands, and parsers for its own artifacts.

Backends must not:

- mutate workspace root ledgers;
- close a node;
- set a scientific verdict;
- accept or reject a pathway;
- write outside the node artifact directory by default.

The expected flow is:

1. `start_node` creates `nodes/<node_id>/`.
2. Backend prepares node-scoped inputs and command metadata.
3. Local or remote execution creates artifacts.
4. Parsed facts are registered through `update_workspace`.
5. `end_node` writes the closure and triggers finalizers.
