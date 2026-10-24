"""
conftest.py
-----------
Global pytest configuration.

* Puts the project root, the updater folder and tests/ on sys.path.
* SAFETY NET: fails the test session if anything modifies the live database
  or the live workbook. Tests must use tmp_path copies only.
"""

import hashlib
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent
for p in (ROOT_DIR, ROOT_DIR / "data" / "excel_autofetch", ROOT_DIR / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(scope="session", autouse=True)
def live_data_must_not_change():
    import config

    live = [config.DB_PATH, config.EXCEL_PATH]
    before = {p: _digest(p) for p in live}
    yield
    after = {p: _digest(p) for p in live}
    changed = [str(p) for p in live if before[p] != after[p]]
    assert not changed, f"Tests modified live data files: {changed}. Use tmp_path copies."
