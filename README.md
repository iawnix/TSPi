# @iawnix/ts-agent

`@iawnix/ts-agent` is the Pi Package maintained in the TSAgentSkill repository.
It provides an evidence- and hypothesis-driven transition-state research
workflow and separates scientific decisions, program
execution, evidence registration, branch topology, reporting, and read-only
visualization.

This branch supports Pi Agent only. The Python packages and command-line
entrypoints are implementation kernels used by the Pi extensions, not a
separately supported agent runtime.

The workspace contract is `ts-decision/2` and `ts-node/2`. Phase-based
workspaces are rejected and must be recreated under the current ontology.

## Architecture

- `skills/transition-state-workflow/`: the only public Pi Skill, including its
  on-demand references and reusable report/decision assets.
- `extensions/`: the public Pi tool and command adapters.
- `src/agent-core/`: shared `ts-agent-task/1` / `ts-agent-result/1` protocol,
  result normalization, disposable-session lifecycle, and durable run journal.
- `src/agents/review/`: fresh, tool-free Pi scientific-review sessions with
  bounded task packets and review-specific result validation.
- `src/agents/compute/`: fresh backend sessions, compute-specific result
  binding, and private backend skills.
- `src/agents/artifacts/`: fresh render, report, and email-draft sessions,
  request contracts, and private artifact skills.
- `ts_workspace`: the only canonical research-state control plane.
- `ts_compute` and `ts_backends`: typed calculation intents, preparation,
  pre-bound submission/cancellation, status, collection, and
  deterministic parsing.
- `ts_remote`: installation-owned OpenSSH/SCP transfer, Torque lifecycle,
  durable control records, and read-only diagnostics without scientific authority.
- `ts_render`: local molecular rendering through `xyzrender` only.
- `ts_report`: report-package assembly from validated workspace evidence.
- `ts_email`: deterministic fixed-template drafts, private delivery policy,
  ClawEmail boundary, and idempotent send receipts.
- `ts_web`: read-only workspace normalization and visualization.

The Root Agent is the sole authority for hypothesis status, branch selection,
audit conclusions, stopping, and workspace decisions. A completed calculation
is only a program fact.

## Install

Create the research workspace, install this branch project-locally through Pi,
then create a workspace-owned runtime from the Pi-managed checkout:

```bash
mkdir -p /path/to/ts-workspace
cd /path/to/ts-workspace
pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve
export TS_WORKSPACE_ROOT=$PWD
export TS_AGENT_SKILL_ROOT=$PWD/.pi/git/github.com/iawnix/TSAgentSkill
python "$TS_AGENT_SKILL_ROOT/scripts/install_env.py" \
  --package-root "$TS_AGENT_SKILL_ROOT" \
  --workspace-root "$TS_WORKSPACE_ROOT" \
  --conda-root /path/to/miniforge3 \
  --with-render \
  --json
```

The default runtime manifest is:

```text
<workspace>/.agents/runtime/transition-state-workflow/env.json
```

The default Conda prefix store is:

```text
<workspace>/.agents/envs/transition-state-workflow/<environment-hash>/
```

Therefore separate Pi research workspaces do not collide by default. Set the
same `TS_AGENT_ENV_ROOT` only when deliberate environment sharing is wanted.
The package checkout, including a Pi `.pi/git/...` checkout installed directly
from GitHub, never owns the workspace runtime when `--workspace-root` is used.

From the package checkout:

```bash
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env
TS_WORKSPACE_ROOT=/path/to/ts-workspace npm run install-env:core
```

## Render Dependency Boundary

`ts_render` uses `xyzrender` only.

It does not require or probe Blender, FFmpeg, OpenBabel, Mayavi, or PyVista.
Missing render support does not block workspace validation or calculation
parsing.

## Pi Agent Usage

The native adapters support Pi `>=0.81.1 <1.0.0` with matching Pi SDK packages
and are currently validated against Pi `0.83.0`. Pi
project-local installation registers a package reference; it does not copy the
skill into a requested directory.

Local package reference:

```bash
cd /path/to/ts-workspace
pi install -l /absolute/path/to/TSAgentSkill --approve
```

Direct GitHub installation of this development branch:

```bash
cd /path/to/ts-workspace
pi install -l git:github.com/iawnix/TSAgentSkill@pi_ts_subagents --approve
TS_WORKSPACE_ROOT=$PWD pi --approve --session-dir .pi/sessions
```

Install the package-owned `TSPi` launcher once at the installation root, next
to its `.pi/` and `.agents/` directories. Select one isolated research
workspace for every Pi process:

```bash
./TSPi --workspace reaction-a
./TSPi --workspace reaction-b
./TSPi --workspace reaction-c --dev
```

