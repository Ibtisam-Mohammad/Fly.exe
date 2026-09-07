# SPDX-License-Identifier: GPL-2.0-or-later
import json
import subprocess
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.stage2 import (
    Stage2ExperimentSpec,
    adaptive_lif_ramp_rate_hz,
    evaluate_dynamic_projection_neuron_holdout,
    import_gouwens_dm1_priors,
    import_gugel_figure7,
    import_nanami_pn_trace,
    lif_steady_state_rate_hz,
    review_dynamic_projection_neuron_timestep,
    review_projection_neuron_fit,
)


def _commit_fixture(path: Path) -> str:
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_gouwens_import_preserves_three_parameter_fits(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    values = ((8300, 2.57, 163.9), (20400, 1.50, 102.5), (20800, 0.79, 266.1))
    for index, (rm, cm, ri) in enumerate(values, start=1):
        (source / f"figure_4a_cell{index}.hoc").write_text(
            f"Rm = {rm}\nCm = {cm}\nRi = {ri}\n", encoding="utf-8"
        )
    commit = _commit_fixture(source)
    output = tmp_path / "priors.json"

    payload = import_gouwens_dm1_priors(source, output, expected_commit=commit)

    assert payload["record_count"] == 3
    assert [
        record["derived_specific_membrane_time_constant"]["value"]
        for record in payload["records"]
    ] == pytest.approx([21.331, 30.6, 16.432])
    assert payload["provenance"] == "P/F"
    assert payload["validation_tier_awarded"] is None
    assert json.loads(output.read_text(encoding="utf-8"))["source_commit"] == commit


def test_gouwens_import_rejects_dirty_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(1, 4):
        (source / f"figure_4a_cell{index}.hoc").write_text(
            "Rm = 10000\nCm = 1\nRi = 100\n", encoding="utf-8"
        )
    commit = _commit_fixture(source)
    (source / "figure_4a_cell1.hoc").write_text("Rm = 1\nCm = 1\nRi = 1\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="local changes"):
        import_gouwens_dm1_priors(source, tmp_path / "out.json", expected_commit=commit)


def _write_experiment(path: Path, artifact_sha256: str, *, overlap: bool = False) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "experiment_id": "test-stage2",
                "provenance": "P/F",
                "assumption_ids": ["ND-01", "ND-02", "ND-05"],
                "required_artifacts": [
                    {"path": "derived/test.json", "sha256": artifact_sha256}
                ],
                "split": {
                    "unit": "recorded-cell",
                    "fit_specimen_ids": ["cell-1"],
                    "held_out_specimen_ids": ["cell-1" if overlap else "cell-2"],
                },
                "observables": [
                    {
                        "id": "firing-rate",
                        "value_units": "Hz",
                        "loss": "rmse",
                        "weight": 1.0,
                    }
                ],
                "declared_blockers": [],
                "claim_boundary": "test only",
            }
        ),
        encoding="utf-8",
    )


def test_stage2_readiness_requires_locked_artifacts_and_disjoint_cells(tmp_path: Path) -> None:
    artifact = tmp_path / "derived" / "test.json"
    artifact.parent.mkdir()
    artifact.write_text("evidence\n", encoding="utf-8")
    experiment = tmp_path / "experiment.json"
    _write_experiment(experiment, sha256_file(artifact))

    report = Stage2ExperimentSpec.load(experiment).readiness(tmp_path)

    assert report["fit_ready"] is True
    assert report["fit_specimen_count"] == 1
    assert report["held_out_specimen_count"] == 1
    artifact.write_text("changed\n", encoding="utf-8")
    assert Stage2ExperimentSpec.load(experiment).readiness(tmp_path)["fit_ready"] is False

    _write_experiment(experiment, sha256_file(artifact), overlap=True)
    with pytest.raises(ConfigurationError, match="nonempty/disjoint"):
        Stage2ExperimentSpec.load(experiment)


def test_gugel_import_rejects_unlocked_workbook(tmp_path: Path) -> None:
    source = tmp_path / "figure7.xlsx"
    source.write_bytes(b"not the registered workbook")
    with pytest.raises(DatasetError, match="SHA-256 mismatch"):
        import_gugel_figure7(source, tmp_path / "out")


