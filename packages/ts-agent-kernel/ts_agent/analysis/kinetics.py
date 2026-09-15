"""Concentration-form elementary TST and restricted initial branching."""

from __future__ import annotations

import math

from .engine import number, outcome
from .thermochemistry import R_KJ, standard_concentration


def tst(inputs, p):
    barrier = inputs.data("barrier", schema="ts-barrier-result/1")
    if barrier["quantity"] != "G" or barrier["unit"] != "kJ/mol":
        raise ValueError("TST requires an activation Gibbs free energy in kJ/mol")
    direction = p.get("direction", "forward")
    temperature = number(barrier["conditions"]["temperature_k"], "temperature", positive=True)
    standard = standard_concentration(barrier["conditions"]["standard_state"], temperature)
    kappa = number(p.get("kappa", 1.0), "transmission coefficient", positive=True)
    side = "reactants" if direction == "forward" else "products"
    participants = barrier[side]
    order = sum(item["coefficient"] for item in participants)
    activation = number(barrier[direction], "activation free energy")
    logk = math.log(kappa * 1.380649e-23 * temperature / 6.62607015e-34) + (1-order)*math.log(standard) - activation/(R_KJ*temperature)
    diagnostics = []
    rate_constant = math.exp(logk) if -745 <= logk <= 709 else None
    if rate_constant is None:
        diagnostics.append("Rate constant lies outside floating-point range; use the natural logarithm.")
    if activation < 0:
        diagnostics.append("Negative activation free energy: simple TST may need a variational/diffusion model.")
    concentrations = p.get("concentrations_molar")
    rate = None
    if concentrations is not None:
        if set(concentrations) != {r["species"] for r in participants}:
            raise ValueError("concentrations must cover exactly the reactant species")
        log_rate, zero = logk, False
        for item in participants:
            concentration = number(concentrations[item["species"]], "concentration")
            if concentration < 0:
                raise ValueError("concentrations cannot be negative")
            if concentration == 0:
                zero = True
            else:
                log_rate += item["coefficient"] * math.log(concentration)
        rate = 0.0 if zero else math.exp(log_rate) if -745 <= log_rate <= 709 else None
        if rate is None:
            diagnostics.append("Reaction rate lies outside floating-point range.")
    units = "s^-1" if order == 1 else f"(mol/L)^{1-order} s^-1"
    data = {"rate_constant": rate_constant, "log_rate_constant": logk, "rate_constant_unit": units, "reaction_order": order,
            "rate_molar_s": rate, "reactants": participants, "conditions": barrier["conditions"], "methods": barrier["methods"],
            "direction": direction, "kappa": kappa, "standard_concentration_molar": standard,
            "model": "elementary concentration-form transition-state theory", "concentrations_molar": concentrations}
    data["activation_gibbs_kj_mol"] = activation
    facts = {"kinetics.log_rate_constant": {"value": logk, "unit": f"ln({units})"}}
    if rate_constant is not None:
        facts["kinetics.rate_constant"] = {"value": rate_constant, "unit": units}
    return outcome("ts-kinetic-result/1", data, verdict="inconclusive" if diagnostics else "valid", diagnostics=diagnostics, facts=facts,
                   limitations=["Elementary TST with explicit kappa; no inferred tunnelling, recrossing, diffusion limit or network steady state."])


def branching(inputs, p):
    if not all(p["assumptions"].get(key) is True for key in ("shared_equilibrated_precursor", "irreversible_products", "no_product_interconversion")):
        return outcome("ts-branching-result/1", {"fractions": None}, verdict="unsupported", diagnostics=["Restricted branching assumptions are not satisfied; use a network kinetics model."])
    rates = [inputs.data("rates", i, schema="ts-kinetic-result/1") for i in range(len(inputs.bindings["rates"]))]
    first = rates[0]
    for record in rates:
        if record["activation_gibbs_kj_mol"] < 0:
            raise ValueError("branching requires rates within the elementary activated-TST regime")
        if any(record[key] != first[key] for key in ("conditions", "methods", "reactants", "reaction_order", "rate_constant_unit")):
            raise ValueError("branching requires the same precursor stoichiometry, conditions and rate convention")
    maximum = max(r["log_rate_constant"] for r in rates)
    weights = [math.exp(r["log_rate_constant"] - maximum) for r in rates]
    total = sum(weights)
    return outcome("ts-branching-result/1", {"fractions": [w/total for w in weights], "rate_artifact_ids": [r["artifact_id"] for r in inputs.bindings["rates"]],
                   "assumptions": p["assumptions"], "scope": "initial branching for the supplied irreversible competitors"},
                   limitations=["Fractions are not general product yields for cycles, reversible networks, depletion or time-dependent kinetics."])


HANDLERS = {"kinetics.tst": tst, "kinetics.branching": branching}
