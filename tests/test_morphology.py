# SPDX-License-Identifier: GPL-2.0-or-later
from pathlib import Path

import pytest

from flysim.errors import DatasetError
from flysim.morphology import validate_swc


def test_swc_validation_preserves_tree_identity(tmp_path: Path) -> None:
    path = tmp_path / "canary.swc"
    path.write_text("# units 8 nm\n1 1 0 0 0 1 -1\n2 3 1 2 3 0.5 1\n", encoding="utf-8")
    assert validate_swc(path) == {"nodes": 2, "roots": 1, "valid": True}


def test_swc_validation_rejects_missing_parent(tmp_path: Path) -> None:
    path = tmp_path / "bad.swc"
    path.write_text("1 1 0 0 0 1 -1\n2 3 1 2 3 0.5 99\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="missing parent"):
        validate_swc(path)
