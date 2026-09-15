"""Explicit thermal models and stoichiometric energy differences."""

from __future__ import annotations

import contextlib
import io
import math
import re
from collections import Counter

from .engine import number, outcome

HARTREE_KJ_MOL = 2625.4996394799
EV_KJ_MOL = 96.4853321233
R_KJ = 0.00831446261815324
R_L_BAR = 0.0831446261815324


def standard_concentration(standard, temperature):
    value = number(standard["value"], "standard state", positive=True)
    if standard["kind"] == "concentration" and standard["unit"] == "mol/L":
        return value
    if standard["kind"] == "pressure" and standard["unit"] in {"bar", "atm", "Pa"}:
        pressure_bar = value * {"bar": 1, "atm": 1.01325, "Pa": 1e-5}[standard["unit"]]
        return pressure_bar / (R_L_BAR * temperature)
    raise ValueError("unsupported standard state; use mol/L, bar, atm or Pa")


def _source(inputs, role, section_index):
    from ts_agent.backends.gaussian import select_job_section, final_geometry, parse_thermochemistry, extract_log_route, selected_frequency_table

    section = select_job_section(inputs.text(role).splitlines(), section_index)
    lines = section["lines"]
    text = "\n".join(lines)
    state = re.search(r"Charge\s*=\s*(-?\d+)\s+Multiplicity\s*=\s*(\d+)", text)
    scf_methods = re.findall(r"SCF Done:\s+E\(([^)]+)\)", text)
    return {
        **parse_thermochemistry(lines), "geometry": final_geometry(lines),
        "frequencies": selected_frequency_table(lines)["frequencies"],
        "route": extract_log_route(lines), "charge": int(state[1]) if state else None,
        "multiplicity": int(state[2]) if state else None,
        "normal_termination": "Normal termination of Gaussian" in text and "Error termination" not in text,
        "scf_method": scf_methods[-1] if scf_methods else None,
        "post_scf_energy": bool(re.search(r"(?:EUMP[2-5]|E\(CORR\)|CCSD\(T\)|E2)\s*=", text)),
    }


