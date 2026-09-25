from __future__ import annotations

import pytest

from ts_agent import MemoryStore as TopLevelMemoryStore
from ts_agent import ResearchMemoryService as TopLevelResearchMemoryService
from ts_agent.research import (
    KernelMemoryStore,
    MemoryStore,
    ResearchKernel,
    ResearchMemoryService,
)
from tests.support.workspace_helpers import bootstrap_workspace_fixture


def test_kernel_memory_store_is_only_an_adapter(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    kernel = ResearchKernel(root)
    store = KernelMemoryStore(kernel)

    assert isinstance(store, MemoryStore)
    assert store.load_read_only().map_id == kernel.load_read_only().map_id
    assert store.kernel is kernel
    assert TopLevelMemoryStore is MemoryStore
    assert TopLevelResearchMemoryService is ResearchMemoryService


def test_memory_service_exposes_canonical_map_and_read_projections(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    service = ResearchMemoryService(root)

    research_map = service.read()
    assert research_map.map_id
    assert service.read_projection("map")["map_id"] == research_map.map_id
    assert service.read_projection("summary")["revision"] == research_map.revision

    context = service.context()
    liveness = service.liveness()
    assert context["map_id"] == research_map.map_id
    assert context["map_revision"] == research_map.revision
    assert liveness["map_id"] == research_map.map_id
    assert liveness["map_revision"] == research_map.revision


def test_memory_service_delegates_decision_and_evidence_reads(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    service = ResearchMemoryService(root)

    decisions = service.decisions(limit=4)
    evidence = service.evidence(record_type="artifact", limit=4)
    assert decisions["schema_version"] == "research-decisions/1"
    assert evidence["schema_version"] == "research-evidence/1"
    assert service.read_projection("decisions", limit=4) == decisions
    assert service.read_projection("evidence", record_type="artifact", limit=4) == evidence


def test_memory_service_allows_host_owned_projection_readers(tmp_path) -> None:
    root = bootstrap_workspace_fixture(tmp_path / "workspace")
    seen: list[tuple[str, str]] = []

    def context_reader(research_map, reader_root):
        seen.append(("context", str(reader_root)))
        return {"map_id": research_map.map_id, "source": "host-context"}

    def liveness_reader(research_map, reader_root):
        seen.append(("liveness", str(reader_root)))
        return {"map_id": research_map.map_id, "source": "host-liveness"}

    service = ResearchMemoryService(
        root,
        context_reader=context_reader,
        liveness_reader=liveness_reader,
    )
    assert service.context()["source"] == "host-context"
    assert service.liveness()["source"] == "host-liveness"
    assert seen == [("context", str(root.absolute())), ("liveness", str(root.absolute()))]


def test_memory_service_rejects_unknown_read_projection(tmp_path) -> None:
    service = ResearchMemoryService(tmp_path / "workspace")
    with pytest.raises(Exception, match="unsupported Research Memory read mode"):
        service.read_projection("prompt")