Names use 1-80 letters, digits, dots, underscores, or hyphens and resolve only
under `<installation>/workspaces/<name>/`. Plain `./TSPi` is rejected so the
installation root cannot accidentally become research state. Each workspace
owns its `.pi/sessions`, `.pi/root-agent.lock`, `.agents/workspace-identity.json`
after formal initialization, `nodes/`, `inputs/`, and `reports/`. A nonblocking
writer lock permits only one Root Agent in one workspace; different workspace
names can run concurrently.

The package checkout, remote profile, email policy, shared Python environment,
and runtime manifest remain installation-owned. Remote configuration lives at
`<installation>/.pi/remote.toml` or the absolute path in `TS_REMOTE_CONFIG`.
Ordinary `./TSPi --workspace <name>` startup does not contact the cluster, so a
remote outage does not block local research. `./TSPi --check-remote` performs a
strict read-only SSH status check, returns nonzero on failure, and does not
require a workspace.

An unpinned GitHub URL resolves the repository default branch (`main`). Until
this work is merged or tagged, it does not select `pi_ts_subagents`.

Pi loads these extensions from the resolved package root:

- `extensions/ts-workflow-control`
- `extensions/ts-workflow-ui`
- `extensions/ts-workflow-review`
- `extensions/ts-workflow-compute`
- `extensions/ts-workflow-artifacts`

Public tool prefixes describe execution rather than subject matter:

- `ts_workspace_*` calls the deterministic workspace control plane without a
  child model session.
- `ts_subagent_*` creates one fresh, isolated child model session.
- `ts_remote_*` runs deterministic SSH/Torque diagnostics without a child
  model session.
- `ts_email_*` performs deterministic external delivery subject to a private,
  pre-activated fixed-scope policy; it never delegates sending to a child.

The package-owned UI extension installs a MyPi-compatible animated TSPi header,
mode-aware rounded editor, session footer, working state, and terminal title
request.
It adds the configured workspace/remote profile and observes `ts_subagent_*`
lifecycle updates through a two-line active-child panel and history entries.
Pi's native `Ctrl+O` action globally toggles every expandable history and tool
result; TS-specific entries label it as "expand all details" or "collapse all
details" rather than implying that it affects only the adjacent result.
The UI reads presentation state only: it does not probe the cluster, write workspace
state, request authorization, call a model, or make scientific decisions.

The workspace control surface is exactly:

- `ts_workspace_context`: read `summary`, `delta`, `node`, `branch`, or
  `audit` context on demand.
- `ts_workspace_decision_draft`: construct a non-mutating `ts-decision/2`
  draft with current report and revision provenance.
- `ts_workspace_decision_validate`: validate that draft against the live
  workspace.
- `ts_workspace_decision_apply`: transactionally apply a validated mutation
  and return refreshed compact context.

Pi also exposes:

- `ts_subagent_review`: fresh, tool-free advisory scientific review.
- `ts_remote_inspect`: read-only `status`, `doctor`, `queues`, or `nodes`
  probe for the configured remote profile. It has no
  upload, submit, cancel, or workspace mutation capability.
- `ts_subagent_compute`: fresh backend subagent with only the typed
  tools bound to one `prepare`, `submit`, `inspect`, `collect`, `cancel`, or
  `parse` request. The Root Agent can run `submit/cancel` directly after
  preflight; no interactive confirmation is required.
- `ts_subagent_render`: node-scoped local render with bound paths.
- `ts_subagent_report`: validated report-package build under
  `reports/`.
- `ts_subagent_email_draft`: local draft JSON from a generated report
  summary and explicit recipients. Its subject and body come directly from the
  deterministic `email_summary.md` template.
- `ts_email_send`: sends one existing draft only when recipients, template,
  report-manifest digests, and fixed attachments match the active private
  delivery policy. Sent or ambiguous receipts prevent duplicate retries.

The delivery policy is installation-private state, not package source. `TSPi`
sets `TS_EMAIL_POLICY_ROOT` to its installation root; other launchers fall back
to `TS_WORKSPACE_ROOT`. Create the fixed policy once at that root, inspect the
exact returned scope, and activate it with the returned exact token:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_email.py" policy-create \
  --root "$TS_EMAIL_POLICY_ROOT" \
  --recipient researcher@example.org \
  --attachment final_report.md \
  --clawemail-root /home/iaw/.pi/agent/skills/clawemail \
  --json

python "$TS_AGENT_SKILL_ROOT/scripts/ts_email.py" policy-activate \
  --root "$TS_EMAIL_POLICY_ROOT" \
  --token 'EXACT_TOKEN_FROM_POLICY_CREATE' \
  --json
