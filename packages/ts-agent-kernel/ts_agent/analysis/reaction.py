"""Closed molecular reactions, bounded mapping proposals, and bond changes."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy

from .engine import outcome
from ts_agent.reaction.mapping import validate_atom_mapping


def species_record(key, smiles, multiplicity, role="participant"):
    from rdkit import Chem

    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError(f"invalid SMILES for {key}")
    if len(Chem.GetMolFrags(mol)) != 1:
        raise ValueError("each species must be one connected molecular component")
    mol = Chem.AddHs(mol)
    if mol.GetNumAtoms() > 256:
        raise ValueError("species exceeds 256 explicit atoms")
    charge = sum(a.GetFormalCharge() for a in mol.GetAtoms())
    electrons = sum(a.GetAtomicNum() for a in mol.GetAtoms()) - charge
    if type(multiplicity) is not int or not 1 <= multiplicity <= min(21, electrons + 1) or (electrons - multiplicity + 1) % 2:
        raise ValueError(f"{key}: multiplicity is incompatible with electron count")
    atoms = [{"element": a.GetSymbol(), "isotope": a.GetIsotope(), "formal_charge": a.GetFormalCharge(),
              "map_number": a.GetAtomMapNum(), "chiral_tag": str(a.GetChiralTag())} for a in mol.GetAtoms()]
    bonds = [{"atoms": sorted((b.GetBeginAtomIdx(), b.GetEndAtomIdx())), "order": b.GetBondTypeAsDouble()} for b in mol.GetBonds()]
    unmapped = Chem.Mol(mol)
    for atom in unmapped.GetAtoms():
        atom.SetAtomMapNum(0)
    return {
        "key": key, "smiles": smiles, "canonical_smiles": Chem.MolToSmiles(Chem.RemoveHs(unmapped), isomericSmiles=True),
        "charge": charge, "multiplicity": multiplicity, "role": role,
        "atoms": atoms, "bonds": sorted(bonds, key=lambda b: b["atoms"]),
    }


def parse(inputs, p):
    if "reaction_smiles" in p:
        text = p["reaction_smiles"]
        if text.count(">>") != 1:
            raise ValueError("reaction_smiles requires reactants>>products; include participating catalysts explicitly")
        sides = text.split(">>")
        spec = {"species": [], "reactants": [], "products": [], "conditions": p.get("conditions", {}), "boundary": p.get("boundary", "closed")}
        for side, text in zip(("reactants", "products"), sides):
            molecules = text.split(".")
            if not 1 <= len(molecules) <= 64:
                raise ValueError("reaction supports at most 64 components per side")
            spins = p["multiplicities"][side]
            if len(spins) != len(molecules):
                raise ValueError(f"one explicit multiplicity is required per {side} component")
            for i, (smiles, spin) in enumerate(zip(molecules, spins)):
                key = f"{side[0]}{i}"
                spec["species"].append(species_record(key, smiles, spin))
                spec[side].append({"species": key, "coefficient": 1})
    else:
        spec = {"species": [species_record(s["key"], s["smiles"], s["multiplicity"], s.get("role", "participant")) for s in p["species"]],
                "reactants": p["reactants"], "products": p["products"], "conditions": p.get("conditions", {}), "boundary": p.get("boundary", "closed")}
    checked = validate_spec(spec)
    files = {f"species_{s['key']}.json": json.dumps({"schema_version": "ts-species-record/1", "data": s}, sort_keys=True) + "\n" for s in spec["species"]}
    return outcome("ts-reaction-spec/1", spec, verdict=checked["verdict"], diagnostics=checked["diagnostics"],
                   limitations=["Multiplicity is declared and checked for electron parity; surface continuity is not inferred."],
                   facts={"reaction.balanced": {"value": checked["balanced"]}}, files=files)


def validate_spec(spec):
    if not isinstance(spec, dict) or not 1 <= len(spec.get("species", [])) <= 128 or any(not 1 <= len(spec.get(side, [])) <= 64 for side in ("reactants", "products")):
        raise ValueError("ReactionSpec exceeds bounded species/stoichiometry limits")
    if spec.get("boundary") != "closed":
        return {"verdict": "unsupported", "balanced": False, "diagnostics": ["Open reservoirs/electron exchange require a separate model."]}
    species = {s["key"]: s for s in spec["species"]}
    if len(species) != len(spec["species"]):
        raise ValueError("species keys must be unique")
    counts, charges, diagnostics = {}, {}, []
    for side in ("reactants", "products"):
        if not spec[side]:
            raise ValueError(f"{side} is empty")
        counts[side], charges[side] = Counter(), 0
        for row in spec[side]:
            coefficient = row["coefficient"]
            if type(coefficient) is not int or not 1 <= coefficient <= 64 or row["species"] not in species:
                raise ValueError("invalid stoichiometry or unknown species")
            s = species[row["species"]]
            # Recreate identity from the authoritative SMILES and declared spin.
            expected = species_record(s["key"], s["smiles"], s["multiplicity"], s.get("role", "participant"))
            if s != expected:
                raise ValueError("SpeciesRecord does not match its chemical identity")
            counts[side].update({f"{element}:{isotope}": coefficient * n for (element, isotope), n in Counter((a["element"], a["isotope"]) for a in s["atoms"]).items()})
            charges[side] += coefficient * s["charge"]
        if sum(row["coefficient"] for row in spec[side]) > 64:
            raise ValueError("reaction supports at most 64 occurrences per side")
    if counts["reactants"] != counts["products"]:
        diagnostics.append("Whole-reaction element/isotope counts differ.")
    if charges["reactants"] != charges["products"]:
        diagnostics.append("Whole-reaction charge is not conserved.")
    return {"verdict": "invalid" if diagnostics else "valid", "balanced": not diagnostics,
            "element_isotope_counts": {k: dict(v) for k, v in counts.items()}, "charges": charges, "diagnostics": diagnostics}


def validate(inputs, p):
    spec = inputs.data("reaction", schema="ts-reaction-spec/1")
    result = validate_spec(spec)
    return outcome("ts-reaction-validation/1", result, verdict=result["verdict"], diagnostics=result["diagnostics"], facts={"reaction.balanced": {"value": result["balanced"]}})


def expanded(spec, side):
    lookup = {s["key"]: s for s in spec["species"]}
    species = [lookup[row["species"]] for row in spec[side] for _ in range(row["coefficient"])]
    if len(species) > 64 or sum(len(s["atoms"]) for s in species) > 256:
        raise ValueError("reaction analysis supports 64 occurrences and 256 atoms per side")
    refs, labels, edges = [], [], {}
    for i, s in enumerate(species):
        offset = len(refs)
        refs.extend({"species": i, "atom": j} for j in range(len(s["atoms"])))
        labels.extend((a["element"], a["isotope"]) for a in s["atoms"])
        edges.update({tuple(offset + a for a in b["atoms"]): b["order"] for b in s["bonds"]})
    return species, refs, labels, edges


def mapping_generate(inputs, p):
    spec = inputs.data("reaction", schema="ts-reaction-spec/1")
    check = validate_spec(spec)
    if check["verdict"] != "valid":
        return outcome("ts-reaction-mapping-candidates/1", {"candidates": [], "truncated": False}, verdict=check["verdict"], diagnostics=check["diagnostics"])
    ls, lr, labels, le = expanded(spec, "reactants")
    rs, rr, targets, re = expanded(spec, "products")
    maximum, max_states = p.get("max_candidates", 8), p.get("max_states", 20000)
    options = {i: [j for j, target in enumerate(targets) if target == label] for i, label in enumerate(labels)}
    degree = Counter(a for bond in le for a in bond)
    order = sorted(range(len(labels)), key=lambda i: (labels[i][0] == "H", len(options[i]), -degree[i], i))
    selected, used, best, visited, truncated = {}, set(), [], 0, False
    best_cost = float("inf")

    def visit(depth, cost):
        nonlocal visited, truncated, best_cost, best
        if visited >= max_states:
            truncated = True
            return
        visited += 1
        if cost > best_cost:
            return
        if depth == len(order):
            if cost < best_cost:
                best_cost, best = cost, []
            if len(best) < maximum:
                best.append({"cost": cost, "mapping": [{"reactant": lr[i], "product": rr[selected[i]]} for i in range(len(labels))]})
            else:
                truncated = True
            return
        atom = order[depth]
        scored = []
        for target in options[atom]:
            if target in used:
                continue
            delta = sum(abs(le.get(tuple(sorted((atom, a))), 0) - re.get(tuple(sorted((target, b))), 0)) for a, b in selected.items())
            scored.append((delta, target))
        for delta, target in sorted(scored):
            selected[atom] = target
            used.add(target)
            visit(depth + 1, cost + delta)
            used.remove(target)
            del selected[atom]
            if visited >= max_states:
                break

    visit(0, 0.0)
    return outcome("ts-reaction-mapping-candidates/1", {"candidates": best, "states_visited": visited, "truncated": truncated,
                   "ambiguity": len(best) != 1 or truncated, "objective": "sum of absolute bond-order edits"},
                   verdict="inconclusive" if len(best) != 1 or truncated else "valid",
                   limitations=["Graph-edit minimization proposes correspondence, not chemical mechanism.", "Symmetric/proton maps require explicit selection; bounded search may omit better maps."],
                   facts={"reaction.mapping.candidate_count": {"value": len(best)}})


def selected_mapping(inputs, p):
    if "mapping" in p:
        return p["mapping"]
    if "mapping" not in inputs.bindings:
        raise ValueError("supply an explicit mapping or a mapping artifact and candidate_index")
    record = inputs.json("mapping")
    if record.get("schema_version") == "ts-reaction-mapping-validation/1":
        return record["mapping"]
    choices = record.get("data", record).get("candidates", [])
    index = p.get("candidate_index")
    if type(index) is not int or not 0 <= index < len(choices):
        raise ValueError("select a valid candidate_index; a mapping is never selected automatically")
    return choices[index]["mapping"]


def bond_changes(inputs, p):
    spec = inputs.data("reaction", schema="ts-reaction-spec/1")
    if validate_spec(spec)["verdict"] != "valid":
        raise ValueError("bond changes require a balanced closed ReactionSpec")
    ls, lr, labels, le = expanded(spec, "reactants")
    rs, rr, targets, re = expanded(spec, "products")
    mapping = selected_mapping(inputs, p)
    checked = validate_atom_mapping([[a["element"] for a in s["atoms"]] for s in ls], [[a["element"] for a in s["atoms"]] for s in rs], mapping)
    if not checked["valid"]:
        raise ValueError("bond changes require a complete valid atom mapping")
    left_index = {(r["species"], r["atom"]): i for i, r in enumerate(lr)}
    right_index = {(r["species"], r["atom"]): i for i, r in enumerate(rr)}
    reverse = {}
    for pair in mapping:
        a = left_index[(pair["reactant"]["species"], pair["reactant"]["atom"])]
        b = right_index[(pair["product"]["species"], pair["product"]["atom"])]
        if labels[a] != targets[b]:
            raise ValueError("mapping changes isotope identity")
        reverse[b] = a
    mapped_edges = {tuple(sorted(reverse[a] for a in key)): value for key, value in re.items()}
    changes = {"formed": [], "broken": [], "order_changed": []}
    center = set()
    for edge in sorted(set(le) | set(mapped_edges)):
        before, after = le.get(edge, 0), mapped_edges.get(edge, 0)
        if before == after:
            continue
        kind = "formed" if before == 0 else "broken" if after == 0 else "order_changed"
        changes[kind].append({"atoms": [lr[a] for a in edge], "before": before, "after": after})
        center.update(edge)
    return outcome("ts-reaction-bond-changes/1", {**changes, "reaction_center": [lr[a] for a in sorted(center)]},
                   facts={"reaction.bond_change_count": {"value": sum(map(len, changes.values()))}})


HANDLERS = {"reaction.parse": parse, "reaction.validate": validate, "reaction.mapping.generate": mapping_generate, "reaction.bond_changes": bond_changes}
