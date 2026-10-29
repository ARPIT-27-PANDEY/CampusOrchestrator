from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from academics_mcp.config import DEMO_HANDBOOK_DIR, AcademicsSettings
from academics_mcp.server import build_service
from academics_mcp.service import HandbookService


@pytest.fixture
def handbook_dir(tmp_path: Path) -> Path:
    target = tmp_path / "handbooks"
    shutil.copytree(DEMO_HANDBOOK_DIR, target)
    return target


@pytest.fixture
def settings(handbook_dir: Path) -> AcademicsSettings:
    return AcademicsSettings(handbook_dir=handbook_dir, qdrant_path=":memory:")


@pytest.fixture
def service(settings: AcademicsSettings) -> HandbookService:
    return build_service(settings)
