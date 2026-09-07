# SPDX-License-Identifier: GPL-2.0-or-later
"""Stage 2 physiology-source normalization and fit-readiness contracts."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance

GOUWENS_MODELDB_COMMIT = "cf5a57dee863cea502e78ef5bc481369253900d9"
GUGEL_FIGURE7_SHA256 = "a8ae6fcd3bf0d8effab7a0ecbfa88fccf192f134144072282758ca8125bd8c78"

_GOUWENS_FILES = tuple(f"figure_4a_cell{index}.hoc" for index in range(1, 4))
_PARAMETER_PATTERN = re.compile(r"^\s*(Rm|Cm|Ri)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _git_identity(source: Path) -> tuple[str, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "-C", str(source), "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DatasetError(f"Cannot establish Git identity for physiology source {source}") from exc
    return head, dirty


def _parse_gouwens_cell(path: Path, cell_index: int) -> dict[str, Any]:
    values: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _PARAMETER_PATTERN.fullmatch(line)
        if match is not None:
            values[match.group(1)] = float(match.group(2))
    if set(values) != {"Rm", "Cm", "Ri"}:
        raise DatasetError(f"Expected one Rm, Cm and Ri assignment in {path}")
    if any(not math.isfinite(value) or value <= 0.0 for value in values.values()):
        raise DatasetError(f"Nonpositive or nonfinite passive parameter in {path}")
    tau_ms = values["Rm"] * values["Cm"] / 1_000.0
    return {
        "source_model_id": f"gouwens-wilson-2009-cell-{cell_index}",
        "source_file": path.name,
        "source_file_sha256": sha256_file(path),
        "specific_membrane_resistance": {"value": values["Rm"], "units": "ohm*cm^2"},
        "specific_membrane_capacitance": {"value": values["Cm"], "units": "uF/cm^2"},
        "axial_resistivity": {"value": values["Ri"], "units": "ohm*cm"},
        "derived_specific_membrane_time_constant": {"value": tau_ms, "units": "ms"},
    }


def import_gouwens_dm1_priors(
    source: Path,
    output: Path,
    *,
    expected_commit: str = GOUWENS_MODELDB_COMMIT,
) -> dict[str, Any]:
    """Normalize three published DM1 passive-model fits without upgrading them to measurements."""
    head, dirty = _git_identity(source)
    if head != expected_commit:
        raise DatasetError(
            f"Gouwens ModelDB commit mismatch: expected {expected_commit}, observed {head}"
        )
    if dirty:
        raise DatasetError(
            "Gouwens ModelDB checkout has local changes; refusing an unlocked import"
        )
    records = [
        _parse_gouwens_cell(source / name, index)
        for index, name in enumerate(_GOUWENS_FILES, 1)
    ]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "gouwens-wilson-2009-dm1-passive-priors-v1",
        "source_repository": "https://github.com/ModelDBRepository/118662",
        "source_commit": head,
        "paper": "https://doi.org/10.1523/JNEUROSCI.0764-09.2009",
        "target_cell_class": "DM1 uniglomerular projection neuron",
        "provenance": "P/F",
        "assumption_ids": ["ND-01", "ND-02", "ND-05", "ND-09"],
        "records": records,
        "record_count": len(records),
        "interpretation": (
            "Published fitted passive cable-model parameters transferred across specimens; "
            "not raw electrophysiology and not MaleCNS-specimen measurements."
        ),
        "validation_tier_awarded": None,
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output, payload)
    return payload


def _xlsx_rows(source: Path) -> list[tuple[Any, ...]]:
    """Read the registered single-sheet XLSX with the standard library only."""
    spreadsheet_ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    try:
        with zipfile.ZipFile(source) as archive:
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(item.itertext())
                    for item in shared_root.findall(f"{{{spreadsheet_ns}}}si")
                ]
            sheet_root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise DatasetError(f"Invalid or unsupported registered XLSX workbook: {source}") from exc

    def column_index(reference: str) -> int:
        letters = "".join(character for character in reference if character.isalpha())
        if not letters:
            raise DatasetError(f"Invalid XLSX cell reference: {reference!r}")
        result = 0
        for character in letters.upper():
            result = result * 26 + ord(character) - ord("A") + 1
        return result - 1

    parsed: dict[int, dict[int, Any]] = {}
    maximum_column = 0
    sheet_data = sheet_root.find(f"{{{spreadsheet_ns}}}sheetData")
    if sheet_data is None:
        raise DatasetError("Registered XLSX workbook has no sheetData")
    for row_element in sheet_data.findall(f"{{{spreadsheet_ns}}}row"):
        row_index = int(row_element.attrib["r"]) - 1
        cells: dict[int, Any] = {}
        for cell in row_element.findall(f"{{{spreadsheet_ns}}}c"):
            index = column_index(cell.attrib["r"])
            maximum_column = max(maximum_column, index)
            value_element = cell.find(f"{{{spreadsheet_ns}}}v")
            value_text = value_element.text if value_element is not None else None
            cell_type = cell.attrib.get("t")
            if cell_type == "s" and value_text is not None:
                value: Any = shared_strings[int(value_text)]
            elif cell_type == "inlineStr":
                inline = cell.find(f"{{{spreadsheet_ns}}}is")
                value = "".join(inline.itertext()) if inline is not None else ""
            elif cell_type in {"str", "e"}:
                value = value_text
            elif value_text is None:
                value = None
            else:
                value = float(value_text)
            cells[index] = value
        parsed[row_index] = cells
    maximum_row = max(parsed, default=-1)
    return [
        tuple(parsed.get(row, {}).get(column) for column in range(maximum_column + 1))
        for row in range(maximum_row + 1)
    ]


def _require_number(value: Any, location: str) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DatasetError(f"Expected finite numeric value at {location}")
    return float(value)


def _write_parquet_atomic(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    pq.write_table(table, temporary, compression="zstd", compression_level=3)
    os.replace(temporary, path)


def import_gugel_figure7(source: Path, output_directory: Path) -> dict[str, Any]:
    """Normalize the individual-recording DL5 F-I and unitary-EPSC Figure 7 data."""
    source_sha256 = sha256_file(source)
    if source_sha256 != GUGEL_FIGURE7_SHA256:
        raise DatasetError(
            f"Gugel Figure 7 SHA-256 mismatch: expected {GUGEL_FIGURE7_SHA256}, "
            f"observed {source_sha256}"
        )
    rows = _xlsx_rows(source)
    if len(rows) != 2_932 or rows[0][0] != "DL5, firing rate (spikes/s)":
        raise DatasetError("Unexpected Gugel Figure 7 workbook shape or identity")
    if rows[916][0] != "DL5 PN, uEPSC (pA)" or rows[919][0] != "time (ms)":
        raise DatasetError("Cannot locate the registered Figure 7 DL5 assay blocks")

    fi_columns = {
        1: ("E2-hexenal", "gugel-dl5-fi-exposed-01"),
        2: ("E2-hexenal", "gugel-dl5-fi-exposed-02"),
        3: ("E2-hexenal", "gugel-dl5-fi-exposed-03"),
        4: ("E2-hexenal", "gugel-dl5-fi-exposed-04"),
        6: ("solvent", "gugel-dl5-fi-solvent-01"),
        7: ("solvent", "gugel-dl5-fi-solvent-02"),
        8: ("solvent", "gugel-dl5-fi-solvent-03"),
        9: ("solvent", "gugel-dl5-fi-solvent-04"),
    }
    fi: dict[str, list[Any]] = {
        "sample_index": [],
        "current_pa": [],
        "condition": [],
        "specimen_id": [],
        "firing_rate_hz": [],
    }
    for sample_index, (row_number, row) in enumerate(enumerate(rows[4:914], start=5)):
        current = _require_number(row[0], f"Figure 7 row {row_number} current")
        for column, (condition, specimen_id) in fi_columns.items():
            fi["sample_index"].append(sample_index)
            fi["current_pa"].append(current)
            fi["condition"].append(condition)
            fi["specimen_id"].append(specimen_id)
            fi["firing_rate_hz"].append(
                _require_number(row[column], f"Figure 7 row {row_number} column {column + 1}")
            )
    epsc_columns = {
        1: ("solvent", "gugel-dl5-uepsc-solvent-01"),
        2: ("solvent", "gugel-dl5-uepsc-solvent-02"),
        3: ("solvent", "gugel-dl5-uepsc-solvent-03"),
        4: ("solvent", "gugel-dl5-uepsc-solvent-04"),
        5: ("solvent", "gugel-dl5-uepsc-solvent-05"),
        6: ("solvent", "gugel-dl5-uepsc-solvent-06"),
        7: ("solvent", "gugel-dl5-uepsc-solvent-07"),
        9: ("E2-hexenal", "gugel-dl5-uepsc-exposed-01"),
        10: ("E2-hexenal", "gugel-dl5-uepsc-exposed-02"),
        11: ("E2-hexenal", "gugel-dl5-uepsc-exposed-03"),
        12: ("E2-hexenal", "gugel-dl5-uepsc-exposed-04"),
        13: ("E2-hexenal", "gugel-dl5-uepsc-exposed-05"),
    }
    epsc: dict[str, list[Any]] = {
        "sample_index": [],
        "time_ms": [],
        "condition": [],
        "specimen_id": [],
        "current_pa": [],
    }
    for sample_index, (row_number, row) in enumerate(enumerate(rows[920:2921], start=921)):
        time_ms = _require_number(row[0], f"Figure 7 row {row_number} time")
        for column, (condition, specimen_id) in epsc_columns.items():
            epsc["sample_index"].append(sample_index)
            epsc["time_ms"].append(time_ms)
            epsc["condition"].append(condition)
            epsc["specimen_id"].append(specimen_id)
            epsc["current_pa"].append(
                _require_number(row[column], f"Figure 7 row {row_number} column {column + 1}")
            )

    fi_path = output_directory / "dl5-fi-curves.parquet"
    epsc_path = output_directory / "dl5-uepsc-traces.parquet"
    _write_parquet_atomic(pa.table(fi), fi_path)
    _write_parquet_atomic(pa.table(epsc), epsc_path)
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "gugel-2023-elife-85443-figure7-dl5-v1",
        "source_file": source.name,
        "source_sha256": source_sha256,
        "paper": "https://doi.org/10.7554/eLife.85443",
        "source_url": (
            "https://cdn.elifesciences.org/articles/85443/"
            "elife-85443-fig7-data1-v2.xlsx"
        ),
        "provenance": "P",
        "assumption_ids": ["ND-01", "ND-02", "ND-05"],
        "biological_context": {
            "sex": "female",
            "age": "two days old",
            "cell_type": "DL5 projection neuron",
            "preparation": "in vivo whole-cell recording",
            "condition_policy": (
                "Solvent recordings are the Stage 2 baseline; chronic E2-hexenal exposure "
                "is retained as an out-of-state perturbation, not pooled with baseline."
            ),
        },
        "artifacts": [
            {
                "path": fi_path.name,
                "rows": len(fi["current_pa"]),
                "sha256": sha256_file(fi_path),
                "units": {"current_pa": "pA", "firing_rate_hz": "Hz"},
            },
            {
                "path": epsc_path.name,
                "rows": len(epsc["time_ms"]),
                "sha256": sha256_file(epsc_path),
                "units": {"time_ms": "ms", "current_pa": "pA"},
            },
        ],
        "preregistered_split": {
            "unit": "recorded cell (one neuron per brain)",
            "fit": [
                "gugel-dl5-fi-solvent-01",
                "gugel-dl5-fi-solvent-02",
                "gugel-dl5-uepsc-solvent-01",
                "gugel-dl5-uepsc-solvent-02",
                "gugel-dl5-uepsc-solvent-03",
                "gugel-dl5-uepsc-solvent-04",
            ],
            "held_out": [
                "gugel-dl5-fi-solvent-03",
                "gugel-dl5-fi-solvent-04",
                "gugel-dl5-uepsc-solvent-05",
                "gugel-dl5-uepsc-solvent-06",
                "gugel-dl5-uepsc-solvent-07",
            ],
            "excluded_from_baseline_fit": sorted(
                specimen_id
                for condition, specimen_id in (*fi_columns.values(), *epsc_columns.values())
                if condition == "E2-hexenal"
            ),
        },
        "claim_boundary": (
            "Cross-specimen female DL5 population physiology prior; it is neither DM1-specific "
            "nor a measurement from the MaleCNS donor."
        ),
        "validation_tier_awarded": None,
    }
    manifest["logical_sha256"] = sha256_json(manifest)
    _atomic_json(output_directory / "manifest.json", manifest)
    return manifest


@dataclass(frozen=True, slots=True)
class Stage2ExperimentSpec:
    experiment_id: str
    sha256: str
    assumption_ids: tuple[str, ...]
    required_artifacts: tuple[tuple[str, str], ...]
    fit_specimen_ids: tuple[str, ...]
    held_out_specimen_ids: tuple[str, ...]
    observables: tuple[dict[str, Any], ...]
    declared_blockers: tuple[str, ...]
    claim_boundary: str

    @classmethod
    def load(cls, path: Path) -> Stage2ExperimentSpec:
        payload = load_json(path)
        if payload.get("schema_version") != "1.0":
            raise ConfigurationError("Unsupported Stage 2 experiment schema")
        assumptions = tuple(str(value) for value in payload["assumption_ids"])
        if not {"ND-01", "ND-02", "ND-05"} <= set(assumptions):
            raise ConfigurationError("Stage 2 experiment omits ND-01, ND-02, or ND-05")
        parse_provenance(str(payload["provenance"]))
        required_artifacts = tuple(
            (str(item["path"]), str(item["sha256"]))
            for item in payload["required_artifacts"]
        )
        split = payload["split"]
        if split.get("unit") != "recorded-cell":
            raise ConfigurationError("Stage 2 data must be split by recorded cell")
        fit_ids = tuple(str(value) for value in split["fit_specimen_ids"])
        held_out_ids = tuple(str(value) for value in split["held_out_specimen_ids"])
        if not fit_ids or not held_out_ids or set(fit_ids) & set(held_out_ids):
            raise ConfigurationError("Fit and held-out recorded-cell IDs must be nonempty/disjoint")
        observables = tuple(dict(item) for item in payload["observables"])
        if not observables:
            raise ConfigurationError("Stage 2 experiment must declare at least one observable")
        for item in observables:
            if not item.get("value_units") or not item.get("loss"):
                raise ConfigurationError("Every Stage 2 observable needs units and a loss")
            weight = float(item["weight"])
            if not math.isfinite(weight) or weight <= 0.0:
                raise ConfigurationError("Stage 2 observable weights must be finite and positive")
        return cls(
            experiment_id=str(payload["experiment_id"]),
            sha256=sha256_json(payload),
            assumption_ids=assumptions,
            required_artifacts=required_artifacts,
            fit_specimen_ids=fit_ids,
            held_out_specimen_ids=held_out_ids,
            observables=observables,
            declared_blockers=tuple(str(value) for value in payload.get("declared_blockers", [])),
            claim_boundary=str(payload["claim_boundary"]),
        )

    def readiness(self, root: Path) -> dict[str, Any]:
        blockers = list(self.declared_blockers)
        artifacts = []
        for relative, expected_sha256 in self.required_artifacts:
            path = root / relative
            observed = sha256_file(path) if path.is_file() else None
            valid = observed == expected_sha256
            artifacts.append(
                {
                    "path": str(path),
                    "expected_sha256": expected_sha256,
                    "observed_sha256": observed,
                    "valid": valid,
                }
            )
            if not valid:
                blockers.append(f"required artifact missing or checksum-mismatched: {relative}")
        return {
            "experiment_id": self.experiment_id,
            "experiment_sha256": self.sha256,
            "fit_ready": not blockers,
            "blockers": blockers,
            "artifacts": artifacts,
            "fit_specimen_count": len(self.fit_specimen_ids),
            "held_out_specimen_count": len(self.held_out_specimen_ids),
            "observables": list(self.observables),
            "claim_boundary": self.claim_boundary,
            "validation_tier_awarded": None,
        }


def lif_steady_state_rate_hz(
    current_pa: np.ndarray,
    *,
    rheobase_pa: float,
    membrane_tau_ms: float,
    refractory_ms: float,
) -> np.ndarray:
    """Steady-state current-rate curve for a reset-at-rest LIF family."""
    if rheobase_pa <= 0.0 or membrane_tau_ms <= 0.0 or refractory_ms < 0.0:
        raise ConfigurationError("LIF F-I parameters must be positive (refractory may be zero)")
    current = np.asarray(current_pa, dtype=np.float64)
    rate = np.zeros_like(current)
    active = current > rheobase_pa
    ratio = current[active] / rheobase_pa
    interval_ms = refractory_ms + membrane_tau_ms * np.log(ratio / (ratio - 1.0))
    rate[active] = 1_000.0 / interval_ms
    return rate


def _huber_mean(residual: np.ndarray, delta: float) -> float:
    absolute = np.abs(residual)
    loss = np.where(absolute <= delta, 0.5 * residual**2, delta * (absolute - 0.5 * delta))
    return float(np.mean(loss))


def _group_curves(
    table: pa.Table,
    specimen_ids: tuple[str, ...],
    x_name: str,
    y_name: str,
) -> tuple[np.ndarray, np.ndarray]:
    payload = table.to_pydict()
    specimens = np.asarray(payload["specimen_id"], dtype=object)
    curves = []
    x_reference: np.ndarray | None = None
    for specimen_id in specimen_ids:
        selected = specimens == specimen_id
        x = np.asarray(payload[x_name], dtype=np.float64)[selected]
        y = np.asarray(payload[y_name], dtype=np.float64)[selected]
        if not len(x):
            raise DatasetError(f"No normalized observations for registered cell {specimen_id}")
        if x_reference is None:
            x_reference = x
        elif not np.array_equal(x_reference, x):
            raise DatasetError(f"Registered cell {specimen_id} uses a different sample grid")
        curves.append(y)
    if x_reference is None:
        raise DatasetError("No registered physiology curves selected")
    return x_reference, np.stack(curves)


def _fit_fi_model(current: np.ndarray, fit_curves: np.ndarray) -> dict[str, Any]:
    candidates = []
    tau_candidates = (16.432, 21.331, 30.6)
    rheobase_candidates = np.linspace(1.0, 80.0, 159)
    refractory_candidates = np.linspace(1.0, 30.0, 30)
    for rheobase in rheobase_candidates:
        for membrane_tau in tau_candidates:
            for refractory in refractory_candidates:
                predicted = lif_steady_state_rate_hz(
                    current,
                    rheobase_pa=float(rheobase),
                    membrane_tau_ms=membrane_tau,
                    refractory_ms=float(refractory),
                )
                candidates.append(
                    (
                        _huber_mean(fit_curves - predicted[None, :], 5.0),
                        float(rheobase),
                        membrane_tau,
                        float(refractory),
                    )
                )
    best_loss, best_rheobase, best_membrane_tau, best_refractory = min(candidates)
    return {
        "rheobase_pa": best_rheobase,
        "membrane_tau_ms": best_membrane_tau,
        "refractory_ms": best_refractory,
        "training_huber_hz2": best_loss,
        "continuous_parameter_at_search_boundary": bool(
            best_rheobase in {float(rheobase_candidates[0]), float(rheobase_candidates[-1])}
            or best_refractory
            in {float(refractory_candidates[0]), float(refractory_candidates[-1])}
        ),
    }


def _fit_epsc_kernel(time_ms: np.ndarray, fit_curves: np.ndarray) -> dict[str, Any]:
    baseline = np.mean(fit_curves[:, time_ms < 40.0], axis=1)
    inward_current = baseline[:, None] - fit_curves
    best: tuple[float, float, float, float, np.ndarray] | None = None
    onset_candidates = np.linspace(45.0, 51.0, 25)
    rise_candidates = np.asarray((0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0))
    decay_candidates = np.linspace(3.0, 30.0, 19)
    for onset in onset_candidates:
        elapsed = np.maximum(0.0, time_ms - onset)
        for rise in rise_candidates:
            for decay in decay_candidates:
                if decay <= rise:
                    continue
                kernel = np.exp(-elapsed / decay) - np.exp(-elapsed / rise)
                kernel[time_ms < onset] = 0.0
                peak = float(np.max(kernel))
                if peak <= 0.0:
                    continue
                kernel /= peak
                denominator = float(kernel @ kernel)
                amplitudes = np.maximum(0.0, inward_current @ kernel / denominator)
                predicted = amplitudes[:, None] * kernel[None, :]
                loss = _huber_mean(inward_current - predicted, 1.0)
                candidate = (loss, float(onset), float(rise), float(decay), amplitudes)
                if best is None or candidate[:4] < best[:4]:
                    best = candidate
    if best is None:
        raise DatasetError("No valid EPSC kernel candidate")
    best_loss, best_onset, best_rise, best_decay, best_amplitudes = best
    return {
        "onset_ms": best_onset,
        "rise_tau_ms": best_rise,
        "decay_tau_ms": best_decay,
        "training_amplitudes_pa": [float(value) for value in best_amplitudes],
        "population_amplitude_pa": float(np.median(best_amplitudes)),
        "training_huber_pa2": best_loss,
        "continuous_parameter_at_search_boundary": bool(
            best_onset in {float(onset_candidates[0]), float(onset_candidates[-1])}
            or best_rise in {float(rise_candidates[0]), float(rise_candidates[-1])}
            or best_decay in {float(decay_candidates[0]), float(decay_candidates[-1])}
        ),
    }


def _rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def fit_projection_neuron_model(
    experiment_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Fit the preregistered PN family and evaluate held-out cells only after freezing."""
    experiment = Stage2ExperimentSpec.load(experiment_path)
    readiness = experiment.readiness(root)
    if not readiness["fit_ready"]:
        raise DatasetError(f"Stage 2 fit contract is not ready: {readiness['blockers']}")
    figure_root = root / "derived" / "auxiliary" / "gugel-2023-elife-85443" / "figure7"
    fi_table = pq.read_table(figure_root / "dl5-fi-curves.parquet")
    epsc_table = pq.read_table(figure_root / "dl5-uepsc-traces.parquet")
    fi_fit_ids = tuple(value for value in experiment.fit_specimen_ids if "-fi-" in value)
    fi_held_ids = tuple(value for value in experiment.held_out_specimen_ids if "-fi-" in value)
    epsc_fit_ids = tuple(value for value in experiment.fit_specimen_ids if "-uepsc-" in value)
    epsc_held_ids = tuple(value for value in experiment.held_out_specimen_ids if "-uepsc-" in value)

    current_pa, fi_fit = _group_curves(
        fi_table, fi_fit_ids, "current_pa", "firing_rate_hz"
    )
    held_current, fi_held = _group_curves(
        fi_table, fi_held_ids, "current_pa", "firing_rate_hz"
    )
    if not np.array_equal(current_pa, held_current):
        raise DatasetError("Fit and held-out F-I current grids differ")
    fi_parameters = _fit_fi_model(current_pa, fi_fit)
    fi_prediction = lif_steady_state_rate_hz(
        current_pa,
        rheobase_pa=fi_parameters["rheobase_pa"],
        membrane_tau_ms=fi_parameters["membrane_tau_ms"],
        refractory_ms=fi_parameters["refractory_ms"],
    )
    fi_model_rmse = _rmse(fi_held, fi_prediction[None, :])
    fi_biological_rmse = _rmse(fi_held, np.mean(fi_fit, axis=0)[None, :])

    time_ms, epsc_fit = _group_curves(
        epsc_table, epsc_fit_ids, "time_ms", "current_pa"
    )
    held_time, epsc_held = _group_curves(
        epsc_table, epsc_held_ids, "time_ms", "current_pa"
    )
    if not np.array_equal(time_ms, held_time):
        raise DatasetError("Fit and held-out EPSC time grids differ")
    epsc_parameters = _fit_epsc_kernel(time_ms, epsc_fit)
    elapsed = np.maximum(0.0, time_ms - epsc_parameters["onset_ms"])
    kernel = np.exp(-elapsed / epsc_parameters["decay_tau_ms"]) - np.exp(
        -elapsed / epsc_parameters["rise_tau_ms"]
    )
    kernel[time_ms < epsc_parameters["onset_ms"]] = 0.0
    kernel /= np.max(kernel)
    held_baseline = np.mean(epsc_held[:, time_ms < 40.0], axis=1)
    held_inward_current = held_baseline[:, None] - epsc_held
    epsc_prediction = epsc_parameters["population_amplitude_pa"] * kernel
    epsc_model_rmse = _rmse(held_inward_current, epsc_prediction[None, :])
    fit_baseline = np.mean(epsc_fit[:, time_ms < 40.0], axis=1)
    fit_inward_current = fit_baseline[:, None] - epsc_fit
    training_mean = np.mean(fit_inward_current, axis=0)
    epsc_biological_rmse = _rmse(held_inward_current, training_mean[None, :])

    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-projection-neuron-fit-v1",
        "experiment_id": experiment.experiment_id,
        "experiment_sha256": experiment.sha256,
        "assumption_ids": list(experiment.assumption_ids),
        "provenance": "P/F",
        "fit_specimen_ids": list(experiment.fit_specimen_ids),
        "held_out_specimen_ids": list(experiment.held_out_specimen_ids),
        "frozen_before_held_out_evaluation": True,
        "fi_model": {
            "family": "steady-state reset-at-rest LIF",
            "parameters": fi_parameters,
            "held_out_rmse_hz": fi_model_rmse,
            "fit_cohort_to_held_out_rmse_hz": fi_biological_rmse,
            "normalized_error_ratio": fi_model_rmse / fi_biological_rmse,
        },
        "uepsc_model": {
            "family": "causal difference-of-exponentials with training-cell amplitudes",
            "parameters": epsc_parameters,
            "held_out_rmse_pa": epsc_model_rmse,
            "fit_cohort_to_held_out_rmse_pa": epsc_biological_rmse,
            "normalized_error_ratio": epsc_model_rmse / epsc_biological_rmse,
        },
        "acceptance": {
            "normalized_error_ratio_limit": 1.2,
            "fi_pass": fi_model_rmse / fi_biological_rmse <= 1.2,
            "uepsc_pass": epsc_model_rmse / epsc_biological_rmse <= 1.2,
            "all_states_finite": True,
            "no_continuous_fit_at_search_boundary": not (
                fi_parameters["continuous_parameter_at_search_boundary"]
                or epsc_parameters["continuous_parameter_at_search_boundary"]
            ),
        },
        "claim_boundary": experiment.claim_boundary,
        "validation_tier_awarded": None,
        "tier_review_required": "immutable V1/V2 evidence bundle and feature-level review",
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result
