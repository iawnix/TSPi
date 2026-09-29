import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import {
  CAPABILITY_HOST_CONFIG_SCHEMA,
  create_configured_capability_host,
} from "../../apps/research-agent-app-server/index.mjs";

async function temporary_root() {
  return mkdtemp(join(tmpdir(), "research-agent-capability-host-"));
}

test("standalone capability bootstrap is explicitly not configured by default", async () => {
  assert.equal(await create_configured_capability_host({ package_root: resolve(".") }), null);
});

test("standalone capability bootstrap loads manifest, trusted adapter, and EnvironmentBroker", async () => {
  const root = await temporary_root();
  try {
    const descriptor_path = resolve("extensions/tspi-chemical/providers/xtb.json");
    const descriptor_digest = `sha256:${createHash("sha256").update(await readFile(descriptor_path)).digest("hex")}`;
    const environment_module = join(root, "environment.mjs");
    await writeFile(
      environment_module,
      "export function create_environment_broker() { return { resolve(request) { return { environment_id: 'test', environment_kind: request.environment_kind, command: ['/bin/true'], env: {}, binding_digest: 'sha256:test', readiness: { state: 'ready', checks: [] } }; } }; }\n",
      "utf8",
    );
    const config_path = join(root, "capabilities.json");
    await writeFile(
      config_path,
      JSON.stringify({
        schema_version: CAPABILITY_HOST_CONFIG_SCHEMA,
        environment_module,
        adapters: ["xtb_local"],
        allowlist: [{
          manifest_provider_id: "xtb",
          adapter_id: "xtb_local",
          kind: "compute",
          version: "1",
          descriptor_digest,
          capability_ids: ["xtb.sp", "xtb.opt", "xtb.freq", "xtb.opt_freq"],
          required_tool_ids: ["xtb"],
        }],
      }),
      "utf8",
    );
    const host = await create_configured_capability_host({
      config_path,
      package_root: resolve("."),
      artifact_root: join(root, "artifacts"),
    });
    assert.equal(host.capability_assembly.catalog()[0].adapter_id, "xtb_local");
    assert.ok(host.tool_gateway.describe({ workspace_mode: "research" }).some((item) => item.capability_id === "xtb.sp"));
    const readiness = await host.capability_assembly.readiness({ capability_id: "xtb.sp" });
    assert.equal(readiness[0].readiness.state, "ready");
    assert.equal(readiness[0].environment_id, "test");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute.toml fallback assembles light xTB and Gaussian capabilities", async () => {
  const root = await temporary_root();
  try {
    const activation_path = join(root, "activate.sh");
    await writeFile(activation_path, "export RESEARCH_AGENT_TEST_ACTIVATED=1\n", { mode: 0o600 });
    const compute_path = join(root, "compute.toml");
    await writeFile(compute_path, [
      'default_environment = "local"',
      "[environments.local]",
      'kind = "local"',
      "[environments.local.backends.xtb]",
      'command = "/bin/true"',
      `activation_script = ${JSON.stringify(activation_path)}`,
      "[environments.local.backends.gaussian]",
      'command = "/bin/true"',
      "",
    ].join("\n"), "utf8");
    const host = await create_configured_capability_host({
      package_root: resolve("."),
      compute_config_path: compute_path,
      artifact_root: join(root, "artifacts"),
    });
    assert.equal(host.source, "compute.toml");
    assert.deepEqual(
      host.tool_gateway.describe({ workspace_mode: "light" }).filter((item) => item.kind === "compute").map((item) => item.capability_id),
      [
        "xtb.sp", "xtb.opt", "xtb.freq", "xtb.opt_freq",
        "gaussian.sp", "gaussian.opt", "gaussian.freq", "gaussian.opt_freq", "gaussian.ts", "gaussian.irc", "gaussian.scan",
      ],
    );
    assert.deepEqual((await host.capability_assembly.readiness({ capability_id: "xtb.sp" }))[0].readiness.state, "ready");
    const binding = await host.environment_broker.resolve({
      provider_id: "xtb_local",
      capability_id: "xtb.sp",
      environment_kind: "compute",
    });
    assert.equal(binding.env.RESEARCH_AGENT_TEST_ACTIVATED, "1");
    const selected = await host.environment_broker.resolve({
      provider_id: "xtb_local",
      capability_id: "xtb.sp",
      environment_kind: "compute",
      environment_id: "local",
    });
    assert.equal(selected.environment_id, "local");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("compute.toml is inherited from TSPI_INSTALL_ROOT when worker env omits TS_COMPUTE_CONFIG", async () => {
  const root = await temporary_root();
  const previousInstall = process.env.TSPI_INSTALL_ROOT;
  const previousCompute = process.env.TS_COMPUTE_CONFIG;
  try {
    const installRoot = join(root, "install");
    const configDir = join(installRoot, ".pi");
    await mkdir(configDir, { recursive: true, mode: 0o700 });
    const computePath = join(configDir, "compute.toml");
    await writeFile(computePath, [
      'default_environment = "local"',
      "[environments.local]",
      'kind = "local"',
      "[environments.local.backends.xtb]",
      'command = "/bin/true"',
      "",
    ].join("\n"), "utf8");
    process.env.TSPI_INSTALL_ROOT = installRoot;
    delete process.env.TS_COMPUTE_CONFIG;
    const host = await create_configured_capability_host({
      package_root: resolve("."),
      artifact_root: join(root, "artifacts"),
    });
    assert.equal(host.source, "compute.toml");
    assert.ok(host.tool_gateway.describe({ workspace_mode: "light" }).some((item) => item.capability_id === "xtb.sp"));
  } finally {
    if (previousInstall === undefined) delete process.env.TSPI_INSTALL_ROOT;
    else process.env.TSPI_INSTALL_ROOT = previousInstall;
    if (previousCompute === undefined) delete process.env.TS_COMPUTE_CONFIG;
    else process.env.TS_COMPUTE_CONFIG = previousCompute;
    await rm(root, { recursive: true, force: true });
  }
});

test("compute.toml keeps local and remote environments separate from capability identity", async () => {
  const root = await temporary_root();
  try {
    const ssh_config = join(root, "ssh_config");
    await writeFile(ssh_config, "Host agent.1w\n  HostName agent.1w\n", { mode: 0o600 });
    const compute_path = join(root, "compute.toml");
    await writeFile(compute_path, [
      'default_environment = "local"',
      "[environments.local]",
      'kind = "local"',
      "[environments.local.backends.xtb]",
      'command = "/bin/true"',
      "[environments.remote]",
      'kind = "remote"',
      `ssh_config = ${JSON.stringify(ssh_config)}`,
      'ssh_host = "agent.1w"',
      'remote_root = "/tmp/tspi-remote"',
      'allowed_queues = ["short"]',
      "[environments.remote.backends.xtb]",
      'command = ["xtb"]',
      "",
    ].join("\n"), "utf8");
    const host = await create_configured_capability_host({
      package_root: resolve("."),
      compute_config_path: compute_path,
      artifact_root: join(root, "artifacts"),
    });
    const remote = await host.environment_broker.resolve({
      provider_id: "xtb_local",
      capability_id: "xtb.sp",
      environment_kind: "compute",
      environment_id: "remote",
      execution_kind: "remote",
    });
    assert.equal(remote.environment_id, "remote");
    assert.equal(remote.execution_kind, "remote");
    assert.deepEqual(host.tool_gateway.describe({ workspace_mode: "light" })
      .filter((item) => item.kind === "compute")
      .map((item) => item.capability_id), ["xtb.sp", "xtb.opt", "xtb.freq", "xtb.opt_freq"]);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("remote-only compute configuration still registers a transport-neutral capability", async () => {
  const root = await temporary_root();
  try {
    const ssh_config = join(root, "ssh_config");
    await writeFile(ssh_config, "Host agent.1w\n  HostName agent.1w\n", { mode: 0o600 });
    const compute_path = join(root, "compute.toml");
    await writeFile(compute_path, [
      'default_environment = "agent.1w"',
      '[environments."agent.1w"]',
      'kind = "remote"',
      `ssh_config = ${JSON.stringify(ssh_config)}`,
      'ssh_host = "agent.1w"',
      'remote_root = "/tmp/tspi-remote"',
      'allowed_queues = ["short"]',
      '[environments."agent.1w".backends.xtb]',
      'command = ["xtb"]',
      "",
    ].join("\n"), "utf8");
    const host = await create_configured_capability_host({
      package_root: resolve("."),
      compute_config_path: compute_path,
      artifact_root: join(root, "artifacts"),
    });
    assert.ok(host.tool_gateway.describe({ workspace_mode: "research" })
      .some((item) => item.capability_id === "xtb.sp"));
    const readiness = await host.capability_assembly.readiness({ capability_id: "xtb.sp" });
    assert.equal(readiness[0].environment_id, "agent.1w");
    assert.equal(readiness[0].readiness.state, "unknown");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("remote environment readiness accepts the SSH host alias and preserves the canonical environment", async () => {
  const root = await temporary_root();
  try {
    const ssh_config = join(root, "ssh_config");
    await writeFile(ssh_config, "Host agent.1w\n  HostName agent.1w\n", { mode: 0o600 });
    const compute_path = join(root, "compute.toml");
    await writeFile(compute_path, [
      'default_environment = "local"',
      "[environments.local]",
      'kind = "local"',
      "[environments.local.backends.xtb]",
      'command = "/bin/true"',
      "[environments.cluster_1w]",
      'kind = "remote"',
      `ssh_config = ${JSON.stringify(ssh_config)}`,
      'ssh_host = "agent.1w"',
      'remote_root = "/tmp/tspi-remote"',
      'allowed_queues = ["short"]',
      "[environments.cluster_1w.backends.xtb]",
      'command = ["xtb"]',
      "",
    ].join("\n"), "utf8");
    const host = await create_configured_capability_host({
      package_root: resolve("."),
      compute_config_path: compute_path,
      artifact_root: join(root, "artifacts"),
    });
    const readiness = await host.capability_assembly.readiness({
      capability_id: "xtb.sp",
      environment_id: "agent.1w",
      execution_kind: "remote",
    });
    assert.equal(readiness[0].environment_id, "cluster_1w");
    assert.equal(readiness[0].environment_kind, "compute");
    assert.equal(readiness[0].readiness.state, "unknown");
    assert.equal(readiness[0].readiness.checks.some((check) => check.name === "remote_transport" && check.state === "deferred"), true);
    const unavailable = await host.capability_assembly.readiness({
      capability_id: "xtb.sp",
      environment_id: "missing-environment",
      execution_kind: "remote",
    });
    assert.equal(unavailable[0].readiness.state, "unavailable");
    await assert.rejects(
      host.tool_gateway.invoke({
        workspace_mode: "research",
        capability_id: "xtb.sp",
        environment: { kind: "remote", environment: "agent.1w" },
        input: { xyz: "1\nH\nH 0 0 0\n" },
      }),
      (error) => error?.code === "remote_execution_requires_workspace_compute",
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