```

The mode-0600 policy and authorization files live under
`<installation>/.pi/`. They contain no mailbox credentials. A real descendant
research workspace inherits the active installation policy when it has no
local policy, or when its pending local policy has exactly the same transport,
recipients, template, and attachment names. A local active, disabled, changed,
or differently scoped policy remains authoritative. Delivery receipts always
stay in the research workspace. `policy-status` reports `policy_scope`,
`policy_source_root`, and `local_policy_state` so inheritance is explicit.

Changing any policy field invalidates its activation. ClawEmail authentication
remains owned by the installed ClawEmail skill. Use
`policy-disable --root "$TS_EMAIL_POLICY_ROOT" --json` to revoke installation
delivery without deleting policy history; the same exact token is required to
reactivate it. Policy create, activate, and disable commands always modify only
the explicit `--root`.

Users can run the same remote diagnostics with
`/ts-remote status|doctor|queues|nodes`. The command and Agent tool are on demand; they
do not add remote output to every turn's context. Command completion explains each
read-only mode, and an above-editor activity panel remains visible until the
diagnostic returns or stops with an error.

`before_agent_start` injects only a short control-plane reminder. It does not
inject a full workspace report every turn. Use `mode=delta` with the last
scientific `workspace_revision` and `operational_revision` to avoid repeated
unchanged context while still seeing new calculation or agent-run state.

See `skills/transition-state-workflow/references/pi_agent_adapter.md`.

## Research Nodes

New nodes use one `node_type`:

| Node type | Responsibility |
|---|---|
| `intake` | Normalize user inputs, structures, constraints, and completion criteria. Reserved for `n000`. |
| `mechanism` | Propose, compare, revise, or evaluate a falsifiable mechanism hypothesis. |
| `candidate_search` | Generate TS, endpoint-conformer, intermediate, or crossing-point candidates. |
| `validation` | Produce evidence for a declared prediction and `validation_scope`. |
| `audit` | Audit a TS, elementary step, pathway, or the study. |

Frequency and IRC/connectivity are both validation nodes but remain separate
evidence gates. Wavefunction analysis is normally
`node_type=validation, validation_scope=electronic_structure`; a later
`mechanism` node interprets whether that evidence supports or falsifies the
hypothesis.

Independent status axes:

- `node.lifecycle`: `running|closed|stopped`
- `closure.program.outcome`: `success|failure|not_run`
- `closure.hypothesis.status`: `supported|unsupported|ambiguous`, mechanism only
- `closure.audit.status`: `accepted|not_accepted|ambiguous`, audit only

Candidate and validation nodes cannot set hypothesis status.

## Calculation Attempts

Pi preparation accepts `ts-calculation-request/1` semantics:

- scientific purpose and selected workspace node
- `attempt_kind=primary|retry|recalculation`
- `recalculation_ref`, required only for recalculation
- one allowlisted backend, task type, logical artifact-role bindings, and settings
- a local or allowlisted remote execution target

The deterministic host derives the node validation scope and creates the
immutable `ts-calculation-intent/2`, intent ID, attempt directory, expected
artifact names, execution-mirror authority, and remote directory. Pi callers do
not create intent JSON files or fill generated path fields. Before preparation,
`ts_workspace_context mode=artifacts` lists eligible inputs with deterministic
`artifactId` values and compatible `inputRole` values. The prepare request must
bind every required role through `inputArtifacts`; the kernel resolves and
freezes the path, owner, source attempt, and SHA-256 snapshot.
This standardizes calculation mechanics; it does not prescribe a node sequence,
research phase, branch order, method choice, or scientific acceptance decision.

The deterministic calculation matrix includes Gaussian
`sp|opt|freq|opt_freq|irc`, xTB `sp|opt|freq|opt_freq|scan|md`, CREST
`conformer_search`, ASE `neb`, and QBICS `dmecp`. xTB scan intents bind an XYZ
geometry and a validated `$constrain`/`$scan` control input; parsing reports each
scan point's target coordinate, geometry-derived actual coordinate, and energy
from `xtbscan.log`. xTB and CREST parsing binds a primary `xtb.out` or
`crest.out` plus the task-required sibling artifacts from the prepared manifest.
Parsed facts distinguish process completion, requested task completion,
convergence, and artifact completeness; they never make a TS, connectivity,
conformer-selection, or mechanism verdict.

Remote requests provide only a configured profile name and complete Torque
resource shape. Hosts, OpenSSH configuration, scheduler commands, remote root,
software activation, queue policy, and environment come from the
installation-owned TOML selected by `TS_REMOTE_CONFIG`. They cannot be supplied
by an Agent or calculation intent. Old transport, host, endpoint, or remote-root
request fields are rejected rather than converted.

All local authority for one attempt lives under:

```text
nodes/<node>/attempts/<intent>/
├── intent.json
├── prepared.json
├── status.json
├── submit_guard.json / submit_result.json
├── cancel_guard.json / cancel_result.json
└── outputs/
```

Each initialized workspace also owns a persistent, non-scientific identity at
`.agents/workspace-identity.json`. Remote preparation binds this identity and
the configured profile root into `prepared.json` as:

```text
<profile.remote_root>/workspaces/<workspace_id>/runs/<node_id>/<intent_id>
```

The remote `submission_id` is bound to both `workspace_id` and `intent_id`. This
separates independent Pi workspaces that share one SSH account. Agents
working in the same workspace intentionally share the identity and remain
serialized by the existing per-intent submit/cancel guards. The identity does
not enter canonical scientific state or `workspace_revision`. Every remote
prepared record must contain the matching profile, workspace-bound path,
resources, and submission binding; incomplete records are rejected.

Generated remote intents always declare `authority=execution_mirror`. Results
become usable only after collection and local verification. See
`skills/transition-state-workflow/references/compute_operator.md`.

`ts_remote` binds one `submission_id` to the intent digest, generated Torque
script, complete input manifest, expected artifacts, and resource request. It
persists scheduler output and known job IDs across post-`qsub` SSH failures and
forbids automatic retry after ambiguous submission or cancellation outcomes.
Directory-creation or upload failures remain safe to retry with the same
immutable binding. Collection uses declared artifacts and verified hashes
without querying scheduler history. Scheduler records are not scientific
evidence. The complete profile, lifecycle, failure, and diagnostic contract is
in `skills/transition-state-workflow/references/remote_contract.md`.

Gaussian remote execution requires a configured `software.gaussian` profile.
The profile binds the command, activation script, queue allowlist, and
server-owned environment; a bare `g16` installation or client PATH override is
insufficient.

## Agent Protocol

All isolated roles communicate through:

- `contracts/agent_task.schema.json` (`ts-agent-task/1`)
- `contracts/agent_result.schema.json` (`ts-agent-result/1`)

Roles are `review`, `backend`, `render`, `report`, and `email`. Results cannot
contain authoritative hypothesis, branch, acceptance, or strict pathway
decision fields. Compute and artifact agents each compose one shared operator
policy with one selected backend or role policy under their owning `src/agents/`
directory. These policy fragments are runtime prompt inputs, not Pi skills.

The Pi host persists every child task under `nodes/<node>/agent-runs/<task>/`
for one-node work or `operations/agent-runs/<task>/` for study-level work.
These immutable operational records are never evidence and do not change the
scientific `workspace_revision`.

## Reporting

Generate the final package only from a validated workspace:

```bash
python "$TS_AGENT_SKILL_ROOT/scripts/ts_report.py" \
  --root <workspace> \
  --package-dir <workspace>/reports/final_report_package
