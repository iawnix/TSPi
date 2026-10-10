# Skills and the scientific execution catalog

[English](EXTENSIONS.md) | [简体中文](EXTENSIONS.zh-CN.md)

Method guidance, convenience executors, and compute environments are maintained
separately. The Agent can write inputs and scripts for a research question and
execute them through generic Jobs. Bundled entries neither define an exhaustive
capability list nor prescribe research steps.

## Skill discovery and language

Root `package.json.pi.skills` declares `skills/` and `domains/chemical/skills/`.
`apps/agent/resources/skills.mjs` verifies release resources and invokes Pi's
`loadSkills` with default discovery disabled. Pi discovers a skill through its
`SKILL.md`, which is currently English. Names, descriptions, and paths support
selection; the Agent reads the body and then references on demand.

`SKILL.zh-CN.md` is a Chinese translation for reading and maintenance. A Chinese
user message or system locale does not replace the English entrypoint, and the
translation is not automatically loaded as a second skill. The Agent may explicitly
read it when needed; response and report language follows the user's request.
Maintain both languages together: fixing only the translation leaves the default
instructions unchanged. See the [Skill catalog](../skills/README.md).


## System prompt

`apps/agent/pi/setup.mjs` assembles the working directory, `prompts/coragent.md`,
and discovered Skill descriptions into the system prompt. `prompts/coragent.zh-CN.md`
is a translation for maintenance; it is not injected alongside English or selected by
conversation language. `/sys-prompt` inspects the current worker's actual prompt and sources.

The prompt contains decisions shared across tasks: instruction priority, research
objects, execution ownership, authorization and budgets, evidence, corrections,
and communication. Scientific procedures and full tool examples remain in on-demand
Skills. It instructs the Agent to read applicable workspace AGENTS.md files; the
assembly step does not automatically concatenate them. A bounded research snapshot
is injected separately before each model request as current records, not new
instructions or authorization.

Resource checks verify loaded bytes and deterministic tests verify injection and
record behavior. They do not establish model compliance with every rule or replace
actual spending limits and execution permissions.

## What execution.json does

Root `package.json.coragent.execution` points to
`domains/chemical/execution.json`. Python independently loads and validates it in
`backend/src/research_agent/application/execution_catalog.py`. It declares:

- `executors`: convenience entry IDs/versions, scripts, argument templates, input roles, outputs, requirements, and resource digests.
- `validators`: scoped evidence-checking scripts and their input contracts.
- `acceptance_profiles`: checklists for specific deliverables, with scope defined by each profile.

It does not load Skills, orchestrate workflows, or limit the Agent to these scripts.
Selecting `--executor` or `validator_id` requires a registered ID/version as the
contract for that helper. For other methods, submit explicit command, inputs,
outputs, and platform through `job_start`, or prepare a task with
`--script <file.py> --backend <binding>`. Neither requires a new catalog entry.
Installation-level `etc/job.toml` bindings configure actual programs, Python,
activation scripts, and compute resources.

See [Scientific operations](SCIENTIFIC_CAPABILITIES_OPERATIONS.md) for preparation,
submission, collection, and recovery.

## Maintenance

`config/resources.json` records bundled Skill, reference, script, and prompt
digests; the execution catalog also pins its script dependencies. After editing resources:

```bash
python3 scripts/update_resources.py
python3 scripts/update_resources.py --check
python3 tools/lint_skills.py
```

Add Skills under declared roots with matching English and Chinese entrypoints
and references. Update the execution catalog when adding a reusable convenience
executor. Core tool assembly belongs to `apps/agent/`; it does not use the retired
extension-manifest, dynamic server allowlist, or provider registration flow.
