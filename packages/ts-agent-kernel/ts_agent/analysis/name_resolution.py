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

from .engine import outcome


RESOLVER_CONFIG_ENV = "TSPI_NAME_RESOLVER_CONFIG"
RESOLVER_VERSION = "1"
DEFAULT_PUBCHEM_ENDPOINT = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
DEFAULT_OPSIN_ENDPOINT = "https://opsin.ch.cam.ac.uk/opsin"
MAX_CANDIDATES = 16


class ResolverConfigurationError(ValueError):
    """Raised when an installation-owned resolver configuration is invalid."""


def _config_path() -> Path | None:
    configured = os.environ.get(RESOLVER_CONFIG_ENV, "").strip()
    if not configured:
        install_root = os.environ.get("TSPI_INSTALL_ROOT", "").strip()
        if install_root:
            configured = str(Path(install_root) / ".pi" / "name-resolver.toml")
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
    if default not in {"auto", "pubchem", "opsin"}:
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
        user_agent = value.get("user_agent", "TSPi-chemical-name-resolver/1")
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
            smiles = row.get("SMILES") or row.get("ConnectivitySMILES") or row.get("CanonicalSMILES") or row.get("IsomericSMILES")
            if not smiles:
                continue
            candidates.append({"smiles": str(smiles), "source": "pubchem", "resolver_metadata": {
                "cid": row.get("CID"), "iupac_name": row.get("IUPACName"), "inchi": row.get("InChI"), "inchikey": row.get("InChIKey")
            }})
        cached_value = {"candidates": candidates, "evidence": evidence, "diagnostics": diagnostics}
        _write_cache(config_path, "pubchem", settings, key, cached_value)
        return candidates, evidence, diagnostics
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
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, TypeError, KeyError, AttributeError) as exc:
        diagnostics.append(f"OPSIN lookup failed: {exc.__class__.__name__}")
        return [], evidence, diagnostics


def _configured_candidates(name: str, requested: str) -> tuple[str, list[dict[str, Any]], dict[str, Any], list[str]]:
    config_path, config = _load_config()
    if config_path is None:
        return requested, [], {}, []
    resolver = requested if requested != "auto" else config["default_resolver"]
    if resolver == "auto":
        resolver = "pubchem"
    settings = config["backends"].get(resolver)
    if not settings or not settings["enabled"]:
        return resolver, [], {}, [f"No enabled deterministic resolver backend is configured for {resolver}"]
    if resolver == "pubchem":
        candidates, evidence, diagnostics = _pubchem_candidates(name, config_path, settings)
        return resolver, candidates, evidence, diagnostics
    if resolver == "opsin":
        candidates, evidence, diagnostics = _opsin_candidates(name, config_path, settings)
        return resolver, candidates, evidence, diagnostics
    return resolver, [], {}, [f"Configured resolver backend {resolver} is not implemented"]


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

    smiles = candidate["smiles"].strip()
    source = candidate["source"]
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None or molecule.GetNumAtoms() == 0:
        return None, f"candidate_{index}: RDKit could not parse the supplied SMILES"
    if len(Chem.GetMolFrags(molecule)) != 1:
        return None, f"candidate_{index}: structure must be one connected molecule"

    centers = Chem.FindMolChiralCenters(molecule, includeUnassigned=True, useLegacyImplementation=False)
    unassigned = [int(atom) for atom, assignment in centers if assignment == "?"]
    canonical = Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True)
    result = {
        "candidate_id": f"candidate_{index}",
        "source": source,
        "smiles": smiles,
        "canonical_smiles": canonical,
        "isomeric_smiles": canonical,
        "formula": rdMolDescriptors.CalcMolFormula(molecule),
        "charge": int(Chem.GetFormalCharge(molecule)),
        "atom_count": int(molecule.GetNumAtoms()),
        "undefined_stereocenters": unassigned,
    }
    metadata = candidate.get("resolver_metadata")
    if isinstance(metadata, dict):
        result["resolver_metadata"] = metadata
    result.update(_inchi_fields(molecule))
    return result, None


def resolve(_inputs, parameters: dict[str, Any]) -> dict[str, Any]:
    name = parameters["name"].strip()
    resolver = parameters.get("resolver", "auto")
    supplied = parameters.get("candidates", [])
    diagnostics: list[str] = []
    candidates: list[dict[str, Any]] = []

    if not supplied:
        try:
            resolver, supplied, evidence, lookup_diagnostics = _configured_candidates(name, resolver)
            diagnostics.extend(lookup_diagnostics)
        except ResolverConfigurationError as exc:
            evidence = {}
            diagnostics.append(str(exc))
            supplied = []
        if not supplied:
            return outcome(
                "ts-name-resolution/1",
                {"name": name, "resolver": resolver, "status": "unresolved", "candidates": [],
                 "resolver_provenance": evidence},
                verdict="unsupported",
                diagnostics=diagnostics or [
                    "No registered deterministic name resolver is configured; install or bind OPSIN/PubChem before resolving a name."
                ],
                limitations=[
                    "An LLM cannot be treated as a name-resolution authority without an explicit candidate and confirmation."
                ],
                facts={"chemical.name.status": {"value": "unresolved"}, "chemical.name.candidate_count": {"value": 0}},
            )
    else:
        evidence = {}

    for index, proposed in enumerate(supplied, 1):
        item, diagnostic = _candidate(proposed, index)
        if diagnostic:
            diagnostics.append(diagnostic)
        elif item:
            candidates.append(item)

    if not candidates:
        status = "unresolved"
        verdict = "invalid"
    elif any(item["source"] == "llm" for item in candidates):
        status = "draft"
        verdict = "inconclusive"
    elif len(candidates) != 1 or any(item["undefined_stereocenters"] for item in candidates):
        status = "ambiguous"
        verdict = "inconclusive"
    elif candidates[0]["source"] == "user":
        status = "confirmed"
        verdict = "valid"
    else:
        status = "resolved"
        verdict = "valid"

    data = {
        "name": name,
        "resolver": resolver,
        "status": status,
        "candidates": candidates,
        "resolver_provenance": evidence,
    }
    files = {
        "name_resolution.json": json.dumps(
            {"schema_version": "ts-name-resolution/1", "data": data},
            sort_keys=True,
        ) + "\n"
    }
    return outcome(
        "ts-name-resolution/1",
        data,
        verdict=verdict,
        diagnostics=diagnostics,
        limitations=[
            "Name resolution establishes a molecular graph candidate, not a validated reaction product or optimized 3D structure.",
            "LLM-proposed candidates remain draft until a deterministic resolver or explicit user confirmation establishes identity.",
        ],
        facts={
            "chemical.name.status": {"value": status},
            "chemical.name.candidate_count": {"value": len(candidates)},
        },
        files=files,
    )


HANDLERS = {"chemical.name.resolve": resolve}
