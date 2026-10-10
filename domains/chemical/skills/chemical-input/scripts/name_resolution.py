"""Bounded chemical-name resolution and candidate structure validation."""

from __future__ import annotations

import json
import hashlib
import os
import stat
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESOLVER_CONFIG_ENV = "RESEARCH_AGENT_NAME_RESOLVER_CONFIG"
RESOLVER_VERSION = "1"
DEFAULT_PUBCHEM_ENDPOINT = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
DEFAULT_OPSIN_ENDPOINT = "https://opsin.ch.cam.ac.uk/opsin"
MAX_CANDIDATES = 16


class ResolverConfigurationError(ValueError):
    """Raised when an installation-owned resolver configuration is invalid."""


def _config_path() -> Path | None:
    configured = os.environ.get(RESOLVER_CONFIG_ENV, "").strip()
    if not configured:
        install_root = os.environ.get("RESEARCH_AGENT_INSTALL_ROOT", "").strip()
        if install_root:
            configured = str(Path(install_root) / "etc" / "name-resolver.toml")
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        raise ResolverConfigurationError(f"{RESOLVER_CONFIG_ENV} must be an absolute path")
    if path.is_symlink() or not path.is_file() or not os.access(path, os.R_OK):
        raise ResolverConfigurationError(f"{RESOLVER_CONFIG_ENV} is not a readable regular file: {path}")
    return path.resolve(strict=True)


def _load_config() -> tuple[Path | None, dict[str, Any]]:
    path = _config_path()
    if path is None:
        return None, {}
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ResolverConfigurationError(f"cannot read resolver configuration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ResolverConfigurationError("resolver configuration must be a TOML table")
    default = raw.get("default_resolver", "auto")
    if not isinstance(default, str) or default not in {"auto", "pubchem", "opsin"}:
        raise ResolverConfigurationError("default_resolver must be auto, pubchem, or opsin")
    backends = raw.get("backends", {})
    if not isinstance(backends, dict):
        raise ResolverConfigurationError("backends must be a TOML table")
    normalized: dict[str, Any] = {"default_resolver": default, "backends": {}}
    for name, value in backends.items():
        if name not in {"pubchem", "opsin"} or not isinstance(value, dict):
            raise ResolverConfigurationError(f"unsupported resolver backend: {name}")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ResolverConfigurationError(f"backends.{name}.enabled must be boolean")
        endpoint = value.get("endpoint", DEFAULT_PUBCHEM_ENDPOINT if name == "pubchem" else DEFAULT_OPSIN_ENDPOINT)
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ResolverConfigurationError(f"backends.{name}.endpoint must be a URL")
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ResolverConfigurationError(f"backends.{name}.endpoint must be an absolute HTTP(S) URL")
        timeout = value.get("timeout_seconds", 10)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 60:
            raise ResolverConfigurationError(f"backends.{name}.timeout_seconds must be between 1 and 60")
        cache = value.get("cache", True)
        if not isinstance(cache, bool):
            raise ResolverConfigurationError(f"backends.{name}.cache must be boolean")
        cache_dir = value.get("cache_dir")
        if cache_dir is not None and (not isinstance(cache_dir, str) or not Path(cache_dir).is_absolute()):
            raise ResolverConfigurationError(f"backends.{name}.cache_dir must be an absolute path")
        user_agent = value.get("user_agent", "ResearchAgent-chemical-name-resolver/1")
        if not isinstance(user_agent, str) or not user_agent.strip() or len(user_agent) > 256:
            raise ResolverConfigurationError(f"backends.{name}.user_agent must be a non-empty string")
        normalized["backends"][name] = {
            "enabled": enabled,
            "endpoint": endpoint.rstrip("/"),
            "timeout_seconds": float(timeout),
            "cache": cache,
            "cache_dir": cache_dir,
            "user_agent": user_agent,
        }
    return path, normalized


def _cache_directory(config_path: Path, backend: str, settings: dict[str, Any]) -> Path:
    configured = settings.get("cache_dir")
    return Path(configured) if configured else config_path.parent / "name-resolver-cache" / backend


def _cache_key(backend: str, name: str, endpoint: str) -> str:
    return hashlib.sha256(f"{backend}\n{endpoint}\n{name}".encode("utf-8")).hexdigest()


def _read_cache(config_path: Path, backend: str, settings: dict[str, Any], key: str) -> dict[str, Any] | None:
    if not settings["cache"]:
        return None
    path = _cache_directory(config_path, backend, settings) / f"{key}.json"
    if path.is_symlink() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("candidates"), list):
        return None
    if not isinstance(value.get("evidence"), dict) or not isinstance(value.get("diagnostics"), list):
        return None
    return value


