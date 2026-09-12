# SPDX-License-Identifier: GPL-2.0-or-later
"""The evidence-chain guards added by ADR-2026-018.

Every defect these cover was fail-open: the matrix produced a verdict that read exactly
like a sound one. None of them could be caught by a clean worktree, a passing test suite,
a validating evidence bundle or a verified graph hash, because all of those check
provenance and identity and none checks whether the matrix hangs together.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from flysim.contracts import NeuralOutputFrame, SignalType
from flysim.demo02 import DECODED, FEED_READOUT_SPECS, DecoderParameters, ProboscisDecoder
from flysim.demo02_acceptance import _provenance, read_variant
from flysim.errors import ConfigurationError, ValidationError

REPO = Path(__file__).resolve().parent.parent


def _neural(*, t_us: int, counts: dict[str, int], hz: float = 99.0) -> NeuralOutputFrame:
    """A readout frame carrying a large filtered rate and whatever raw counts are given."""
    return NeuralOutputFrame(
        t_us=t_us,
        ids=("rostrum-mn9",),
        values=(hz,),
        units="Hz",
        signal_type=SignalType.FIRING_RATE,
        provenance="E",
        assumption_ids=("DEMO-02",),
        metadata={"raw_population_spike_counts": dict(counts)},
    )


# --------------------------------------------------------------- the corrected mapping


def test_the_feeding_readout_decodes_the_rostrum_protractor_and_not_the_pump() -> None:
    """MN9 protracts the rostrum; MN10 to MN12 are the pharyngeal pump (MOTOR-07).

    DEMO-02 had these exactly inverted until 2026-09-12. It decoded the pump, which
    produced zero spikes in every variant of the recorded matrix, and recorded the
    extensor, which produced ten in the exact run and none without the stimulus.
    """
    names = {spec.name: spec for spec in FEED_READOUT_SPECS}
    assert DECODED["feeding"] == ("rostrum-mn9",)
    assert names["rostrum-mn9"].cell_type == "MN9"
    assert not names["rostrum-mn9"].additional_types

    pump = names["pharyngeal-pump-mn"]
    assert pump.cell_type == "MN10"
    assert set(pump.additional_types) == {"MN11D", "MN11V", "MN12D"}
    assert "NEVER DECODED" in pump.role

    # The haustellum extensor is deliberately unresolved: McKellar names mn4 and Schwarz
    # names MN2, and the project does not settle a source conflict by picking one.
    haustellum = names["haustellum-candidates"]
    assert set([haustellum.cell_type, *haustellum.additional_types]) == {
        "MN2Da", "MN2Db", "MN2V", "MN4a", "MN4b",
    }
    assert "NEVER DECODED" in haustellum.role
    for name in ("pharyngeal-pump-mn", "haustellum-candidates"):
        assert name not in DECODED["feeding"]


def test_the_motor_07_record_carries_a_source_and_a_check_the_data_could_fail() -> None:
    register = json.loads(
        (REPO / "configs/assumptions.json").read_text(encoding="utf-8")
    )
    record = next(r for r in register["records"] if r["id"] == "MOTOR-07")
    assert record["value"]["rostrum_protractor_and_extension_readout"] == ["MN9"]
    assert "MN10" in record["value"]["pharyngeal_pump"]
    assert record["value"]["haustellum_extensor"] == "UNRESOLVED"
    # A mapping with no source is what produced the defect in the first place.
    assert "54978" in record["source"]
    # And the release check that could have refuted it must be recorded, not just done.
    assert "exitNerve" in record["validation"]
    assert "pharyngeal" in record["validation"].lower()


def test_the_feeding_decoder_counts_spikes_because_two_cells_cannot_carry_a_rate() -> None:
    """One spike from two cells at a 15 ms interval is 33.3 Hz. Counting is the honest read."""
    decoder = ProboscisDecoder(
        parameters=DecoderParameters.from_mapping(
            {"quiescent_us": 0, "threshold_hz": 0.0, "spike_threshold": 1,
             "half_spikes": 3.0, "initiation_hold_us": 0, "action_us": 1_000_000}
        )
    )
    assert decoder.parameters.half_spikes == 3.0
    assert "spike count" in (ProboscisDecoder.__doc__ or "").lower()
    with pytest.raises(ConfigurationError):
        DecoderParameters.from_mapping({"half_spikes": 0.0})

    # A rate is never read. A frame carrying a large filtered rate and no raw counts
    # must produce no command: if the decoder still read `value_for`, 99 Hz would act.
    quiet = decoder.decode(_neural(t_us=0, counts={}))
    assert all(value == 0.0 for value in quiet.values)

    # And the same frame with raw counts does act, so the test above is not passing
    # because the decoder is inert.
    loud = ProboscisDecoder(parameters=decoder.parameters).decode(
        _neural(t_us=0, counts={"rostrum-mn9": 6}, hz=0.0)
    )
    assert any(value > 0.0 for value in loud.values)


# ------------------------------------------------------------------ the chain guards


def _variant(
    name: str, *, commit: str = "a" * 40, seed: int = 1, dirty: bool = False,
    experiment: str = "x" * 64,
) -> dict[str, Any]:
    return {
        "directory": f"/runs/{name}",
        "summary": {
            "code_commit": commit, "worktree_dirty": dirty, "seed": seed,
            "experiment_id": "demo02-test-v1", "experiment_sha256": experiment,
            "intervals": 400, "trace_sha256": "b" * 64,
        },
    }


CONTRACT = {
    "control_variants": ["exact", "readout-ablated", "stimulus-absent", "command-replay"],
    "required_controls": ["exact", "readout-ablated", "stimulus-absent"],
}


def test_a_sound_matrix_reports_a_sound_chain() -> None:
    chain = _provenance(CONTRACT, {
        n: _variant(n) for n in ("exact", "readout-ablated", "stimulus-absent")
    })
    assert chain["chain_is_sound"]
    assert chain["chain_faults"] == []
    assert chain["required_controls_missing"] == []
    # A control the contract names but does not require is reported, not faulted.
    assert chain["declared_controls_missing"] == ["command-replay"]


def test_variants_from_different_commits_break_the_chain() -> None:
    """The recorded demo02-escape matrix spanned four commits and nothing said so."""
    chain = _provenance(CONTRACT, {
        "exact": _variant("exact", commit="a" * 40),
        "readout-ablated": _variant("readout-ablated", commit="c" * 40),
        "stimulus-absent": _variant("stimulus-absent", commit="d" * 40),
    })
    assert not chain["chain_is_sound"]
    assert any("3 different commits" in f for f in chain["chain_faults"])


def test_variants_from_different_seeds_break_the_chain() -> None:
    chain = _provenance(CONTRACT, {
        "exact": _variant("exact", seed=1),
        "readout-ablated": _variant("readout-ablated", seed=2),
        "stimulus-absent": _variant("stimulus-absent", seed=1),
    })
    assert not chain["chain_is_sound"]
    assert any("different seeds" in f for f in chain["chain_faults"])


def test_a_missing_required_control_breaks_the_chain_even_if_no_criterion_reads_it() -> None:
    """demo02-escape-legs-v1 named two controls nobody ran, and unscored_required was empty."""
    chain = _provenance(CONTRACT, {
        "exact": _variant("exact"), "readout-ablated": _variant("readout-ablated"),
    })
    assert not chain["chain_is_sound"]
    assert chain["required_controls_missing"] == ["stimulus-absent"]
    assert any("requires controls" in f for f in chain["chain_faults"])


def test_a_dirty_worktree_anywhere_breaks_the_chain() -> None:
    chain = _provenance(CONTRACT, {
        "exact": _variant("exact", dirty=True),
        "readout-ablated": _variant("readout-ablated"),
        "stimulus-absent": _variant("stimulus-absent"),
    })
    assert not chain["chain_is_sound"]
    assert any("dirty worktree" in f for f in chain["chain_faults"])


def test_graph_free_controller_only_record_is_scoreable(tmp_path: Path) -> None:
    """A body-only baseline has no population registry by construction."""
    run = tmp_path / "controller-only"
    _write_run(run, 2, declared=2, digest="real")
    summary_path = run / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["populations"] = {}
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    loaded = read_variant(run)

    assert loaded["decoded_populations"] == ()
    assert loaded["intervals"] == 2


def test_different_contract_versions_break_the_chain() -> None:
    chain = _provenance(CONTRACT, {
        "exact": _variant("exact", experiment="1" * 64),
        "readout-ablated": _variant("readout-ablated", experiment="2" * 64),
        "stimulus-absent": _variant("stimulus-absent", experiment="1" * 64),
    })
    assert not chain["chain_is_sound"]
    assert any("different versions of the contract" in f for f in chain["chain_faults"])


# --------------------------------------------------------- summary and trace coherence


def _write_run(directory: Path, rows: int, *, declared: int, digest: str | None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    trace = directory / "trace.jsonl"
    trace.write_text(
        "".join(
            json.dumps({
                "t_us": (i + 1) * 15_000, "t_start_us": i * 15_000,
                "pose": {"x_mm": 0.0, "y_mm": 0.0, "z_mm": 1.0, "heading_rad": 0.0},
                "command": {"state": "QUIESCENT"}, "readout_raw_counts": {},
                "readout_hz": {}, "body": {},
            }) + "\n"
            for i in range(rows)
        ),
        encoding="utf-8",
    )
    real = hashlib.sha256(trace.read_bytes()).hexdigest()
    (directory / "summary.json").write_text(
        json.dumps({
            "intervals": declared, "populations": {"readout_sizes": [2]},
            "trace_sha256": real if digest == "real" else digest,
            "code_commit": "a" * 40, "seed": 1,
        }),
        encoding="utf-8",
    )


def test_a_truncated_trace_beside_a_stale_summary_is_refused(tmp_path: Path) -> None:
    """The recorder truncates on open; the summary is replaced only on success.

    A killed run therefore leaves a short trace beside the previous run's summary, and
    the evaluator used to score that pair without noticing.
    """
    _write_run(tmp_path / "exact", rows=12, declared=400, digest="real")
    with pytest.raises(ValidationError, match="400 intervals and the trace holds 12"):
        read_variant(tmp_path / "exact")


def test_a_trace_edited_after_the_run_is_refused(tmp_path: Path) -> None:
    _write_run(tmp_path / "exact", rows=10, declared=10, digest="f" * 64)
    with pytest.raises(ValidationError, match="has changed since the run"):
        read_variant(tmp_path / "exact")


def test_a_coherent_run_is_accepted(tmp_path: Path) -> None:
    _write_run(tmp_path / "exact", rows=10, declared=10, digest="real")
    variant = read_variant(tmp_path / "exact")
    assert variant["intervals"] == 10
    # Row-time semantics: every row says which instant each of its parts belongs to.
    assert variant["rows"][0]["t_start_us"] == 0
    assert variant["rows"][0]["t_us"] == 15_000
