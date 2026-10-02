"""Stoichiometric reaction networks, including parallel steps and cycles."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy

from .engine import outcome
from .reaction import species_record, validate_spec


def step_define(inputs, p):
    reaction = inputs.data("reaction", schema="ts-reaction-spec/1")
    check = validate_spec(reaction)
    if check["verdict"] != "valid":
        raise ValueError("an elementary StepRecord requires a balanced closed ReactionSpec")
    evidence, diagnostics = {}, []
    for role, schema in (("audit", "ts-elementary-step-audit/1"), ("barrier", "ts-barrier-result/1"), ("rate", "ts-kinetic-result/1")):
        if role in inputs.bindings:
            evidence[role] = inputs.data(role, schema=schema)
            if inputs.json(role).get("verdict") != "valid":
                diagnostics.append(f"{role} evidence is not valid")
        else:
            diagnostics.append(f"{role} evidence is not attached")
    if "audit" in evidence and evidence["audit"]["step_key"] != p["step_key"]:
        raise ValueError("step audit belongs to a different step")
    if "barrier" in evidence and any(evidence["barrier"][side] != reaction[side] for side in ("reactants", "products")):
        raise ValueError("barrier participants differ from the ReactionSpec")
    if "rate" in evidence and "barrier" in evidence:
        bound = inputs.document("rate").get("input_artifacts", {}).get("barrier", [])
        if inputs.bindings["barrier"][0]["artifact_id"] not in bound:
            raise ValueError("rate is not derived from the attached barrier")
    data = {"step_key": p["step_key"], "reversible": p.get("reversible", False),
            "species": reaction["species"], "reactants": reaction["reactants"], "products": reaction["products"],
            "evidence": evidence, "evidence_verdicts": {role: inputs.json(role).get("verdict", "inconclusive") for role in evidence},
            "evidence_refs": {role: values[0]["artifact_id"] for role, values in inputs.bindings.items()}}
    verdict = "invalid" if "invalid" in data["evidence_verdicts"].values() else "inconclusive" if diagnostics else "valid"
    return outcome("ts-step-record/1", data, verdict=verdict, diagnostics=diagnostics,
                   limitations=["A recorded step remains a hypothesis until its evidence supports a separately accepted Claim."])


def _identity(species):
    return species["canonical_smiles"], species["charge"], species["multiplicity"]


def assemble(inputs, p):
    species, steps = {}, []
    aliases = p.get("species_aliases", {})
    for i in range(len(inputs.bindings["steps"])):
        source = inputs.data("steps", i, schema="ts-step-record/1")
        step = deepcopy(source)
        name = step["step_key"]
        if any(s["step_key"] == name for s in steps):
            raise ValueError("parallel steps require distinct step_key values")
        local = {}
        for record in step.pop("species"):
            key = aliases.get(f"{name}/{record['key']}", record["key"])
            if key in species and _identity(species[key]) != _identity(record):
                raise ValueError(f"species key {key} has conflicting chemical/electronic identities; provide explicit aliases")
            local[record["key"]] = key
            species.setdefault(key, {**record, "key": key})
        for side in ("reactants", "products"):
            coefficients = Counter()
            for row in step[side]:
                coefficients[local[row["species"]]] += row["coefficient"]
            step[side] = [{"species": key, "coefficient": value} for key, value in sorted(coefficients.items())]
        step["source_artifact_id"] = inputs.bindings["steps"][i]["artifact_id"]
        steps.append(step)
    data = {"species": list(species.values()), "steps": steps, "scope": p["scope"]}
    audit = audit_data(data)
    data["audit"] = audit
    if "initial_species" in p:
        data["paths"] = enumerate_paths(data, p)
    return outcome("ts-network-snapshot/1", data, verdict=audit["verdict"], diagnostics=audit["diagnostics"],
                   facts={"mechanism.network.step_count": {"value": len(steps)}, "mechanism.network.species_count": {"value": len(species)}})


def audit_data(data):
    if not 1 <= len(data.get("steps", [])) <= 64 or not 1 <= len(data.get("species", [])) <= 4096:
        raise ValueError("network exceeds bounded species/step limits")
    species = {s["key"]: s for s in data["species"]}
    diagnostics, missing, contradictions, adjacency = [], [], [], {key: set() for key in species}
    if len(species) != len(data["species"]):
        diagnostics.append("duplicate species keys")
    for s in species.values():
        if s != species_record(s["key"], s["smiles"], s["multiplicity"], s.get("role", "participant")):
            diagnostics.append(f"species {s['key']} identity is inconsistent")
    seen = set()
    for step in data["steps"]:
        name = step["step_key"]
        if name in seen:
            diagnostics.append(f"duplicate step key {name}")
        seen.add(name)
        try:
            used = {r["species"] for side in ("reactants", "products") for r in step[side]}
            checked = validate_spec({"species": [s for k, s in species.items() if k in used], "reactants": step["reactants"], "products": step["products"], "boundary": "closed"})
            diagnostics.extend(f"{name}: {message}" for message in checked["diagnostics"])
        except (KeyError, ValueError) as exc:
            diagnostics.append(f"{name}: {exc}")
        directions = [("reactants", "products")]
        if step["reversible"]:
            directions.append(("products", "reactants"))
        for side_a, side_b in directions:
            for a in step[side_a]:
                for b in step[side_b]:
                    if a["species"] in adjacency and b["species"] in adjacency:
                        adjacency[a["species"]].add(b["species"])
        for role in ("audit", "barrier", "rate"):
            if role not in step["evidence"]:
                missing.append(f"{name}: {role}")
            elif step.get("evidence_verdicts", {}).get(role) != "valid":
                missing.append(f"{name}: {role} evidence is not valid")
                if step.get("evidence_verdicts", {}).get(role) == "invalid":
                    contradictions.append(f"{name}: {role} evidence contradicts the step")
        audit = step["evidence"].get("audit")
        if audit and not all(value is True for value in audit["checks"].values()):
            missing.append(f"{name}: structural evidence is incomplete")
    # Reachability detects membership of cycles without imposing a DAG rule.
    cyclic = []
    for start in adjacency:
        pending, visited = list(adjacency[start]), set()
        while pending:
            current = pending.pop()
            if current == start:
                cyclic.append(start)
                break
            if current not in visited:
                visited.add(current)
                pending.extend(adjacency[current] - visited)
    return {"verdict": "invalid" if diagnostics or contradictions else "inconclusive" if missing else "valid", "diagnostics": diagnostics + contradictions + missing,
            "cycle_species": sorted(cyclic), "missing_evidence": missing, "chemistry_balanced": not diagnostics,
            "cycle_semantics": "species projection may contain cycles; reaction hyperedges retain all stoichiometric participants"}


def enumerate_paths(data, p):
    species_keys = {s["key"] for s in data["species"]}
    initial, target = set(p["initial_species"]), set(p["target_species"])
    if not initial <= species_keys or not target <= species_keys:
        raise ValueError("path endpoints refer to unknown species")
    maximum, depth = p.get("max_paths", 16), p.get("max_depth", 8)
    pending, paths, examined, truncated = [(initial, [])], [], 0, False
    while pending and examined < 10000:
        available, path = pending.pop(0)
        examined += 1
        if target <= available:
            paths.append(path)
            if len(paths) >= maximum:
                truncated = bool(pending)
                break
            continue
        if len(path) >= depth:
            truncated = True
            continue
        for step in data["steps"]:
            for direction in (["forward", "reverse"] if step["reversible"] else ["forward"]):
                left, right = ("reactants", "products") if direction == "forward" else ("products", "reactants")
                reactants = {s["species"] for s in step[left]}
                products = {s["species"] for s in step[right]}
                if reactants <= available and products - available:
                    if len(pending) + examined >= 10000:
                        truncated = True
                        continue
                    pending.append((available | products, [*path, {"step": step["step_key"], "direction": direction}]))
    truncated |= bool(pending)
    return {"paths": paths, "truncated": truncated, "states_examined": examined,
            "semantics": "qualitative reachability with available co-reactants; no concentrations, stoichiometric depletion or kinetic preference"}


def audit(inputs, p):
    data = inputs.data("network", schema="ts-network-snapshot/1")
    result = audit_data(data)
    return outcome("ts-network-audit/1", result, verdict=result["verdict"], diagnostics=result["diagnostics"], facts={"mechanism.network.balanced": {"value": result["chemistry_balanced"]}})


def energy_profile(inputs, p):
    network = inputs.data("network", schema="ts-network-snapshot/1")
    steps = {s["step_key"]: s for s in network["steps"]}
    available = Counter(p["initial_composition"])
    if not set(available) <= {s["key"] for s in network["species"]}:
        raise ValueError("initial composition contains unknown species")
    current, points, conditions, methods = 0.0, [{"label": "initial", "energy": 0.0, "kind": "state"}], None, None
    for row in p["path"]:
        step = steps[row["step"]]
        direction = row.get("direction", "forward")
        if direction == "reverse" and not step["reversible"]:
            raise ValueError("requested reverse traversal of an irreversible step")
        barrier = step["evidence"].get("barrier")
        if barrier is None or barrier["quantity"] != "G":
            raise ValueError("energy profile requires explicit Gibbs barriers for every selected step")
        if conditions is None:
            conditions, methods = barrier["conditions"], barrier["methods"]
        if barrier["conditions"] != conditions or barrier["methods"] != methods:
            raise ValueError("energy profile cannot mix conditions or methods")
        left, right = ("reactants", "products") if direction == "forward" else ("products", "reactants")
        if any(available[s["species"]] < s["coefficient"] for s in step[left]):
            raise ValueError("path consumes an unavailable stoichiometric participant")
        for s in step[left]:
            available[s["species"]] -= s["coefficient"]
        for s in step[right]:
            available[s["species"]] += s["coefficient"]
        points.append({"label": f"{step['step_key']} TS", "energy": current + barrier[direction], "kind": "transition_state", "source_artifact_id": step["evidence_refs"]["barrier"]})
        current += barrier["reaction"] * (1 if direction == "forward" else -1)
        points.append({"label": step["step_key"], "energy": current, "kind": "state", "source_artifact_id": step["evidence_refs"]["barrier"]})
    data = {"points": points, "unit": "kJ/mol", "reference": "explicit initial composition", "initial_composition": p["initial_composition"],
            "final_composition": dict(available), "conditions": conditions, "methods": methods}
    curve = {"schema_version": "ts-curve-data/1", "title": "Selected mechanism Gibbs energy profile", "x_label": "Selected path position",
             "y_label": "Relative Gibbs energy", "y_unit": "kJ/mol", "series": [{"name": "Selected path", "x": list(range(len(points))), "y": [row["energy"] for row in points]}]}
    return outcome("ts-mechanism-energy-profile/1", data, files={"energy_profile.json": json.dumps(curve, sort_keys=True) + "\n"},
                   limitations=["The selected path and initial pool define this profile; it does not identify the dominant network pathway."])


HANDLERS = {"mechanism.step.define": step_define, "mechanism.network.assemble": assemble, "mechanism.network.audit": audit, "mechanism.energy_profile": energy_profile}