def _write_cache(config_path: Path, backend: str, settings: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    if not settings["cache"]:
        return
    directory = _cache_directory(config_path, backend, settings)
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        path = directory / f"{key}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        # A read-only cache must not turn an otherwise usable resolver into a failure.
        return


def _http_json(url: str, *, timeout: float, user_agent: str) -> tuple[Any, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    return json.loads(payload.decode("utf-8")), "sha256:" + hashlib.sha256(payload).hexdigest()


def _http_failure_diagnostic(backend: str, error: urllib.error.HTTPError) -> str:
    """Keep backend status visible instead of collapsing it to ``HTTPError``."""

    code = getattr(error, "code", None)
    if code == 404:
        return f"{backend} returned HTTP 404: the submitted name is not recognized by this backend"
    if code == 429:
        return f"{backend} returned HTTP 429: the resolver backend rate-limited the request"
    return f"{backend} returned HTTP {code}: deterministic lookup failed"


def _pubchem_candidates(name: str, config_path: Path, settings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    endpoint = settings["endpoint"]
    key = _cache_key("pubchem", name, endpoint)
    cached = _read_cache(config_path, "pubchem", settings, key)
    if cached is not None:
        return cached.get("candidates", []), cached.get("evidence", {}), cached.get("diagnostics", [])
    encoded = urllib.parse.quote(name, safe="")
    base = f"{endpoint}/compound/name/{encoded}"
    diagnostics: list[str] = []
    evidence: dict[str, Any] = {
        "implementation": "PubChem PUG REST",
        "version": RESOLVER_VERSION,
        "endpoint": endpoint,
        "requests": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    cids_url = f"{base}/cids/JSON"
    try:
        cids_payload, cids_digest = _http_json(cids_url, timeout=settings["timeout_seconds"], user_agent=settings["user_agent"])
        evidence["requests"].append({"url": cids_url, "response_sha256": cids_digest})
        cids = cids_payload.get("IdentifierList", {}).get("CID", [])
        if not isinstance(cids, list) or not cids:
            diagnostics.append("PubChem returned no compound CID for this name")
            _write_cache(
                config_path,
                "pubchem",
                settings,
                key,
                {"candidates": [], "evidence": evidence, "diagnostics": diagnostics},
            )
            return [], evidence, diagnostics
        cids = [int(cid) for cid in cids[:MAX_CANDIDATES]]
        if len(cids) > 1:
            diagnostics.append(f"PubChem returned {len(cids)} compound candidates")
        joined = ",".join(str(cid) for cid in cids)
        properties_url = f"{endpoint}/compound/cid/{joined}/property/CanonicalSMILES,IsomericSMILES,InChI,InChIKey,IUPACName/JSON"
        properties_payload, properties_digest = _http_json(
            properties_url, timeout=settings["timeout_seconds"], user_agent=settings["user_agent"]
        )
        evidence["requests"].append({"url": properties_url, "response_sha256": properties_digest})
        rows = properties_payload.get("PropertyTable", {}).get("Properties", [])
        candidates = []
        for row in rows if isinstance(rows, list) else []:
            smiles = row.get("IsomericSMILES") or row.get("SMILES") or row.get("CanonicalSMILES") or row.get("ConnectivitySMILES")
            if not smiles:
                continue
            candidates.append({"smiles": str(smiles), "source": "pubchem", "resolver_metadata": {
                "cid": row.get("CID"), "iupac_name": row.get("IUPACName"), "inchi": row.get("InChI"), "inchikey": row.get("InChIKey")
            }})
        cached_value = {"candidates": candidates, "evidence": evidence, "diagnostics": diagnostics}
        _write_cache(config_path, "pubchem", settings, key, cached_value)
        return candidates, evidence, diagnostics
    except urllib.error.HTTPError as exc:
        diagnostics.append(_http_failure_diagnostic("PubChem", exc))
        # A 404 is a deterministic "not indexed" answer. Cache it so an
        # agent retry cannot repeatedly spend network/API budget on the same
        # name. Transient statuses remain uncached and may be retried.
        if exc.code == 404:
            _write_cache(
                config_path,
                "pubchem",
                settings,
                key,
                {"candidates": [], "evidence": evidence, "diagnostics": diagnostics},
            )
        return [], evidence, diagnostics
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, TypeError, KeyError, AttributeError) as exc:
        diagnostics.append(f"PubChem lookup failed: {exc.__class__.__name__}")
        return [], evidence, diagnostics


def _opsin_candidates(name: str, config_path: Path, settings: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    endpoint = settings["endpoint"]
    key = _cache_key("opsin", name, endpoint)
    cached = _read_cache(config_path, "opsin", settings, key)
    if cached is not None:
        return cached["candidates"], cached["evidence"], cached["diagnostics"]
    url = f"{endpoint}/{urllib.parse.quote(name, safe='')}.json"
    evidence: dict[str, Any] = {
        "implementation": "OPSIN HTTP API",
        "version": RESOLVER_VERSION,
        "endpoint": endpoint,
        "requests": [],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    diagnostics: list[str] = []
    try:
        payload, response_digest = _http_json(url, timeout=settings["timeout_seconds"], user_agent=settings["user_agent"])
        evidence["requests"].append({"url": url, "response_sha256": response_digest})
        smiles = payload.get("smiles") if isinstance(payload, dict) else None
        candidates = []
        if smiles:
            candidates.append({"smiles": str(smiles), "source": "opsin", "resolver_metadata": {
                "iupac_name": payload.get("name"), "inchi": payload.get("stdinchi"), "inchikey": payload.get("stdinchikey")
            }})
        else:
            diagnostics.append("OPSIN returned no SMILES for this name")
        cached_value = {"candidates": candidates, "evidence": evidence, "diagnostics": diagnostics}
        _write_cache(config_path, "opsin", settings, key, cached_value)
        return candidates, evidence, diagnostics
    except urllib.error.HTTPError as exc:
        diagnostics.append(_http_failure_diagnostic("OPSIN", exc))
        if exc.code == 404:
            _write_cache(
                config_path,
                "opsin",
                settings,
                key,
                {"candidates": [], "evidence": evidence, "diagnostics": diagnostics},
            )
        return [], evidence, diagnostics
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, TypeError, KeyError, AttributeError) as exc:
        diagnostics.append(f"OPSIN lookup failed: {exc.__class__.__name__}")
        return [], evidence, diagnostics


def _configured_candidates(name: str, requested: str) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[str]]:
    config_path, config = _load_config()
    if config_path is None:
        return requested, [], {}, ["No name resolver configuration is available; infer candidates from the input description"]
    if requested != "auto":
        resolvers = [requested]
    else:
        configured_default = config["default_resolver"]
        resolvers = []
        if configured_default != "auto":
            resolvers.append(configured_default)
        # Auto lookup is a deterministic backend chain. The manifest decides
        # which backends are enabled; no backend is inferred from an LLM.
        resolvers.extend(name for name in ("pubchem", "opsin") if name not in resolvers)

    attempts: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for resolver in resolvers:
        settings = config["backends"].get(resolver)
        if not settings or not settings["enabled"]:
            if requested != "auto":
                return resolver, [], {}, [f"No enabled deterministic resolver backend is configured for {resolver}"]
            continue
        if resolver == "pubchem":
            candidates, evidence, backend_diagnostics = _pubchem_candidates(name, config_path, settings)
        elif resolver == "opsin":
            candidates, evidence, backend_diagnostics = _opsin_candidates(name, config_path, settings)
        else:
            backend_diagnostics = [f"Configured resolver backend {resolver} is not implemented"]
            candidates, evidence = [], {}
        checked, checks = _check_candidates(candidates)
        backend_diagnostics = [*backend_diagnostics, *[
            f"{resolver}: {message}" for check in checks for message in check['diagnostics']]]
        diagnostics.extend(backend_diagnostics)
        attempts.append({"resolver": resolver, "evidence": evidence, "diagnostics": backend_diagnostics,
                         "candidate_checks": checks})
        if checked:
            provenance = {**evidence, "candidate_checks": checks} if len(attempts) == 1 else {"attempts": attempts}
            return resolver, checked, provenance, diagnostics

    if not attempts:
        resolver = requested if requested != "auto" else config["default_resolver"]
        return resolver, [], {}, diagnostics or [
            "No enabled deterministic resolver backend is configured for automatic lookup"
        ]
    if len(attempts) == 1:
        return attempts[0]["resolver"], [], {**attempts[0]["evidence"],
            "candidate_checks": attempts[0]["candidate_checks"]}, diagnostics
    return "auto", [], {"attempts": attempts}, diagnostics


def _inchi_fields(molecule) -> dict[str, str]:
    try:
        from rdkit import Chem

        inchi = Chem.MolToInchi(molecule)
        if not inchi:
            return {}
        return {"inchi": inchi, "inchikey": Chem.InchiToInchiKey(inchi)}
    except (AttributeError, RuntimeError, ValueError):
        return {}


def _candidate(candidate: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, str | None]:
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    prefix = f"candidate_{index}: "
    if not isinstance(candidate, dict):
        return None, prefix + "candidate must be an object"
    smiles, source = candidate.get("smiles"), candidate.get("source")
    if not isinstance(smiles, str) or not smiles.strip():
        return None, prefix + "provide a non-empty SMILES"
    if not isinstance(source, str) or source not in {"pubchem", "opsin", "llm", "user"}:
        return None, prefix + "source must be pubchem, opsin, llm or user"
    if "reason" in candidate and not isinstance(candidate["reason"], str):
        return None, prefix + "reason must be text"
    if "assumptions" in candidate and (not isinstance(candidate["assumptions"], list)
            or any(not isinstance(item, str) for item in candidate["assumptions"])):
        return None, prefix + "assumptions must be a list of strings"
    molecule = Chem.MolFromSmiles(smiles.strip())
    if molecule is None or molecule.GetNumAtoms() == 0:
        return None, prefix + "RDKit could not parse the SMILES; revise the structure"
    if len(Chem.GetMolFrags(molecule)) != 1:
        return None, prefix + "prepare disconnected species separately"
    charge = int(Chem.GetFormalCharge(molecule))
    if "charge" in candidate and (type(candidate["charge"]) is not int or candidate["charge"] != charge):
        return None, prefix + "declared charge differs from the SMILES; revise charge or structure"
    if "multiplicity" in candidate:
        multiplicity = candidate["multiplicity"]
        full = Chem.AddHs(molecule)
        electrons = sum(atom.GetAtomicNum() for atom in full.GetAtoms()) - charge
        if (type(multiplicity) is not int or multiplicity < 1 or multiplicity - 1 > electrons
                or (electrons - (multiplicity - 1)) % 2):
            return None, prefix + "multiplicity is incompatible with electron count; revise multiplicity or structure"

    centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True, useLegacyImplementation=False)
    stereo = [str(item.type) + ":" + str(item.centeredOn) for item in Chem.FindPotentialStereo(molecule)
              if item.specified == Chem.StereoSpecified.Unspecified]
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    result = {
        "candidate_id": f"candidate_{index}", "source": source, "smiles": smiles.strip(),
        "canonical_smiles": canonical, "isomeric_smiles": canonical,
        "formula": rdMolDescriptors.CalcMolFormula(molecule), "charge": charge,
        "atom_count": int(molecule.GetNumAtoms()), "graph_valid": True,
        "undefined_stereocenters": [int(atom) for atom, assignment in centers if assignment == "?"],
        "unspecified_stereo": stereo,
    }
    for field in ("reason", "assumptions", "multiplicity"):
        if field in candidate:
            result[field] = candidate[field]
    metadata = candidate.get("resolver_metadata")
    if isinstance(metadata, dict):
        result["resolver_metadata"] = metadata
    result.update(_inchi_fields(molecule))
    return result, None


def _check_candidates(supplied):
    candidates, checks = [], []
    for index, proposed in enumerate(supplied, 1):
        candidate, diagnostic = _candidate(proposed, index)
        checks.append({"candidate_id": f"candidate_{index}", "status": "failed" if diagnostic else "passed",
                       "diagnostics": [diagnostic] if diagnostic else []})
        if candidate:
            candidates.append(candidate)
    return candidates, checks


def resolve(_inputs, parameters: dict[str, Any]) -> dict[str, Any]:
    name = parameters.get("name")
    lookup_name = parameters.get("lookup_name", name)
    if not isinstance(name, str) or not name.strip() or not isinstance(lookup_name, str) or not lookup_name.strip():
        raise ValueError("name and lookup_name must be non-empty strings")
    name, lookup_name = name.strip(), lookup_name.strip()
    resolver = parameters.get("resolver", "auto")
    if not isinstance(resolver, str) or resolver not in {"auto", "pubchem", "opsin"}:
        raise ValueError("resolver must be auto, pubchem or opsin")
    supplied = parameters.get("candidates")
    diagnostics, checks = [], []
    if supplied is None:
        try:
            resolver, candidates, evidence, diagnostics = _configured_candidates(lookup_name, resolver)
        except ResolverConfigurationError as exc:
            candidates, evidence = [], {}
            diagnostics.append(str(exc))
        checks = [{"candidate_id": item["candidate_id"], "status": "passed", "diagnostics": []} for item in candidates]
    else:
        if not isinstance(supplied, list) or not 1 <= len(supplied) <= MAX_CANDIDATES:
            raise ValueError(f"candidates must contain between 1 and {MAX_CANDIDATES} structures")
        candidates, checks = _check_candidates(supplied)
        diagnostics = [message for check in checks for message in check["diagnostics"]]
        evidence = {}
        sources = {item["source"] for item in candidates}
        resolver = next(iter(sources)) if len(sources) == 1 else "supplied"

    if not candidates:
        status = "unresolved"
        verdict = "inconclusive" if supplied is None else "invalid"
        next_step = "infer_candidates" if supplied is None else "revise_candidates"
    elif len(candidates) != 1 or any(item["unspecified_stereo"] for item in candidates):
        status, verdict, next_step = "ambiguous", "inconclusive", "select_or_enumerate"
    else:
        status, verdict, next_step = "resolved", "valid", "prepare_geometry"

    return {"schema_version": "chemical-input/1", "data": {
        "name": name, "lookup_name": lookup_name, "resolver": resolver, "status": status,
        "candidates": candidates, "resolver_provenance": evidence, "next_step": next_step,
    }, "verdict": verdict, "checks": checks, "diagnostics": diagnostics, "limitations": []}


def resolve_candidates_file(path: Path) -> dict[str, Any]:
    """Inspect Agent/user proposals locally; the Job input pins the original file."""
    with path.open('rb') as stream:
        raw = stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("candidate file must be at most 1 MiB")
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) - {"name", "lookup_name", "candidates", "lookup_ref"}:
        raise ValueError("candidate file requires name and candidates; optional fields are lookup_name and lookup_ref")
    proposals = document.get('candidates')
    if not isinstance(proposals, list) or not proposals:
        raise ValueError("candidate file requires a non-empty candidates list")
    if any(not isinstance(item, dict) or not isinstance(item.get('source'), str)
           or item['source'] not in {'llm', 'user'} for item in proposals):
        raise ValueError("candidate file sources must be llm or user; service results come from lookup")
    if 'lookup_ref' in document and (not isinstance(document['lookup_ref'], str) or not document['lookup_ref'].strip()):
        raise ValueError("lookup_ref must be a non-empty reference to the earlier lookup")
    result = resolve({}, document)
    result['data']['input_provenance'] = {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(),
        **({'lookup_ref': document['lookup_ref']} if 'lookup_ref' in document else {})}
    return result
