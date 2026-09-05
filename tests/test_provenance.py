# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

from flysim.errors import ConfigurationError
from flysim.provenance import AssumptionRegistry, ProvenanceClass, parse_provenance


def test_project_assumptions_are_complete_and_unique() -> None:
    from flysim.config import project_root

    registry = AssumptionRegistry.load(project_root() / "configs" / "assumptions.json")
    registry.require(
        "DATA-01",
        "DATA-02",
        "DATA-03",
        "DATA-04",
        "DATA-05",
        "ND-01",
        "ND-02",
        "ND-03",
        "ND-04",
        "ND-05",
        "ND-06",
        "ND-07",
        "ND-08",
        "ND-09",
        "SENS-01",
        "SENS-02",
        "SENS-03",
        "SENS-04",
        "SENS-05",
        "MOTOR-01",
        "MOTOR-02",
        "MOTOR-03",
        "BODY-01",
        "BODY-02",
        "STATE-01",
        "STATE-02",
        "LEARN-01",
        "NUM-01",
        "VAL-01",
    )
    assert registry.assumption_set_id == "foundation-v0.2"
    assert registry.sha256


def test_combined_provenance_is_parsed() -> None:
    assert parse_provenance("P/E") == (
        ProvenanceClass.POPULATION_PRIOR,
        ProvenanceClass.ENGINEERING,
    )


def test_invalid_provenance_fails() -> None:
    with pytest.raises(ConfigurationError):
        parse_provenance("unknown")
