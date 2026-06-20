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

Gaussian remote execution is implemented by the internal adapter
`ts_remote.gaussian`. Do not expose a standalone Gaussian remote-runner script as
part of the public workflow surface. The generated compute-side runner must
source Gaussian profiles with unset-variable protection because cluster profiles
may read variables such as `LD_LIBRARY64_PATH` before defining them.
