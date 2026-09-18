"""On-demand, closed schemas for independently selectable scientific operations."""

from __future__ import annotations


def obj(properties=None, required=(), **keywords):
    return {"type": "object", "properties": properties or {}, "required": list(required), "additionalProperties": False, **keywords}


def array(items, maximum=64, minimum=1):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def integer(minimum=0, maximum=4095):
    return {"type": "integer", "minimum": minimum, "maximum": maximum}


def real(minimum=None, maximum=None):
    return {"type": "number", **({"minimum": minimum} if minimum is not None else {}), **({"maximum": maximum} if maximum is not None else {})}


def choice(*values):
    return {"enum": list(values)}


TEXT = {"type": "string", "minLength": 1, "maxLength": 256}
KEY = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"}
BOOL = {"type": "boolean"}
POSITIVE = {"type": "number", "exclusiveMinimum": 0, "maximum": 1e12}
ARTIFACT = {"type": "string", "pattern": "^art_[0-9a-f]{24}$"}
ATOM = obj({"species": integer(0, 63), "atom": integer()}, ["species", "atom"])
MAPPING = array(obj({"reactant": ATOM, "product": ATOM}, ["reactant", "product"]), 4096)
STOICH = array(obj({"species": KEY, "coefficient": integer(1, 64)}, ["species", "coefficient"]))
STATE = obj({"charge": integer(-32, 32), "multiplicity": integer(1, 21)}, ["charge", "multiplicity"])
STANDARD = obj({"kind": choice("pressure", "concentration"), "value": POSITIVE, "unit": choice("mol/L", "bar", "atm", "Pa")}, ["kind", "value", "unit"])
CONDITIONS = obj({"temperature_k": {"type": "number", "exclusiveMinimum": 0, "maximum": 10000}, "phase": choice("gas", "solution"),
                  "solvent": TEXT, "source_standard_state": STANDARD, "standard_state": STANDARD},
                 ["temperature_k", "phase", "source_standard_state", "standard_state"])
SPECIES = obj({"key": KEY, "smiles": {"type": "string", "minLength": 1, "maxLength": 4096},
               "multiplicity": integer(1, 21), "role": choice("participant", "catalyst", "solvent", "spectator")}, ["key", "smiles", "multiplicity"])
TRANSFORM = obj({"translation": array(real(-1e6, 1e6), 3, 3), "rotation": array(array(real(-1, 1), 3, 3), 3, 3)}, ["translation"])
MAP_PARAMETERS = {"mapping": MAPPING, "candidate_index": integer(0, 31)}
SECTION = {"section_index": integer(0, 255)}
PATH_ROW = obj({"step": KEY, "direction": choice("forward", "reverse")}, ["step"])


def descriptor(name, summary, roles, parameters, *, optional=(), multiple=(), limitations=()):
    return {
        "capability": name, "version": "1", "capability_kind": "analysis", "summary": summary,
        "input_roles": list(roles), "output_roles": ["analysis_artifact", "output_artifacts", "finding_candidates"],
        "effects": ["local_prepare", "local_analysis"],
        "input_schema": obj({role: array(ARTIFACT, 64 if role in multiple else 1) for role in roles}, [r for r in roles if r not in optional]),
        "parameter_schema": parameters, "parsers": [name + "/1"],
        "limits": {"input_bytes": 67108864, "input_file_bytes": 33554432, "analysis_artifact_bytes": 4194304},
        "scientific_scope": summary,
        "limitations": ["Deterministic evidence only; no automatic successor operation or Claim acceptance.", *limitations],
    }