def evaluate(inputs, p):
    import numpy as np

    electronic = _source(inputs, "electronic", p.get("electronic_section"))
    thermal = _source(inputs, "thermal", p.get("thermal_section")) if "thermal" in inputs.bindings else electronic
    conditions, methods = p["conditions"], p["methods"]
    if conditions["phase"] == "solution" and not conditions.get("solvent"):
        raise ValueError("solution thermochemistry requires an explicit solvent")
    temperature = number(conditions["temperature_k"], "temperature", positive=True)
    source_standard = conditions["source_standard_state"]
    target_standard = conditions["standard_state"]
    target_c = standard_concentration(target_standard, temperature)
    source_c = standard_concentration(source_standard, temperature)
    quantity, model = p["quantity"], p.get("model", {"kind": "parsed"})
    diagnostics = []
    scf_method = (electronic["scf_method"] or "").lower().replace("-", "")
    declared_method = methods["electronic"].split("/", 1)[0].lower().replace("-", "")
    scf_aliases = {scf_method}
    for prefix in ("ro", "r", "u"):
        if scf_method.startswith(prefix):
            scf_aliases.add(scf_method[len(prefix):])
    if declared_method not in scf_aliases or electronic["post_scf_energy"]:
        diagnostics.append("Electronic-energy extraction supports bound HF/Kohn-Sham SCF totals only; correlated energy requires a separate parser.")
    for label, source, method in (("electronic", electronic, methods["electronic"]), ("thermal", thermal, methods.get("thermal", methods["electronic"]))):
        if not source["normal_termination"]:
            diagnostics.append(f"{label} source did not terminate normally")
        if not source["route"] or method.lower() not in source["route"].lower().split():
            diagnostics.append(f"{label} method cannot be matched to its log route")
        route = (source["route"] or "").lower().replace(" ", "")
        if conditions["phase"] == "solution" and f"solvent={conditions['solvent'].lower()}" not in route:
            diagnostics.append(f"{label} solvent cannot be matched to its log route")
        if conditions["phase"] == "gas" and "scrf" in route:
            diagnostics.append(f"{label} solution route conflicts with the declared gas phase")
        if source["charge"] != p["electronic_state"]["charge"] or source["multiplicity"] != p["electronic_state"]["multiplicity"]:
            diagnostics.append(f"{label} charge/multiplicity binding is missing or inconsistent")
    composite = inputs.bindings.get("thermal", inputs.bindings["electronic"])[0]["artifact_id"] != inputs.bindings["electronic"][0]["artifact_id"]
    if composite:
        if not methods.get("composite", False):
            raise ValueError("mixing electronic and thermal sources requires explicit methods.composite")
        a, b = electronic["geometry"], thermal["geometry"]
        if not a or not b or [x[0] for x in a] != [x[0] for x in b]:
            diagnostics.append("composite sources have missing or incompatible atom identity")
        else:
            x, y = np.array([r[1:] for r in a]), np.array([r[1:] for r in b])
            x, y = x - x.mean(axis=0), y - y.mean(axis=0)
            u, _, vt = np.linalg.svd(x.T @ y)
            rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
            rmsd = float(np.sqrt(np.mean(np.sum((x @ rotation - y)**2, axis=1))))
            if rmsd > p.get("geometry_tolerance_angstrom", 0.001):
                diagnostics.append("composite electronic/thermal geometries differ beyond the declared tolerance")
    energy = electronic["electronic_energy_hartree"]
    if not electronic["geometry"]:
        diagnostics.append("electronic source geometry is missing")
    if energy is None:
        diagnostics.append("electronic energy is missing")
    if diagnostics:
        return outcome("ts-thermochemical-result/1", {"species_key": p["species_key"], "quantity": quantity, "value": None}, verdict="inconclusive", diagnostics=diagnostics)
    value = energy * HARTREE_KJ_MOL
    correction = 0.0
    if quantity != "E":
        frequencies = thermal["frequencies"]
        n_imaginary = sum(f < 0 for f in frequencies)
        expected_imaginary = 1 if p["stationary_kind"] == "transition_state" else 0
        geometry = thermal["geometry"]
        xyz = np.array([r[1:] for r in geometry])
        linear = len(geometry) > 1 and np.linalg.matrix_rank(xyz - xyz.mean(axis=0), tol=1e-6) == 1
        actual_kind = "monatomic" if len(geometry) == 1 else "linear" if linear else "nonlinear"
        expected_modes = 0 if len(geometry) == 1 else 3 * len(geometry) - (5 if linear else 6)
        if not geometry or n_imaginary != expected_imaginary or len(frequencies) != expected_modes or any(f == 0 for f in frequencies):
            return outcome("ts-thermochemical-result/1", {"value": None}, verdict="inconclusive", diagnostics=["Thermal source has missing modes or the wrong number of unstable modes."])
        if model["kind"] == "parsed":
            if model.get("frequency_scale", 1) != 1 or "symmetry_number" in model:
                raise ValueError("parsed corrections cannot be rescaled; choose an explicit RRHO model")
            if quantity in {"H", "G"}:
                if thermal["temperature_k"] is None or abs(thermal["temperature_k"] - temperature) > 0.01:
                    raise ValueError("parsed thermal correction temperature differs or is missing")
                if thermal["pressure_atm"] is None:
                    raise ValueError("parsed thermal correction pressure is missing")
                actual_c = standard_concentration({"kind": "pressure", "unit": "atm", "value": thermal["pressure_atm"]}, temperature)
                if not math.isclose(actual_c, source_c, rel_tol=1e-5):
                    raise ValueError("source standard state differs from parsed pressure")
            key = {"E_ZPE": "zero_point_correction_hartree", "H": "thermal_enthalpy_correction_hartree", "G": "thermal_gibbs_correction_hartree"}[quantity]
            if thermal[key] is None:
                raise ValueError(f"missing {key}; electronic energy cannot substitute for it")
            correction = thermal[key] * HARTREE_KJ_MOL
        else:
            from ase import Atoms
            from ase.thermochemistry import IdealGasThermo
            from ase.units import invcm

            geometry = thermal["geometry"]
            if not geometry:
                raise ValueError("RRHO requires geometry")
            scale = model.get("frequency_scale", 1.0)
            positive = [f * scale * invcm for f in frequencies if f > 0]
            expected = 0 if model["geometry"] == "monatomic" else 3*len(geometry) - (5 if model["geometry"] == "linear" else 6)
            if model["geometry"] != actual_kind:
                raise ValueError("RRHO geometry classification conflicts with the source coordinates")
            if len(positive) != expected - expected_imaginary:
                raise ValueError("RRHO requires the complete stable vibrational spectrum")
            atomset = Atoms(symbols=[r[0] for r in geometry], positions=[r[1:] for r in geometry])
            import inspect
            mode_options = {"vib_selection": "all"} if "vib_selection" in inspect.signature(IdealGasThermo).parameters else {}
            thermo = IdealGasThermo(positive, geometry=model["geometry"], atoms=atomset, symmetrynumber=model["symmetry_number"], spin=(p["electronic_state"]["multiplicity"] - 1)/2, potentialenergy=0, **mode_options)
            pressure_pa = source_c * 1000 * 8.31446261815324 * temperature
            with contextlib.redirect_stdout(io.StringIO()):
                correction_ev = thermo.get_ZPE_correction() if quantity == "E_ZPE" else thermo.get_enthalpy(temperature, verbose=False) if quantity == "H" else thermo.get_gibbs_energy(temperature, pressure_pa, verbose=False)
            correction = float(correction_ev) * EV_KJ_MOL
        value += correction
    standard_correction = R_KJ * temperature * math.log(target_c / source_c) if quantity == "G" else 0.0
    value += standard_correction
    atoms = Counter(r[0] for r in electronic["geometry"])
    data = {"species_key": p["species_key"], "quantity": quantity, "value": value, "unit": "kJ/mol",
            "electronic_energy_kj_mol": energy * HARTREE_KJ_MOL, "thermal_correction_kj_mol": correction,
            "standard_state_correction_kj_mol": standard_correction, "conditions": conditions, "methods": methods,
            "electronic_state": p["electronic_state"], "element_counts": dict(atoms), "model": model, "stationary_kind": p["stationary_kind"]}
    return outcome("ts-thermochemical-result/1", data, facts={f"thermochemistry.{quantity}": {"value": value, "unit": "kJ/mol"}},
                   limitations=["Harmonic ideal-gas thermal model; no conformer ensemble, anharmonicity or automatic quasi-harmonic correction."])


