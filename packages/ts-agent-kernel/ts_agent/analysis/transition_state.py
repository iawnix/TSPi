"""TS input construction, vibrational evidence, and bounded path summaries."""

from __future__ import annotations

import re

from .engine import number, outcome, xyz_frames, xyz_text


def gaussian_sections(inputs, p, role="log"):
    from ts_agent.backends.gaussian import select_job_section
    return select_job_section(inputs.text(role).splitlines(), p.get("section_index"))


def parse_modes(lines):
    from ts_agent.backends.gaussian import selected_frequency_table
    table = selected_frequency_table(lines)
    start = table.get("start_line")
    if start is None:
        return []
    modes, cursor = [], int(start) - 1
    while cursor < len(lines):
        if "Frequencies --" not in lines[cursor]:
            cursor += 1
            continue
        frequencies = [float(v.replace("D", "E")) for v in lines[cursor].split("--", 1)[1].split()]
        group = [{"frequency_cm1": f, "displacements": []} for f in frequencies]
        cursor += 1
        while cursor < len(lines) and "Frequencies --" not in lines[cursor]:
            if re.match(r"\s*Atom\s+AN\s+X\s+Y\s+Z", lines[cursor]):
                cursor += 1
                while cursor < len(lines):
                    fields = lines[cursor].split()
                    if len(fields) != 2 + 3 * len(group) or not fields[0].isdigit() or not fields[1].isdigit():
                        break
                    for i, mode in enumerate(group):
                        mode["displacements"].append([float(v.replace("D", "E")) for v in fields[2 + 3*i:5 + 3*i]])
                    cursor += 1
                break
            cursor += 1
        modes.extend(group)
    return modes


def gaussian_analyze(inputs, p):
    from ts_agent.backends.gaussian import final_geometry, extract_log_route, parse_convergence, selected_frequency_table, route_expectation
    section = gaussian_sections(inputs, p)
    lines = section["lines"]
    text = "\n".join(lines)
    atoms = final_geometry(lines)
    frequencies = selected_frequency_table(lines)["frequencies"]
    convergence, source = parse_convergence(lines)
    route = extract_log_route(lines)
    modes = parse_modes(lines)
    charge_match = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text)
    data = {
        "section_index": section["index"], "section_count": section["section_count"],
        "route": route, "route_expectation": route_expectation(p.get("expected_route"), route, text),
        "normal_termination": "Normal termination of Gaussian" in text and "Error termination" not in text,
        "stationary_point_found": "Stationary point found" in text,
        "converged": bool(convergence) and all(str(r["converged"]).upper() == "YES" for r in convergence.values()),
        "convergence": convergence, "convergence_source": source,
        "frequencies_cm1": frequencies, "imaginary_frequency_count": sum(f < 0 for f in frequencies),
        "modes": modes, "geometry": {"symbols": [a[0] for a in atoms], "coordinates": [list(a[1:]) for a in atoms]},
        "charge": int(charge_match[1]) if charge_match else None,
        "multiplicity": int(charge_match[2]) if charge_match else None,
    }
    files = {"stationary.xyz": xyz_text(data["geometry"]["symbols"], data["geometry"]["coordinates"])} if atoms else {}
    diagnostics = [] if atoms and frequencies else ["Selected section lacks geometry or frequencies."]
    return outcome("ts-gaussian-evidence/1", data, verdict="inconclusive" if diagnostics else "valid", diagnostics=diagnostics, files=files,
                   facts={"program.normal_termination": {"value": data["normal_termination"]}, "stationary_point.confirmed": {"value": data["stationary_point_found"]},
                          "optimization.converged": {"value": data["converged"]}, "vibration.imaginary_frequency_count": {"value": data["imaginary_frequency_count"]}})


