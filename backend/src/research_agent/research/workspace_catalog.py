"""One physical workspace catalog for Host, Monitor and Web.

Only discovery reads sibling manifests. A lookup resolves one registered
identity or one canonical child; full State validation happens on attachment.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

from research_agent.foundation.io import now_iso, read_json, write_json
from research_agent.foundation.path_safety import lexical_path, path_has_symlink
from .workspace import validate_workspace_manifest, WorkspaceModeError
from research_agent.foundation.protocol import WORKSPACE_ID_PATTERN


class WorkspaceCatalogError(ValueError):
    def __init__(self, message, code="invalid_workspace"):
        super().__init__(message)
        self.code = code


def read_manifest(root, *, attach=False):
    root = lexical_path(root)
    if path_has_symlink(root) or not root.is_dir():
        raise WorkspaceCatalogError("workspace must be a physical directory")
    manifest = read_json(root / "workspace_manifest.json")
    try:
        validate_workspace_manifest(manifest, root, validate_documents=attach)
        if manifest["state"] != "ready":
            raise WorkspaceCatalogError("workspace_admission_required")
        if attach:
            validate_workspace_manifest(manifest, root, require_ready=True)
    except WorkspaceModeError as exc:
        raise WorkspaceCatalogError(str(exc)) from exc
    return manifest


def workspace_id_for(root):
    try:
        return read_manifest(root)["workspace_id"]
    except (OSError, ValueError) as exc:
        raise WorkspaceCatalogError("workspace is not an initialized CoRAgent workspace") from exc


class WorkspaceCatalog:
    SCHEMA = "coragent-workspace-catalog/1"

    def __init__(self, root, *, discovery_roots=None):
        self.root = lexical_path(root)
        self.roots = [lexical_path(p) for p in (discovery_roots if discovery_roots is not None else [root])]
        if any(path_has_symlink(p) for p in [self.root, *self.roots]):
            raise WorkspaceCatalogError("workspace catalog paths cannot contain symbolic links")
        self.directory = self.root / ".coragent-catalog"
        self.path = self.directory / "workspaces.json"

    def _read(self):
        if not self.path.exists():
            return {}
        value = read_json(self.path)
        if value.get("schema_version") != self.SCHEMA or not isinstance(value.get("workspaces"), dict):
            raise WorkspaceCatalogError("invalid workspace catalog schema")
        return value["workspaces"]

    @contextmanager
    def _locked(self):
        if path_has_symlink(self.directory):
            raise WorkspaceCatalogError("workspace catalog cannot contain symbolic links")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _write(self, rows):
        write_json(self.path, {"schema_version": self.SCHEMA, "workspaces": rows})

    def _row(self, root, previous=None, *, attach=False):
        manifest = read_manifest(root, attach=attach)
        previous = previous or {}
        return {"workspace_id": manifest["workspace_id"], "source_root": str(lexical_path(root)),
                "label": previous.get("label", manifest["workspace_id"]),
                "registered_at": previous.get("registered_at", now_iso())}

    @staticmethod
    def _merge(rows, row):
        previous = rows.get(row["workspace_id"])
        if previous and previous["source_root"] != row["source_root"]:
            raise WorkspaceCatalogError("Workspace identity is duplicated: " + row["workspace_id"])
        for identity, existing in rows.items():
            if existing["source_root"] == row["source_root"] and identity != row["workspace_id"]:
                raise WorkspaceCatalogError("Registered workspace identity changed: " + identity)
        rows[row["workspace_id"]] = row

    def list(self, *, discover=True):
        with self._locked():
            stored = self._read()
            rows = dict(stored)
            if discover:
                for root in self.roots:
                    if path_has_symlink(root) or not root.is_dir():
                        continue
                    for child in sorted(root.iterdir()):
                        if child.name.startswith(".") or not child.is_dir() or child.is_symlink():
                            continue
                        try:
                            row = self._row(child)
                        except (OSError, ValueError):
                            continue
                        prior = rows.get(row["workspace_id"])
                        self._merge(rows, {**row, **({"label": prior["label"], "registered_at": prior["registered_at"]} if prior else {})})
            result = []
            for identity, row in rows.items():
                try:
                    current = self._row(row["source_root"], row)
                except (OSError, ValueError):
                    continue
                if current["workspace_id"] != identity:
                    raise WorkspaceCatalogError("Registered workspace identity changed: " + identity)
                result.append(current)
            if rows != stored:
                self._write(rows)
        return sorted(result, key=lambda row: row["workspace_id"])

    def resolve(self, workspace_id, *, allow_missing=False, attach=False):
        if not isinstance(workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise WorkspaceCatalogError("workspace_id_invalid")
        rows = self._read()
        registered = rows.get(workspace_id)
        candidates = [lexical_path(registered["source_root"])] if registered else [root / workspace_id for root in self.roots]
        matches = []
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                row = self._row(candidate, registered, attach=attach)
                if row["workspace_id"] != workspace_id:
                    raise WorkspaceCatalogError("Workspace directory has another identity")
                matches.append(row)
            except (OSError, ValueError) as exc:
                raise WorkspaceCatalogError(str(exc)) from exc
        if len(matches) > 1:
            raise WorkspaceCatalogError("Workspace identity is duplicated: " + workspace_id)
        if matches:
            return matches[0]
        if allow_missing and not registered and len(self.roots) == 1:
            return {"workspace_id": workspace_id, "source_root": str(self.roots[0] / workspace_id)}
        raise WorkspaceCatalogError("Workspace does not exist: " + workspace_id, "workspace_not_found")

    def register(self, source_roots, labels=None):
        labels = labels or []
        if len(labels) > len(source_roots):
            raise WorkspaceCatalogError("more labels than source roots")
        registered = []
        with self._locked():
            rows = self._read()
            for index, source in enumerate(source_roots):
                if self.directory.is_relative_to(lexical_path(source)):
                    raise WorkspaceCatalogError("workspace catalog must not be inside a research workspace")
                try:
                    row = self._row(source, attach=True)
                except (OSError, ValueError) as exc:
                    raise WorkspaceCatalogError("workspace is not an initialized CoRAgent workspace") from exc
                previous = rows.get(row["workspace_id"])
                if previous:
                    row.update(label=previous["label"], registered_at=previous["registered_at"])
                if index < len(labels):
                    row["label"] = labels[index]
                self._merge(rows, row)
                registered.append(row)
            self._write(rows)
        return registered

    def remove(self, workspace_id):
        if not isinstance(workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise WorkspaceCatalogError("workspace_id_invalid")
        with self._locked():
            rows = self._read()
            if workspace_id not in rows:
                raise WorkspaceCatalogError("no workspace with id: " + workspace_id, "workspace_not_found")
            del rows[workspace_id]
            self._write(rows)
        return {"removed": workspace_id, "remaining": len(rows)}


def catalog_for_web(state_dir, configured_roots=None):
    state = lexical_path(state_dir)
    if path_has_symlink(state):
        raise WorkspaceCatalogError("web state_dir cannot contain a symbolic link")
    if configured_roots is not None:
        roots = [lexical_path(root) for root in configured_roots]
    else:
        roots = []
    catalog = WorkspaceCatalog(roots[0] if roots else state / "catalog", discovery_roots=roots)
    return catalog


def dispatch(root, request):
    catalog = WorkspaceCatalog(root)
    operation = request["operation"]
    if operation == "list":
        return {"workspaces": catalog.list()}
    if operation == "resolve":
        return catalog.resolve(request["workspace_id"], allow_missing=request.get("allow_missing", False), attach=request.get("attach", False))
    if operation == "register":
        return {"workspaces": catalog.register(request["source_roots"], request.get("labels"))}
    raise WorkspaceCatalogError("unsupported workspace catalog operation")