def barrier(inputs, p):
    left = [inputs.data("reactants", i, schema="ts-thermochemical-result/1") for i in range(len(inputs.bindings["reactants"]))]
    right = [inputs.data("products", i, schema="ts-thermochemical-result/1") for i in range(len(inputs.bindings["products"]))]
    ts = inputs.data("transition_state", schema="ts-thermochemical-result/1")
    coefficients = {"reactants": p.get("reactant_coefficients", [1]*len(left)), "products": p.get("product_coefficients", [1]*len(right))}
    for side, values in (("reactants", left), ("products", right)):
        if len(values) != len(coefficients[side]):
            raise ValueError("stoichiometric coefficients must match the energy list")
    for record in [*left, *right, ts]:
        if record.get("value") is None:
            raise ValueError("all barrier inputs require complete thermochemical results")
        if record["unit"] != "kJ/mol" or record["quantity"] != ts["quantity"] or record["conditions"] != ts["conditions"] or record["methods"] != ts["methods"]:
            raise ValueError("barrier inputs differ in quantity, units, conditions or model chemistry")
        if record["model"].get("kind") != ts["model"].get("kind") or record["model"].get("frequency_scale", 1) != ts["model"].get("frequency_scale", 1):
            raise ValueError("barrier inputs use incompatible thermal models or frequency scales")
    if any(record["stationary_kind"] != "minimum" for record in [*left, *right]):
        raise ValueError("reactant/product thermal records must describe minima")
    totals = {}
    for side, values in (("reactants", left), ("products", right)):
        elements, charge, energy = Counter(), 0, 0.0
        possible_spins = {0}
        for item, coefficient in zip(values, coefficients[side]):
            energy += number(item["value"], "energy") * coefficient
            elements.update({element: count * coefficient for element, count in item["element_counts"].items()})
            charge += item["electronic_state"]["charge"] * coefficient
            for _ in range(coefficient):
                spin = item["electronic_state"]["multiplicity"] - 1
                possible_spins = {z for old in possible_spins for z in range(abs(old-spin), old+spin+1, 2)}
        if dict(elements) != ts["element_counts"] or charge != ts["electronic_state"]["charge"]:
            raise ValueError("barrier stoichiometry does not conserve TS composition/charge")
        if ts["electronic_state"]["multiplicity"] - 1 not in possible_spins:
            raise ValueError("declared TS spin cannot couple to the supplied species states")
        totals[side] = energy
    if ts["stationary_kind"] != "transition_state":
        raise ValueError("transition_state input is not identified as a TS thermal model")
    forward, reverse = ts["value"] - totals["reactants"], ts["value"] - totals["products"]
    participants = {side: [{"species": item["species_key"], "coefficient": coefficient} for item, coefficient in zip(values, coefficients[side])] for side, values in (("reactants", left), ("products", right))}
    data = {"forward": forward, "reverse": reverse, "reaction": totals["products"]-totals["reactants"], "unit": "kJ/mol", "quantity": ts["quantity"],
            "conditions": ts["conditions"], "methods": ts["methods"], **participants, "ts_species": ts["species_key"]}
    return outcome("ts-barrier-result/1", data, facts={"barrier.forward": {"value": forward, "unit": "kJ/mol"}, "barrier.reverse": {"value": reverse, "unit": "kJ/mol"}})


HANDLERS = {"thermochemistry.evaluate": evaluate, "barrier.evaluate": barrier}