def input_build(inputs, p):
    from ase.data import atomic_numbers

    task = p["task"]
    frames = [inputs.xyz("structures", i) for i in range(len(inputs.bindings["structures"]))]
    expected = 2 if task == "qst2" else 3 if task == "qst3" else 1
    if len(frames) != expected or any(f["symbols"] != frames[0]["symbols"] for f in frames):
        raise ValueError("Gaussian task requires the correct number of explicitly aligned geometries")
    electrons = sum(atomic_numbers[s] for s in frames[0]["symbols"]) - p["charge"]
    if electrons < p["multiplicity"] - 1 or (electrons - p["multiplicity"] + 1) % 2:
        raise ValueError("charge/multiplicity are incompatible with the geometry")
    method, basis = p["method"], p["basis"]
    for label, value in (("method", method), ("basis", basis)):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+*(),_.-]{0,95}", value):
            raise ValueError(f"unsupported {label}; use a single method/basis token")
    cycles = p.get("max_cycles", 100)
    drivers = {"sp": "SP", "opt": f"Opt=(MaxCycles={cycles})", "ts": f"Opt=(TS,CalcFC,MaxCycles={cycles})", "freq": "Freq",
               "opt_freq": f"Opt=(MaxCycles={cycles}) Freq", "qst2": f"Opt=(QST2,CalcFC,MaxCycles={cycles})", "qst3": f"Opt=(QST3,CalcFC,MaxCycles={cycles})"}
    if task == "irc":
        direction = p["direction"].capitalize()
        driver = f"IRC=(CalcFC,{direction},MaxPoints={p.get('max_points', 50)},StepSize={p.get('step_size', 10)})"
    else:
        driver = drivers[task]
    solvent = ""
    if "solvent" in p:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,63}", p["solvent"]):
            raise ValueError("invalid solvent token")
        solvent = f" SCRF=({p.get('solvent_model', 'SMD')},Solvent={p['solvent']})"
    route = f"#P {method}/{basis} {driver} Int=UltraFine{solvent}"
    text = f"%chk=analysis.chk\n%nprocshared={p.get('nproc', 1)}\n%mem={p.get('memory_mb', 1024)}MB\n{route}\n\n"
    for i, frame in enumerate(frames):
        text += f"Explicit {task} geometry {i}\n\n{p['charge']} {p['multiplicity']}\n"
        text += "".join(f"{s} {c[0]:.10f} {c[1]:.10f} {c[2]:.10f}\n" for s, c in zip(frame["symbols"], frame["coordinates"])) + "\n"
    return outcome("ts-gaussian-input/1", {"task": task, "route": route, "charge": p["charge"], "multiplicity": p["multiplicity"]}, files={"calculation.gjf": text},
                   limitations=["This constructs an input only. Launch through the existing Gaussian calculation capability."])


def extract_candidate(inputs, p):
    frames = xyz_frames(inputs.text("trajectory"))
    if any(f["symbols"] != frames[0]["symbols"] for f in frames):
        raise ValueError("trajectory atom order/elements changed")
    energies = p.get("energies")
    if p["selection"] == "highest_energy":
        if energies is None or len(energies) != len(frames):
            raise ValueError("highest-energy selection requires one explicit energy per frame")
        energies = [number(e, "path energy") for e in energies]
        selected = max(range(len(frames)), key=lambda i: energies[i])
    else:
        selected = p["index"]
        if not 0 <= selected < len(frames):
            raise ValueError("frame index is out of range")
    frame = frames[selected]
    return outcome("ts-path-candidate/1", {"frame_index": selected, "frame_count": len(frames), "selection": p["selection"],
                   "energy": energies[selected] if energies else None, "energy_unit": p.get("energy_unit"), "stationary_point_established": False},
                   files={"candidate.xyz": xyz_text(frame["symbols"], frame["coordinates"]),
                          "path_start.xyz": xyz_text(frames[0]["symbols"], frames[0]["coordinates"]),
                          "path_end.xyz": xyz_text(frames[-1]["symbols"], frames[-1]["coordinates"])},
                   limitations=["A selected path image, including a NEB maximum, is not a validated transition state."])


def analyze_mode(inputs, p):
    import numpy as np

    evidence = inputs.data("evidence", schema="ts-gaussian-evidence/1")
    modes = evidence["modes"]
    index = p["mode_index"]
    if not 0 <= index < len(modes):
        raise ValueError("mode_index is unavailable")
    mode = modes[index]
    coordinates = np.asarray(evidence["geometry"]["coordinates"], dtype=float)
    displacements = np.asarray(mode["displacements"], dtype=float)
    if not len(coordinates) or displacements.shape != coordinates.shape:
        return outcome("ts-vibrational-mode/1", {"mode_index": index, "frequency_cm1": mode["frequency_cm1"]}, verdict="inconclusive", diagnostics=["Normal-mode displacement vectors are missing or incomplete."])
    rows, derivatives, expected = [], [], []
    for bond in p["bonds"]:
        a, b = bond["atoms"]
        if a == b or min(a, b) < 0 or max(a, b) >= len(coordinates):
            raise ValueError("invalid mode bond indices")
        vector = coordinates[b] - coordinates[a]
        distance = float(np.linalg.norm(vector))
        if distance == 0:
            raise ValueError("coincident atoms cannot define a bond derivative")
        derivative = float(np.dot(vector / distance, displacements[b] - displacements[a]))
        rows.append({"atoms": [a, b], "distance_angstrom": distance, "mode_derivative": derivative, "expected_sign": bond["sign"]})
        derivatives.append(derivative)
        expected.append(bond["sign"])
    denom = float(np.linalg.norm(derivatives) * np.linalg.norm(expected))
    overlap = abs(float(np.dot(derivatives, expected))) / denom if denom > 0 else 0.0
    coupled = overlap >= p.get("minimum_overlap", 0.5) and denom > 0
    return outcome("ts-vibrational-mode/1", {"mode_index": index, "frequency_cm1": mode["frequency_cm1"], "bond_changes": rows,
                   "reaction_coordinate_overlap": overlap, "coupled": coupled, "sign_convention": "overall eigenvector sign is arbitrary"},
                   facts={"vibration.reaction_coordinate_overlap": {"value": overlap}},
                   limitations=["Overlap uses selected bond-length derivatives; it is evidence for a mode assignment, not complete reaction-coordinate validation."])


