# TSPi Improvement Plan

[English](IMPROVEMENT_PLAN.md) | [简体中文](IMPROVEMENT_PLAN.zh-CN.md)

This document records architectural planning and accepted design constraints.
It is not a release checklist or a claim that every historical milestone is
still pending. The current runtime uses one installation-wide native Pi App
Server Host, while TS Phone is an independent Radius client.

## Goals and Boundaries

- Keep the `ts-web` source and release boundary explicit inside `components/ts-web/`.
- Keep the Research Kernel as the only canonical scientific-state mutator.
- Keep scientific capabilities extensible through registries and Skills rather
  than a reaction-specific workflow router.
- Make clean installation, diagnostics, package validation, and recovery
  repeatable.

The current Web component consists of its provider client, registry, HTTP
server, static assets, and component manifest. It consumes a versioned,
read-only projection and must not import private Kernel modules or write a
workspace directly. The old embedded Web implementation and Suite `/3`
compatibility path are historical migration context, not supported runtime
paths.

## Scientific State and Gates

Root Agent decisions create bounded ResearchNodes through `ts_change`. Claims,
Observations, Findings, ProofSpecs, GateSpecs, and GateResults remain explicit
records. A NodeGate checks whether one bounded task may close; a ClaimGate
evaluates declared evidence but does not automatically change Claim status or
create Acceptance. The Kernel validates and commits; it does not select the
next scientific action.

## Delivery and CI

The fast job covers Python contracts, TypeScript checks, and public terminology.
Component checks cover `components/ts-web`, manifests, Pi adapters, and protocol
compatibility. Release checks build the Agent wheel, optional Web archive, and
suite manifest, then install into a fresh private directory. Tests must reject
stale manifests, unsafe paths, unknown extension entries, and source tampering.

Remote execution and notification delivery remain explicit capabilities. A
remote profile must not copy credentials into a client. TS Web remains read-only
and TS Phone is never assembled as a TSPi Phone server or bridge.

## Scale and Observability

Operational revisions, Attempt receipts, artifact digests, and bounded
frontier/delta projections are the audit trail. The Web projection may show
trajectory, evidence, gates, findings, and runs, but it must not infer a Phase
status, Claim verdict, chemical direction, or successor Node.

Future work should add capability implementations, schemas, focused tests, and
versioned descriptors. It should not add a central hypothesis-to-calculation
switch statement or another scientific state store.
