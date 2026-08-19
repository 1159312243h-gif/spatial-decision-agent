from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from practice.site_selection import AgentState, generate_site_selection_report


_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class SiteSelectionReportNotFoundError(LookupError):
    """Raised when a completed run has no live report artifact."""


@dataclass(frozen=True)
class SiteSelectionReportArtifact:
    path: Path
    public_url: str
    sha256: str


class FileSystemSiteSelectionReportStore:
    """Create and resolve report files below one configured directory."""

    def __init__(
        self,
        root: str | Path,
        *,
        route_prefix: str = "/site-selection/runs",
    ) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        normalized_prefix = "/" + route_prefix.strip("/")
        if normalized_prefix == "/":
            raise ValueError("报告下载路由前缀不能为空")
        self._route_prefix = normalized_prefix

    @property
    def root(self) -> Path:
        return self._root

    def create(
        self,
        run_id: str,
        state: AgentState,
    ) -> SiteSelectionReportArtifact:
        target = self._path_for(run_id)
        temporary = self._root / f".{run_id}.{uuid4().hex}.docx"
        try:
            generate_site_selection_report(state, temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return SiteSelectionReportArtifact(
            path=target,
            public_url=f"{self._route_prefix}/{run_id}/report",
            sha256=_file_sha256(target),
        )

    def resolve(self, run_id: str) -> Path:
        path = self._path_for(run_id)
        if not path.is_file():
            raise SiteSelectionReportNotFoundError(
                f"选址运行报告不存在：{run_id}"
            )
        return path

    def _path_for(self, run_id: str) -> Path:
        if _SAFE_RUN_ID.fullmatch(run_id) is None:
            raise ValueError("run_id 只能包含字母、数字、点、下划线和连字符")
        target = (self._root / f"{run_id}.docx").resolve()
        target.relative_to(self._root)
        return target


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