def endpoint_summary(inputs, p):
    from ts_agent.backends.gaussian import extract_log_route, parse_irc_path, orientation_blocks

    section = gaussian_sections(inputs, p)
    lines = section["lines"]
    path = parse_irc_path(lines, extract_log_route(lines))
    atoms = path["endpoint_atoms"]
    data = {key: value for key, value in path.items() if key not in {"endpoint_atoms", "coordinate_points"}}
    data["normal_termination"] = "Normal termination of Gaussian" in "\n".join(lines) and "Error termination" not in "\n".join(lines)
    first_point = next((i for i, line in enumerate(lines) if "Point Number:" in line), len(lines))
    geometries = orientation_blocks(lines[:first_point], "Standard orientation:") or orientation_blocks(lines[:first_point], "Input orientation:")
    data["initial_geometry"] = {"symbols": [a[0] for a in geometries[-1]], "coordinates": [list(a[1:]) for a in geometries[-1]]} if geometries else None
    complete = data["normal_termination"] and data["path_complete_marker"]
    return outcome("ts-path-endpoint-summary/1", data, verdict="valid" if complete else "inconclusive",
                   files={"endpoint.xyz": xyz_text([a[0] for a in atoms], [a[1:] for a in atoms], "Finite IRC endpoint; basin assignment requires evidence")},
                   limitations=["A finite IRC endpoint is not automatically an optimized minimum or the intended species."],
                   facts={"path.complete_marker": {"value": bool(complete)}})


def step_audit(inputs, p):
    ts = inputs.data("stationary", schema="ts-gaussian-evidence/1")
    checks = {"normal_termination": ts["normal_termination"], "stationary": ts["stationary_point_found"], "convergence": ts["converged"],
              "one_imaginary_frequency": ts["imaginary_frequency_count"] == 1}
    diagnostics = []
    if "mode" in inputs.bindings:
        mode = inputs.data("mode", schema="ts-vibrational-mode/1")
        document = inputs.document("mode")
        checks["mode_source"] = inputs.bindings["stationary"][0]["artifact_id"] in document["input_artifacts"].get("evidence", [])
        checks["mode_coupling"] = mode.get("coupled", False) and mode["frequency_cm1"] < 0
    else:
        checks["mode_coupling"] = None
    for direction in ("forward", "reverse"):
        if direction not in inputs.bindings:
            checks[f"{direction}_path"] = None
            continue
        path = inputs.data(direction, schema="ts-path-endpoint-summary/1")
        checks[f"{direction}_path"] = path["normal_termination"] and path["path_complete_marker"] and path["direction"] == direction
        start = path.get("initial_geometry")
        checks[f"{direction}_ts_origin"] = None
        if start and ts["geometry"]["symbols"]:
            import numpy as np
            if start["symbols"] != ts["geometry"]["symbols"]:
                checks[f"{direction}_ts_origin"] = False
            else:
                a, b = np.asarray(start["coordinates"]), np.asarray(ts["geometry"]["coordinates"])
                a, b = a-a.mean(axis=0), b-b.mean(axis=0)
                u, _, vt = np.linalg.svd(a.T @ b)
                rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
                checks[f"{direction}_ts_origin"] = bool(np.sqrt(np.mean(np.sum((a @ rotation-b)**2, axis=1))) <= p.get("origin_tolerance_angstrom", 0.001))
        role = direction + "_match"
        if role in inputs.bindings:
            comparison = inputs.json(role)
            if comparison.get("schema_version") != "ts-structure-comparison/1":
                raise ValueError("endpoint matches must be registered structure comparison artifacts")
            endpoint_id = inputs.document(direction)["output_artifacts"]["endpoint.xyz"]["artifact_id"]
            compared_ids = [row["artifact_id"] for row in comparison["inputs"].values()]
            target_id = p.get(direction + "_species_artifact_id")
            checks[f"{direction}_endpoint"] = None if target_id is None else endpoint_id != target_id and set(compared_ids) == {endpoint_id, target_id} and comparison["verdict"] == "matched"
        else:
            checks[f"{direction}_endpoint"] = None
    for key, value in checks.items():
        if value is not True:
            diagnostics.append(f"{key}: {'missing evidence' if value is None else 'not satisfied'}")
    verdict = "invalid" if any(v is False for v in checks.values()) else "inconclusive" if diagnostics else "valid"
    return outcome("ts-elementary-step-audit/1", {"step_key": p["step_key"], "checks": checks}, verdict=verdict, diagnostics=diagnostics,
                   limitations=["This audits selected structural evidence only; electronic-state/method consistency and scientific acceptance remain explicit Claim decisions."],
                   facts={"mechanism.step.structural_evidence_complete": {"value": not diagnostics}})


HANDLERS = {"gaussian.output.analyze": gaussian_analyze, "gaussian.input.build": input_build, "path.extract_candidate": extract_candidate,
            "vibration.analyze_mode": analyze_mode, "path.endpoint_summary": endpoint_summary, "mechanism.step.audit": step_audit}
