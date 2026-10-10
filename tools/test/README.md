# Local deterministic tests

Use `python3 tools/test/runner.py` for all suites. Dependencies, snapshots,
installations, caches and evidence stay under repository `local_debug/`.
Nothing under that directory may be uploaded or included in a product artifact.
Runner output contains only run IDs, result counts, status and failed test file
names and valid line numbers matched against the public source inventory. Case names, parameters,
assertions and detailed failures remain in each run's local report and log files.

`prepare` also caches the public `structure` and `wrapper` Conda locks for the complete public
installer acceptance. `--job-profiles` selects these preparation profiles; it
defaults to `structure,wrapper`. The installation tests use those caches offline and
cover package activation, ordinary structure Jobs, repeat installation, and purge.

```bash
export CORAGENT_TEST_CONDA=/home/iaw/soft/miniconda/26.7.1-1/bin/conda
python3 tools/test/runner.py prepare
python3 tools/test/runner.py doctor
python3 tools/test/runner.py plan --changed --base origin/main
python3 tools/test/runner.py check --scope pi,tools
python3 tools/test/runner.py fast --files tests/contract/test_test_runner.py -- -q
python3 tools/test/runner.py native-pi --files tests/node/native/coding-tools.test.mjs
python3 tools/test/runner.py source -- -q
python3 tools/test/runner.py verify
python3 tools/test/runner.py replay --run RUN_ID --failed
python3 tools/test/runner.py release --artifact /absolute/path/to/package.tar.gz
python3 tools/test/runner.py phone --phone-source /absolute/path/to/corhub --flutter-root /home/iaw/project/TSPi/local_debug/deps/flutter/3.44.0 --pub-cache /home/iaw/project/TSPi/local_debug/deps/flutter-pub
python3 tools/test/runner.py gc --dry-run
python3 tools/test/runner.py gc --apply
```

`prepare` is the only dependency installation stage. It uses repository locks,
Pi pin and patches, per-key preparation locks, and completion receipts. Tests
never choose an arbitrary Python installation or install missing dependencies.
A missing or invalid prepared environment blocks the run.

Every run takes its own source snapshot, including uncommitted and untracked
source changes, and creates an independent Git repository for build tests.
The report records the original commit, dirty state, source digest, dependency
keys, seed and selection reasons. Source changes during a passing run make its
result stale. Replay uses the old snapshot and dependency keys; checking a fix
requires a new run.

Python files are sharded across at most eight subprocesses; native Node files
use at most two. `--workers` sets the shared file-level budget. Scientific
thread pools are limited to one thread per worker. Each suite runs inside a
Linux user/network namespace with loopback enabled and no external route.
Provider credentials and user configuration are not inherited. Environments
that prohibit network namespaces fail the gate instead of allowing egress.

Python case and socket directories use short private names to fit Unix socket
limits; their full case IDs remain in reports. The dedicated namespace init
reaps orphaned grandchildren throughout a run. PID namespaces and parent-death
signals also terminate detached children if the supervisor itself is killed.

`system-services` separately exercises real user-manager units. Its launcher
registers each unit before starting it, gives the actual service a private
network, and isolates its environment from manager credentials. An independent
guardian stops owned units if the runner disappears. Unit stdout and stderr
stay in the private run, and cleanup verifies units were removed.

The supervisor records PID start identity and adopts detached descendants as a
Linux child subreaper. Success, failure, timeout and cancellation all finish
with a process cleanup audit. A cleanup failure or required skipped test makes
the run fail. Failed files and logs are retained locally. `doctor` reaps only
verified processes belonging to interrupted runs. `gc` respects live processes,
retained-run dependency references, current environments and `KEEP` markers.

`source` builds a content-addressed wheel once, verifies its digest, creates a
fresh overlay and proves first-party imports come from that wheel. It explicitly
binds catalog and Skill resources to the captured package, independently of the
overlay's parent directories. It retains
the overlay after failure. `release` accepts only the complete package archive
with its adjacent `coragent-package-release.json`, invokes the real
installer, verifies external-cwd startup and installed Python origins, and
runs the native terminal startup/resume/quit and Worker research-flow drivers
against the installed product and Pi runtime. The deterministic local model
exercises all seven coding tools through the actual Worker loop, scientific
Job submission, Research Node/Result persistence, Monitor scheduling, and
restart. Origin assertions reject source-checkout imports and `PYTHONPATH`;
zero skipped tests and an unchanged archive digest are required. Acceptance
then uses the installed uninstaller and requires removal of the installation
root. Its report explicitly leaves Phone, real-model
and remote-platform acceptance unverified. Those require separately authorized
non-private data; the normal runner does not send test data externally.

CI uses these same commands, with an ephemeral root under `runner.temp`, and
installs `ripgrep` and `fd-find` before entering the offline test namespace.
Ubuntu's `fdfind` is exposed as `fd` on the test PATH for Pi's native coding tools.
CI never uploads the test root, logs, databases or cache. The manifest discovers
files automatically; all primary test suites must own disjoint sets of tests.

The optional `phone` suite captures both repositories, runs Flutter with the
supplied private SDK and offline package cache, and connects the actual Dart
client to a real local Host/Pi Worker with a deterministic provider. It covers
protocol identity, Monitor views and mutation receipts, models, input and
interrupts. It rejects skipped tests, records both source digests, and uses the
same network isolation and process cleanup as other suites. Prepare the SDK and
package cache under `local_debug/` before invoking it; it does not download them
or write Flutter caches into either source repository. This is automated local
interop, not an installed Android/iOS device test.
