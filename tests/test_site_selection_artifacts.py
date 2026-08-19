from hashlib import sha256

import pytest

from app.services.site_selection_artifacts import (
    FileSystemSiteSelectionReportStore,
    SiteSelectionReportNotFoundError,
)
from tests.test_site_selection_reporting import completed_state


def test_report_store_creates_resolves_and_hashes_artifact(tmp_path) -> None:
    store = FileSystemSiteSelectionReportStore(tmp_path)

    artifact = store.create("run-artifact-001", completed_state())

    assert artifact.path == tmp_path.resolve() / "run-artifact-001.docx"
    assert artifact.public_url == (
        "/site-selection/runs/run-artifact-001/report"
    )
    assert artifact.sha256 == sha256(artifact.path.read_bytes()).hexdigest()
    assert store.resolve("run-artifact-001") == artifact.path


def test_report_store_rejects_unsafe_or_missing_artifact(tmp_path) -> None:
    store = FileSystemSiteSelectionReportStore(tmp_path)

    with pytest.raises(ValueError, match="run_id"):
        store.resolve("../outside")
    with pytest.raises(SiteSelectionReportNotFoundError, match="不存在"):
        store.resolve("missing-run")