def test_nanami_import_locks_source_and_preserves_raw_samples(tmp_path: Path) -> None:
    source = tmp_path / "source"
    trace = source / "invivo_results" / "PN" / "PN_160310_5_03_v.txt"
    notebook = source / "02_plot_figs" / "analyze_PQNtest.ipynb"
    trace.parent.mkdir(parents=True)
    notebook.parent.mkdir(parents=True)
    trace.write_text("-50.0\n-49.5\n-49.0\n", encoding="ascii")
    notebook.write_text("{}\n", encoding="utf-8")
    commit = _commit_fixture(source)
    output = tmp_path / "normalized"

    payload = import_nanami_pn_trace(
        source,
        output,
        expected_commit=commit,
        expected_trace_sha256=sha256_file(trace),
        expected_analysis_sha256=sha256_file(notebook),
        expected_sample_count=3,
    )

    table = pq.read_table(output / "pn-voltage-trace.parquet")
    assert table.column("t_us").to_pylist() == [0, 100, 200]
    assert table.column("membrane_voltage_mv").to_pylist() == [-50.0, -49.5, -49.0]
    assert payload["biological_context"]["recorded_cell_count"] == 1
    assert payload["protocol_reconstruction"]["step_level_units"].startswith("unresolved")
    assert payload["validation_tier_awarded"] is None


def test_nanami_import_rejects_unlocked_trace(tmp_path: Path) -> None:
    source = tmp_path / "source"
    trace = source / "invivo_results" / "PN" / "PN_160310_5_03_v.txt"
    notebook = source / "02_plot_figs" / "analyze_PQNtest.ipynb"
    trace.parent.mkdir(parents=True)
    notebook.parent.mkdir(parents=True)
    trace.write_text("-50.0\n", encoding="ascii")
    notebook.write_text("{}\n", encoding="utf-8")
    commit = _commit_fixture(source)

    with pytest.raises(DatasetError, match="trace SHA-256 mismatch"):
        import_nanami_pn_trace(
            source,
            tmp_path / "out",
            expected_commit=commit,
            expected_trace_sha256="0" * 64,
            expected_analysis_sha256="0" * 64,
            expected_sample_count=1,
        )


def test_lif_current_rate_is_thresholded_monotonic_and_validated() -> None:
    rates = lif_steady_state_rate_hz(
        np.asarray([0.0, 10.0, 11.0, 20.0]),
        rheobase_pa=10.0,
        membrane_tau_ms=20.0,
        refractory_ms=2.0,
    )

    assert rates[:2].tolist() == [0.0, 0.0]
    assert 0.0 < rates[2] < rates[3]
    with pytest.raises(ConfigurationError, match="must be positive"):
        lif_steady_state_rate_hz(
            np.asarray([1.0]),
            rheobase_pa=0.0,
            membrane_tau_ms=20.0,
            refractory_ms=2.0,
        )


def test_adaptive_lif_replays_windows_and_adaptation_reduces_rate() -> None:
    current = np.asarray([0.0, 20.0, 20.0, 20.0, 20.0])
    without_adaptation = adaptive_lif_ramp_rate_hz(
        current,
        rheobase_pa=10.0,
        membrane_tau_ms=20.0,
        refractory_ms=2.0,
        adaptation_tau_ms=100.0,
        adaptation_increment=0.0,
        integration_step_us=500,
    )
    with_adaptation = adaptive_lif_ramp_rate_hz(
        current,
        rheobase_pa=10.0,
        membrane_tau_ms=20.0,
        refractory_ms=2.0,
        adaptation_tau_ms=100.0,
        adaptation_increment=0.2,
        integration_step_us=500,
    )

    assert without_adaptation[0] == 0.0
    assert np.any(without_adaptation[1:] > 0.0)
    assert np.sum(with_adaptation) < np.sum(without_adaptation)
    with pytest.raises(ConfigurationError, match="must divide"):
        adaptive_lif_ramp_rate_hz(
            current,
            rheobase_pa=10.0,
            membrane_tau_ms=20.0,
            refractory_ms=2.0,
            adaptation_tau_ms=100.0,
            adaptation_increment=0.1,
            integration_step_us=333,
        )


def test_frozen_fit_review_rejects_wrong_result_identity(tmp_path: Path) -> None:
    result = tmp_path / "fit.json"
    result.write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="fit SHA-256 mismatch"):
        review_projection_neuron_fit(
            result,
            tmp_path,
            tmp_path / "review.json",
            expected_fit_sha256="0" * 64,
        )


def test_dynamic_holdout_rejects_wrong_frozen_fit_identity(tmp_path: Path) -> None:
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "evaluation_id": "test",
                "provenance": "P/F/E",
                "frozen_fit": {
                    "path": "fit.json",
                    "sha256": "0" * 64,
                    "experiment_sha256": "1" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "fit.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="Frozen dynamic PN fit SHA-256 mismatch"):
        evaluate_dynamic_projection_neuron_holdout(evaluation, tmp_path, tmp_path / "out.json")


def test_dynamic_timestep_review_rejects_wrong_holdout_identity(tmp_path: Path) -> None:
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "review_id": "test",
                "provenance": "F/E",
                "frozen_holdout_result": {
                    "path": "holdout.json",
                    "sha256": "0" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "holdout.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetError, match="holdout result SHA-256 mismatch"):
        review_dynamic_projection_neuron_timestep(review, tmp_path, tmp_path / "out.json")
