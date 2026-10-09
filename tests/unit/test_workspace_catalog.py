from pathlib import Path

import pytest

from research_agent.research import workspace_catalog as module
from research_agent.research.workspace import initialize_workspace, admit_research_workspace
from research_agent.research.workspace_catalog import WorkspaceCatalog, WorkspaceCatalogError, catalog_for_web


def create(root, identity):
    initialize_workspace(root, identity, "research")
    admit_research_workspace(root)


def test_catalog_lists_manifests_but_attachment_checks_state(tmp_path, monkeypatch):
    root = tmp_path / "workspaces"
    create(root / "a", "a")
    create(root / "b", "b")
    (root / "b/research/journal.json").write_text("broken state")
    catalog = WorkspaceCatalog(root)
    assert [row["workspace_id"] for row in catalog.list()] == ["a", "b"]
    with pytest.raises(WorkspaceCatalogError):
        catalog.resolve("b", attach=True)
    # A route to a remains independent of unrelated sibling State and discovery.
    original = module.read_json
    reads = []
    def tracked(path):
        reads.append(Path(path))
        return original(path)
    monkeypatch.setattr(module, "read_json", tracked)
    monkeypatch.setattr(Path, "iterdir", lambda self: pytest.fail("lookup scanned siblings"))
    assert catalog.resolve("a")["source_root"] == str(root / "a")
    assert root / "b/workspace_manifest.json" not in reads


def test_catalog_preserves_external_paths_and_labels_for_host_and_web(tmp_path):
    roots = tmp_path / "install/workspaces"
    external = tmp_path / "external/physical-name"
    create(external, "canonical")
    host = WorkspaceCatalog(roots)
    host.register([external], ["External study"])
    web = catalog_for_web(tmp_path / "install/var/state/web", [roots])
    assert web.resolve("canonical")["source_root"] == str(external)
    assert web.list()[0]["label"] == "External study"
    web.remove("canonical")
    with pytest.raises(WorkspaceCatalogError, match="does not exist"):
        host.resolve("canonical")


def test_discovery_indexes_physical_directory_names_and_rejects_duplicates(tmp_path):
    create(tmp_path / "physical-a", "canonical")
    catalog = WorkspaceCatalog(tmp_path)
    catalog.list()
    assert WorkspaceCatalog(tmp_path).resolve("canonical")["source_root"] == str(tmp_path / "physical-a")
    create(tmp_path / "physical-b", "canonical")
    with pytest.raises(WorkspaceCatalogError, match="duplicated"):
        catalog.list()


def test_catalog_rejects_symlinked_and_reidentified_registration(tmp_path):
    external = tmp_path / "original"
    create(external, "canonical")
    catalog = WorkspaceCatalog(tmp_path / "container")
    catalog.register([external])
    moved = tmp_path / "moved"
    external.rename(moved)
    external.symlink_to(moved, target_is_directory=True)
    with pytest.raises(WorkspaceCatalogError):
        catalog.resolve("canonical")


def test_concurrent_registration_preserves_every_identity(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    roots = [tmp_path / "external" / str(index) for index in range(8)]
    for index, root in enumerate(roots):
        create(root, f"study_{index}")
    catalog_root = tmp_path / "catalog"
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda root: WorkspaceCatalog(catalog_root).register([root]), roots))
    assert len(WorkspaceCatalog(catalog_root).list()) == len(roots)