```

Package creation is no-overwrite and atomic. `package_manifest.json` uses
`ts-report-package/1` and binds the source `workspace_revision`, report,
context, email summary, and assets by SHA-256. Email drafting rejects a changed
manifest or summary.

Use `skills/transition-state-workflow/assets/templates/ts_final_report.md`.
Keep electronic, E+ZPE, and available free energy values distinct; report
missing corrections explicitly. Accepted-TS language still requires separate
TS/Freq, connectivity, and audit support.

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q
npm run test:pi-adapter
npm run typecheck
npm run test:package
```

The Pi integration suite runs the real Pi executable with a local recording
provider. It verifies the eleven-tool Root Agent inventory, a tool-free review
child, a compute child with exactly one request-bound tool, and an artifact
child with exactly one request-bound tool. Before release, also test one clean,
branch- or tag-pinned GitHub installation from a network that can reach GitHub.

### Development Subagent Tests

The optional development extension lists and runs isolated package tests. It is
not part of the default `pi.extensions` list and adds no Root Agent tools or
scientific workspace protocol. Load it explicitly from a development checkout:

```bash
pi --extension /absolute/path/to/TSAgentSkill/extensions/ts-workflow-dev/index.ts
```

Then use:

```text
/ts-test list
/ts-test run subagent-review
/ts-test run subagent-compute
/ts-test run subagent-all
/ts-test run workspace-contracts
/ts-test run remote-contracts
```

These cases invoke the existing pytest and real-Pi recording-provider tests in
temporary workspaces. They reuse `ts-agent-task/1`, `ts-agent-result/1`, typed
actions, and the agent-run journal; the test runner adds only external
assertions and pass/fail reporting. `npm run test:subagents` runs the same test
surface non-interactively.