DESCRIPTORS = (
    descriptor("reaction.parse", "Parse explicit molecular reaction identities, stoichiometry and electronic states.", [],
        obj({"reaction_smiles": {"type": "string", "minLength": 3, "maxLength": 8192},
             "multiplicities": obj({s: array(integer(1, 21)) for s in ("reactants", "products")}, ["reactants", "products"]),
             "species": array(SPECIES), "reactants": STOICH, "products": STOICH,
             "conditions": CONDITIONS, "boundary": choice("closed", "open")},
            oneOf=[{"required": ["reaction_smiles", "multiplicities"], "not": {"anyOf": [{"required": [k]} for k in ("species", "reactants", "products")]}},
                   {"required": ["species", "reactants", "products"], "not": {"anyOf": [{"required": [k]} for k in ("reaction_smiles", "multiplicities")]}}]),
        limitations=["Open reservoirs are unsupported. Each species must be a connected component; spin is explicitly declared."]),
    descriptor("reaction.validate", "Check closed-reaction element, isotope and charge conservation.", ["reaction"], obj()),
    descriptor("reaction.mapping.generate", "Propose bounded graph-edit atom mappings; preserve symmetry ambiguity.", ["reaction"],
        obj({"max_candidates": integer(1, 32), "max_states": integer(1, 100000)}), limitations=["At most 256 atoms per side; a proposal is not a mechanistic conclusion."]),
    descriptor("reaction.bond_changes", "Extract bond changes for an explicitly selected complete mapping.", ["reaction", "mapping"], obj(MAP_PARAMETERS), optional=["mapping"]),
    descriptor("structure.reindex", "Write paired XYZ endpoints using an explicit atom bijection.", ["reactants", "products", "mapping"], obj(MAP_PARAMETERS), optional=["mapping"], multiple=["reactants", "products"]),
    descriptor("structure.assemble_fragments", "Apply explicit fragment transforms and report interfragment clashes.", ["fragments"],
        obj({"placements": array(TRANSFORM), "placement_candidates": array(array(TRANSFORM), 32), "minimum_distance_angstrom": POSITIVE},
            oneOf=[{"required": ["placements"], "not": {"required": ["placement_candidates"]}}, {"required": ["placement_candidates"], "not": {"required": ["placements"]}}]), multiple=["fragments"]),
    descriptor("species.identity", "Compare declared molecular graph, isotope, stereo, charge and spin identity.", ["reference", "target"], obj()),
    descriptor("gaussian.output.analyze", "Summarize a selected Gaussian job section, stationary point and normal modes.", ["log"], obj({**SECTION, "expected_route": TEXT})),
    descriptor("gaussian.input.build", "Construct structured Gaussian inputs for independently chosen tasks.", ["structures"],
        obj({"task": choice("sp", "opt", "ts", "freq", "opt_freq", "irc", "qst2", "qst3"), **STATE["properties"],
             "method": TEXT, "basis": TEXT, "direction": choice("forward", "reverse"), "max_cycles": integer(1, 1000),
             "max_points": integer(1, 1000), "step_size": integer(1, 100), "nproc": integer(1, 1024), "memory_mb": integer(64, 1048576),
             "solvent": TEXT, "solvent_model": choice("SMD", "PCM", "CPCM")}, ["task", "charge", "multiplicity", "method", "basis"],
            allOf=[{"if": {"properties": {"task": {"const": "irc"}}}, "then": {"required": ["direction"]}}]), multiple=["structures"]),
    descriptor("path.extract_candidate", "Select an explicit path frame or maximum of supplied image energies.", ["trajectory"],
        obj({"selection": choice("index", "highest_energy"), "index": integer(0, 511), "energies": array(real(), 512), "energy_unit": choice("hartree", "eV", "kJ/mol", "kcal/mol")}, ["selection"],
            allOf=[{"if": {"properties": {"selection": {"const": "index"}}}, "then": {"required": ["index"]}, "else": {"required": ["energies", "energy_unit"]}}])),
    descriptor("vibration.analyze_mode", "Compare selected normal-mode bond derivatives with an explicit reaction coordinate.", ["evidence"],
        obj({"mode_index": integer(0, 12287), "minimum_overlap": real(0, 1),
             "bonds": array(obj({"atoms": array(integer(), 2, 2), "sign": choice(-1, 1)}, ["atoms", "sign"]), 256)}, ["mode_index", "bonds"])),
    descriptor("path.endpoint_summary", "Extract a finite Gaussian IRC endpoint and completion evidence.", ["log"], obj(SECTION)),
    descriptor("mechanism.step.audit", "Audit selected TS, mode and bidirectional endpoint evidence; report gaps.",
        ["stationary", "mode", "forward", "reverse", "forward_match", "reverse_match"], obj({"step_key": KEY, "origin_tolerance_angstrom": real(0, 0.1),
            "forward_species_artifact_id": ARTIFACT, "reverse_species_artifact_id": ARTIFACT}, ["step_key"]),
        optional=["mode", "forward", "reverse", "forward_match", "reverse_match"]),
    descriptor("thermochemistry.evaluate", "Compute explicit E, E+ZPE, H or G with bound methods and standard states.", ["electronic", "thermal"],
        obj({"species_key": KEY, "quantity": choice("E", "E_ZPE", "H", "G"), "conditions": CONDITIONS,
             "methods": obj({"electronic": TEXT, "thermal": TEXT, "composite": BOOL}, ["electronic"]), "electronic_state": STATE,
             "stationary_kind": choice("minimum", "transition_state"), "electronic_section": integer(0, 255), "thermal_section": integer(0, 255),
             "geometry_tolerance_angstrom": real(0, 1), "model": obj({"kind": choice("parsed", "rrho"), "frequency_scale": {"type": "number", "exclusiveMinimum": 0, "maximum": 2},
                "geometry": choice("monatomic", "linear", "nonlinear"), "symmetry_number": integer(1, 1000)}, ["kind"],
                allOf=[{"if": {"properties": {"kind": {"const": "rrho"}}}, "then": {"required": ["geometry", "symmetry_number"]}}])},
            ["species_key", "quantity", "conditions", "methods", "electronic_state", "stationary_kind"]), optional=["thermal"]),
    descriptor("barrier.evaluate", "Calculate stoichiometric forward/reverse barriers and reaction energy on compatible references.", ["reactants", "products", "transition_state"],
        obj({"reactant_coefficients": array(integer(1, 64)), "product_coefficients": array(integer(1, 64))}), multiple=["reactants", "products"]),
    descriptor("kinetics.tst", "Calculate elementary concentration-form TST constants and optional reaction rates.", ["barrier"],
        obj({"direction": choice("forward", "reverse"), "kappa": POSITIVE,
             "concentrations_molar": {"type": "object", "propertyNames": KEY, "additionalProperties": real(0, 1e6), "maxProperties": 64}})),
    descriptor("kinetics.branching", "Compare initial irreversible branches from the same equilibrated precursor.", ["rates"],
        obj({"assumptions": obj({k: BOOL for k in ("shared_equilibrated_precursor", "irreversible_products", "no_product_interconversion")},
            ["shared_equilibrated_precursor", "irreversible_products", "no_product_interconversion"])}, ["assumptions"]), multiple=["rates"]),
    descriptor("mechanism.step.define", "Record an explicit balanced elementary-step hypothesis and selected evidence.", ["reaction", "audit", "barrier", "rate"],
        obj({"step_key": KEY, "reversible": BOOL}, ["step_key", "reversible"]), optional=["audit", "barrier", "rate"]),
    descriptor("mechanism.network.assemble", "Assemble explicit stoichiometric reaction hyperedges, preserving cycles and parallel steps.", ["steps"],
        obj({"scope": {"type": "string", "minLength": 1, "maxLength": 2048},
             "species_aliases": {"type": "object", "propertyNames": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}/[A-Za-z][A-Za-z0-9_-]{0,63}$"}, "additionalProperties": KEY, "maxProperties": 4096},
             "initial_species": array(KEY), "target_species": array(KEY), "max_paths": integer(1, 64), "max_depth": integer(1, 32)}, ["scope"],
            dependentRequired={"initial_species": ["target_species"], "target_species": ["initial_species"]}), multiple=["steps"]),
    descriptor("mechanism.network.audit", "Check a network's identities, balance, cycles and missing step evidence.", ["network"], obj()),
    descriptor("mechanism.energy_profile", "Construct a selected Gibbs energy profile with a conserved explicit initial pool.", ["network"],
        obj({"path": array(PATH_ROW), "initial_composition": {"type": "object", "propertyNames": KEY, "additionalProperties": integer(1, 4096), "minProperties": 1, "maxProperties": 4096}}, ["path", "initial_composition"])),
)
