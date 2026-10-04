import shutil
from pathlib import Path

import pytest

from opspulse.etl.config import Paths

FIXTURES = Path(__file__).parent / "fixtures" / "olist"


def hex_id(prefix: str) -> str:
    """The fixture ids: readable prefixes padded to Olist's 32-char hex format."""
    return prefix + "0" * (32 - len(prefix))


@pytest.fixture
def fixture_project(tmp_path) -> Paths:
    """A throwaway project root whose raw directory holds the fixture CSVs."""
    paths = Paths(tmp_path)
    shutil.copytree(FIXTURES, paths.raw)
    return paths
