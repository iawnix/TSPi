# Remote Contract

`ts_remote` manages generic remote job lifecycle:

- stage files;
- submit commands;
- poll scheduler or process state;
- tail logs;
- fetch artifacts;
- kill jobs when requested;
- record receipts.

Remote helpers do not parse chemistry and do not write workspace verdicts.
Receipts should be stored under `nodes/<node_id>/remote/` and then registered as
evidence or provenance through `ts_workspace`.
