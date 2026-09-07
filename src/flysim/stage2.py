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
NANAMI_REPOSITORY_COMMIT = "c064f47da7a1f8c4e9137c09b5e327d1a38ab9f4"
NANAMI_PN_TRACE_SHA256 = "8566550bc6f7cb97410f81483f90166646cdc9bcde276eb748413a9717759255"
NANAMI_ANALYSIS_SHA256 = "55b010987019ccb826b44be275f650168272abb40140798f94160934667f0de6"

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


def import_nanami_pn_trace(
    source: Path,
    output_directory: Path,
    *,
    expected_commit: str = NANAMI_REPOSITORY_COMMIT,
    expected_trace_sha256: str = NANAMI_PN_TRACE_SHA256,
    expected_analysis_sha256: str = NANAMI_ANALYSIS_SHA256,
    expected_sample_count: int = 200_000,
) -> dict[str, Any]:
    """Normalize the single published Nanami PN trace without deriving outcomes."""
    head, dirty = _git_identity(source)
    if head != expected_commit:
        raise DatasetError(
            f"Nanami repository commit mismatch: expected {expected_commit}, observed {head}"
        )
    if dirty:
        raise DatasetError(
            "Nanami repository checkout has local changes; refusing an unlocked import"
        )

    trace_path = source / "invivo_results" / "PN" / "PN_160310_5_03_v.txt"
    analysis_path = source / "02_plot_figs" / "analyze_PQNtest.ipynb"
    observed_trace_sha256 = sha256_file(trace_path) if trace_path.is_file() else None
    observed_analysis_sha256 = sha256_file(analysis_path) if analysis_path.is_file() else None
    if observed_trace_sha256 != expected_trace_sha256:
        raise DatasetError(
            "Nanami PN trace SHA-256 mismatch: "
            f"expected {expected_trace_sha256}, observed {observed_trace_sha256}"
        )
    if observed_analysis_sha256 != expected_analysis_sha256:
        raise DatasetError(
            "Nanami analysis-notebook SHA-256 mismatch: "
            f"expected {expected_analysis_sha256}, observed {observed_analysis_sha256}"
        )

    values: list[float] = []
    with trace_path.open("r", encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                value = float(line.strip())
            except ValueError as exc:
                raise DatasetError(
                    f"Non-numeric Nanami PN voltage at source line {line_number}"
                ) from exc
            if not math.isfinite(value):
                raise DatasetError(
                    f"Nonfinite Nanami PN voltage at source line {line_number}"
                )
            values.append(value)
    if len(values) != expected_sample_count:
        raise DatasetError(
            f"Nanami PN sample-count mismatch: expected {expected_sample_count}, "
            f"observed {len(values)}"
        )

    normalized_path = output_directory / "pn-voltage-trace.parquet"
    _write_parquet_atomic(
        pa.table(
            {
                "sample_index": pa.array(range(len(values)), type=pa.uint32()),
                "t_us": pa.array((index * 100 for index in range(len(values))), type=pa.uint64()),
                "membrane_voltage_mv": pa.array(values, type=pa.float64()),
            }
        ),
        normalized_path,
    )
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "nanami-2024-pn-current-clamp-trace-v1",
        "source_repository": "https://github.com/tnanami/fly-olfactory-network-fpga",
        "source_commit": head,
        "paper": "https://doi.org/10.3389/fnins.2024.1384336",
        "provenance": "P",
        "assumption_ids": ["ND-01", "ND-02", "ND-05"],
        "source_artifacts": [
            {
                "path": "invivo_results/PN/PN_160310_5_03_v.txt",
                "bytes": trace_path.stat().st_size,
                "sha256": observed_trace_sha256,
            },
            {
                "path": "02_plot_figs/analyze_PQNtest.ipynb",
                "bytes": analysis_path.stat().st_size,
                "sha256": observed_analysis_sha256,
                "role": "protocol-reconstruction code only; notebook outputs are not evidence",
            },
        ],
        "normalized_artifact": {
            "path": normalized_path.name,
            "rows": len(values),
            "sha256": sha256_file(normalized_path),
            "units": {"t_us": "us", "membrane_voltage_mv": "mV"},
        },
        "biological_context": {
            "species": "Drosophila melanogaster",
            "sex": "female",
            "age": "three days post eclosion",
            "cell_class": "olfactory projection neuron",
            "driver": "VT033006-Gal4",
            "preparation": "in vivo whole-cell current clamp from a PN soma",
            "recorded_cell_count": 1,
            "sampling_rate_hz": 10_000,
        },
        "protocol_reconstruction": {
            "status": "partially reconstructed from the pinned analysis notebook",
            "step_levels": [3, 4, 5, 6, 7, 8, 9, 10],
            "step_level_units": "unresolved source-code units; do not assume pA",
            "step_duration_ms": 1_000,
            "interpulse_interval_ms": 1_000,
            "alignment_threshold_mv": -55.0,
            "alignment_search_after_ms": 4_000.0,
            "extraction_start_relative_to_first_crossing_ms": -306.5,
            "source_alignment_rule": (
                "The published notebook locates the first voltage crossing above -55 mV after "
                "4 s, starts extraction 306.5 ms before that crossing, and extracts eight 1 s "
                "windows every 2 s."
            ),
        },
        "validation_role": (
            "Sealed external single-cell time-domain challenge for a model fitted without this "
            "trace; never a training or parameter-selection source."
        ),
        "claim_boundary": (
            "One female PN trace with source-code-reconstructed stimulus alignment and unresolved "
            "absolute current units cannot establish a PN population distribution or award V1."
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


def adaptive_lif_ramp_rate_hz(
    current_pa: np.ndarray,
    *,
    rheobase_pa: float,
    membrane_tau_ms: float,
    refractory_ms: float,
    adaptation_tau_ms: float,
    adaptation_increment: float,
    integration_step_us: int = 100,
    sample_interval_ms: float = 25.0,
    rate_window_ms: float = 50.0,
) -> np.ndarray:
    """Replay a current protocol through a dimensionless adaptive LIF point neuron."""
    parameters = (
        rheobase_pa,
        membrane_tau_ms,
        refractory_ms,
        adaptation_tau_ms,
        adaptation_increment,
    )
    if any(not math.isfinite(value) for value in parameters):
        raise ConfigurationError("Adaptive LIF parameters must be finite")
    if (
        rheobase_pa <= 0.0
        or membrane_tau_ms <= 0.0
        or refractory_ms < 0.0
        or adaptation_tau_ms <= 0.0
        or adaptation_increment < 0.0
    ):
        raise ConfigurationError(
            "Adaptive LIF time/scale parameters must be positive (refractory and adaptation "
            "increment may be zero)"
        )
    if integration_step_us <= 0:
        raise ConfigurationError("Adaptive LIF integration step must be positive")
    dt_ms = integration_step_us / 1_000.0
    steps_per_sample = sample_interval_ms / dt_ms
    samples_per_window = rate_window_ms / sample_interval_ms
    if (
        not steps_per_sample.is_integer()
        or not samples_per_window.is_integer()
    ):
        raise ConfigurationError(
            "Adaptive LIF steps must divide the source interval and rate window exactly"
        )
    current = np.asarray(current_pa, dtype=np.float64)
    if current.ndim != 1 or not np.all(np.isfinite(current)):
        raise ConfigurationError("Adaptive LIF current protocol must be one-dimensional and finite")

    v = 0.0
    adaptation = 0.0
    refractory_remaining_ms = 0.0
    spikes_per_sample = np.zeros(len(current), dtype=np.int32)
    for sample_index, injected_current in enumerate(current):
        spike_count = 0
        for _ in range(int(steps_per_sample)):
            adaptation += -adaptation * dt_ms / adaptation_tau_ms
            if refractory_remaining_ms > 0.0:
                refractory_remaining_ms = max(0.0, refractory_remaining_ms - dt_ms)
                continue
            v += (
                -v + injected_current / rheobase_pa - adaptation
            ) * dt_ms / membrane_tau_ms
            if v >= 1.0:
                spike_count += 1
                v = 0.0
                adaptation += adaptation_increment
                refractory_remaining_ms = refractory_ms
        spikes_per_sample[sample_index] = spike_count

    window_samples = int(samples_per_window)
    cumulative = np.concatenate(([0], np.cumsum(spikes_per_sample, dtype=np.int64)))
    rates = np.empty(len(current), dtype=np.float64)
    for index in range(len(current)):
        start = max(0, index + 1 - window_samples)
        count = cumulative[index + 1] - cumulative[start]
        observed_window_ms = (index + 1 - start) * sample_interval_ms
        rates[index] = count * 1_000.0 / observed_window_ms
    return rates


def _adaptive_candidate_bank(
    size: int,
    seed: int,
    *,
    membrane_taus_ms: tuple[float, ...],
    rheobase_range_pa: tuple[float, float],
    refractory_range_ms: tuple[float, float],
    adaptation_tau_range_ms: tuple[float, float],
    adaptation_increment_range: tuple[float, float],
) -> dict[str, np.ndarray]:
    if size < 24:
        raise ConfigurationError("Adaptive LIF candidate bank must contain at least 24 models")
    generator = np.random.default_rng(seed)
    membrane_taus = np.asarray(membrane_taus_ms, dtype=np.float64)
    bank = {
        "rheobase_pa": generator.uniform(*rheobase_range_pa, size),
        "membrane_tau_ms": generator.choice(membrane_taus, size=size),
        "refractory_ms": generator.uniform(*refractory_range_ms, size),
        "adaptation_tau_ms": np.exp(
            generator.uniform(
                math.log(adaptation_tau_range_ms[0]),
                math.log(adaptation_tau_range_ms[1]),
                size,
            )
        ),
        "adaptation_increment": generator.uniform(*adaptation_increment_range, size),
    }
    # Preserve an explicit no-adaptation comparison inside the same candidate bank.
    bank["adaptation_increment"][: len(membrane_taus)] = 0.0
    bank["membrane_tau_ms"][: len(membrane_taus)] = membrane_taus
    return bank


def _simulate_adaptive_bank(
    current_pa: np.ndarray,
    bank: dict[str, np.ndarray],
    indices: np.ndarray,
    *,
    integration_step_us: int,
    sample_interval_ms: float,
    rate_window_ms: float,
    initial_voltage_phases: tuple[float, ...],
) -> np.ndarray:
    """Vectorized candidate simulation used only for bounded model fitting."""
    rheobase = bank["rheobase_pa"][indices]
    membrane_tau = bank["membrane_tau_ms"][indices]
    refractory = bank["refractory_ms"][indices]
    adaptation_tau = bank["adaptation_tau_ms"][indices]
    adaptation_increment = bank["adaptation_increment"][indices]
    if integration_step_us <= 0:
        raise ConfigurationError("Candidate integration step must be positive")
    dt_ms = integration_step_us / 1_000.0
    steps_per_sample_float = sample_interval_ms / dt_ms
    if not steps_per_sample_float.is_integer():
        raise ConfigurationError("Candidate integration step must divide sample interval exactly")
    steps_per_sample = int(steps_per_sample_float)

    trial_count = len(initial_voltage_phases)
    if trial_count < 1:
        raise ConfigurationError("At least one observation-model trial phase is required")
    v = np.broadcast_to(
        np.asarray(initial_voltage_phases, dtype=np.float64),
        (len(indices), trial_count),
    ).copy()
    adaptation = np.zeros((len(indices), trial_count), dtype=np.float64)
    refractory_remaining = np.zeros((len(indices), trial_count), dtype=np.float64)
    spike_bins = np.zeros((len(indices), len(current_pa)), dtype=np.int16)
    for sample_index, injected_current in enumerate(current_pa):
        counts = np.zeros((len(indices), trial_count), dtype=np.int16)
        for _ in range(steps_per_sample):
            adaptation += -adaptation * dt_ms / adaptation_tau[:, None]
            available = refractory_remaining <= 0.0
            refractory_remaining = np.maximum(0.0, refractory_remaining - dt_ms)
            v[available] += (
                -v[available]
                + np.broadcast_to(injected_current / rheobase[:, None], v.shape)[available]
                - adaptation[available]
            ) * dt_ms / np.broadcast_to(membrane_tau[:, None], v.shape)[available]
            spiking = available & (v >= 1.0)
            counts[spiking] += 1
            v[spiking] = 0.0
            adaptation[spiking] += np.broadcast_to(
                adaptation_increment[:, None], v.shape
            )[spiking]
            refractory_remaining[spiking] = np.broadcast_to(
                refractory[:, None], v.shape
            )[spiking]
        spike_bins[:, sample_index] = np.sum(counts, axis=1)
    window_samples_float = rate_window_ms / sample_interval_ms
    if not window_samples_float.is_integer():
        raise ConfigurationError("Rate window must contain an integer number of source samples")
    window_samples = int(window_samples_float)
    cumulative = np.pad(np.cumsum(spike_bins, axis=1, dtype=np.int64), ((0, 0), (1, 0)))
    rates = np.empty_like(spike_bins, dtype=np.float64)
    for sample_index in range(len(current_pa)):
        start = max(0, sample_index + 1 - window_samples)
        counts = cumulative[:, sample_index + 1] - cumulative[:, start]
        observed_window_ms = (sample_index + 1 - start) * sample_interval_ms
        rates[:, sample_index] = counts * 1_000.0 / (observed_window_ms * trial_count)
    return rates


def fit_dynamic_projection_neuron_model(
    experiment_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Fit and freeze the ramp-aware PN family without opening the external trace."""
    experiment = Stage2ExperimentSpec.load(experiment_path)
    readiness = experiment.readiness(root)
    if not readiness["fit_ready"]:
        raise DatasetError(f"Stage 2 dynamic fit contract is not ready: {readiness['blockers']}")
    if any(not specimen.startswith("gugel-dl5-fi-") for specimen in experiment.fit_specimen_ids):
        raise ConfigurationError("Dynamic PN fit accepts only registered Gugel F-I training cells")
    if any(not specimen.startswith("nanami-") for specimen in experiment.held_out_specimen_ids):
        raise ConfigurationError("Dynamic PN fit requires the reserved Nanami external challenge")

    raw_experiment = load_json(experiment_path)
    target = raw_experiment["target"]
    parameter_policy = raw_experiment["parameter_policy"]
    protocol = target["gugel_protocol"]
    bank_size = int(target["candidate_bank_size"])
    bank_seed = int(target["candidate_bank_seed"])
    rerank_count = int(target["final_rerank_count"])
    search_step_us = int(target["candidate_search_step_us"])
    final_step_us = int(target["integration_step_us"])
    sample_interval_ms = float(protocol["sample_interval_ms"])
    rate_window_ms = float(protocol["rate_window_ms"])
    initial_voltage_phases = tuple(
        float(value) for value in parameter_policy["trial_initial_voltage_phases"]
    )

    table = pq.read_table(
        root
        / "derived"
        / "auxiliary"
        / "gugel-2023-elife-85443"
        / "figure7"
        / "dl5-fi-curves.parquet"
    )
    current_pa, fit_curves = _group_curves(
        table, experiment.fit_specimen_ids, "current_pa", "firing_rate_hz"
    )
    bank = _adaptive_candidate_bank(
        bank_size,
        bank_seed,
        membrane_taus_ms=tuple(
            float(value) for value in parameter_policy["membrane_tau_ms"]
        ),
        rheobase_range_pa=tuple(parameter_policy["rheobase_pa_range"]),
        refractory_range_ms=tuple(parameter_policy["refractory_ms_range"]),
        adaptation_tau_range_ms=tuple(parameter_policy["adaptation_tau_ms_range"]),
        adaptation_increment_range=tuple(parameter_policy["adaptation_increment_range"]),
    )
    all_indices = np.arange(bank_size)
    search_rates = _simulate_adaptive_bank(
        current_pa,
        bank,
        all_indices,
        integration_step_us=search_step_us,
        sample_interval_ms=sample_interval_ms,
        rate_window_ms=rate_window_ms,
        initial_voltage_phases=initial_voltage_phases,
    )
    search_losses_by_cell = np.mean(
        np.where(
            np.abs(search_rates[:, None, :] - fit_curves[None, :, :]) <= 5.0,
            0.5 * (search_rates[:, None, :] - fit_curves[None, :, :]) ** 2,
            5.0 * (np.abs(search_rates[:, None, :] - fit_curves[None, :, :]) - 2.5),
        ),
        axis=2,
    )
    rerank_indices = np.unique(
        np.concatenate(
            [
                np.argsort(search_losses_by_cell[:, cell_index])[:rerank_count]
                for cell_index in range(fit_curves.shape[0])
            ]
        )
    )
    final_rates = _simulate_adaptive_bank(
        current_pa,
        bank,
        rerank_indices,
        integration_step_us=final_step_us,
        sample_interval_ms=sample_interval_ms,
        rate_window_ms=rate_window_ms,
        initial_voltage_phases=initial_voltage_phases,
    )
    final_losses_by_cell = np.mean(
        np.where(
            np.abs(final_rates[:, None, :] - fit_curves[None, :, :]) <= 5.0,
            0.5 * (final_rates[:, None, :] - fit_curves[None, :, :]) ** 2,
            5.0 * (np.abs(final_rates[:, None, :] - fit_curves[None, :, :]) - 2.5),
        ),
        axis=2,
    )
    selected_positions = np.argmin(final_losses_by_cell, axis=0)
    selected_indices = [int(rerank_indices[position]) for position in selected_positions]
    parameter_draws = [
        {
            "fit_specimen_id": specimen_id,
            "candidate_index": selected_index,
            "parameters": {
                key: float(values[selected_index]) for key, values in bank.items()
            },
        }
        for specimen_id, selected_index in zip(
            experiment.fit_specimen_ids, selected_indices, strict=True
        )
    ]
    selected_predictions = np.stack(
        [final_rates[position] for position in selected_positions]
    )
    selected_losses = np.asarray(
        [
            final_losses_by_cell[position, cell_index]
            for cell_index, position in enumerate(selected_positions)
        ]
    )

    steady_parameters = {"rheobase_pa": 31.0, "membrane_tau_ms": 30.6, "refractory_ms": 24.0}
    steady_prediction = lif_steady_state_rate_hz(current_pa, **steady_parameters)
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-projection-neuron-dynamic-fit-v5",
        "experiment_id": experiment.experiment_id,
        "experiment_sha256": experiment.sha256,
        "provenance": "P/F/E",
        "fit_specimen_ids": list(experiment.fit_specimen_ids),
        "reserved_external_specimen_ids": list(experiment.held_out_specimen_ids),
        "external_trace_opened": False,
        "frozen_before_external_evaluation": True,
        "family": "ramp-aware dimensionless adaptive LIF",
        "protocol": {
            "current_ramp_pa_per_s": float(protocol["ramp_rate_pa_per_s"]),
            "sample_interval_ms": sample_interval_ms,
            "rate_window_ms": rate_window_ms,
            "rate_window_overlap_ms": float(protocol["rate_window_overlap_ms"]),
            "trial_average_count": len(initial_voltage_phases),
            "trial_initial_voltage_phases": list(initial_voltage_phases),
            "trial_count_inference": (
                "F/E inference from 6.6667 Hz source quantization under the published 50 ms window"
            ),
            "candidate_search_step_us": search_step_us,
            "final_integration_step_us": final_step_us,
        },
        "candidate_bank": {
            "size": bank_size,
            "seed": bank_seed,
            "final_rerank_count": len(rerank_indices),
            "selected_indices": selected_indices,
        },
        "parameter_distribution": {
            "kind": "empirical per-training-cell draws",
            "draw_count": len(parameter_draws),
            "draws": parameter_draws,
        },
        "training": {
            "per_cell_huber_hz2": [float(value) for value in selected_losses],
            "huber_hz2": float(np.mean(selected_losses)),
            "rmse_hz": _rmse(fit_curves, selected_predictions),
            "steady_state_lif_rmse_hz": _rmse(fit_curves, steady_prediction[None, :]),
            "dynamic_improves_training_rmse": _rmse(fit_curves, selected_predictions)
            < _rmse(fit_curves, steady_prediction[None, :]),
        },
        "acceptance": {
            "all_states_finite": bool(np.all(np.isfinite(selected_predictions))),
            "dynamic_improves_training_rmse": _rmse(fit_curves, selected_predictions)
            < _rmse(fit_curves, steady_prediction[None, :]),
            "external_evaluation_pending": True,
            "validation_tier_awarded": None,
        },
        "claim_boundary": experiment.claim_boundary,
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


def evaluate_dynamic_projection_neuron_holdout(
    evaluation_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Evaluate a frozen dynamic PN distribution on previously excluded recorded cells."""
    evaluation = load_json(evaluation_path)
    if evaluation.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported dynamic PN holdout schema")
    parse_provenance(str(evaluation["provenance"]))
    frozen_spec = evaluation["frozen_fit"]
    fit_path = root / str(frozen_spec["path"])
    expected_fit_sha256 = str(frozen_spec["sha256"])
    observed_fit_sha256 = sha256_file(fit_path) if fit_path.is_file() else None
    if observed_fit_sha256 != expected_fit_sha256:
        raise DatasetError(
            "Frozen dynamic PN fit SHA-256 mismatch: "
            f"expected {expected_fit_sha256}, observed {observed_fit_sha256}"
        )
    fit = load_json(fit_path)
    if fit.get("frozen_before_external_evaluation") is not True:
        raise DatasetError("Dynamic PN holdout evaluation requires a pre-frozen fit")
    if fit.get("experiment_sha256") != frozen_spec["experiment_sha256"]:
        raise DatasetError("Frozen dynamic PN fit experiment identity mismatch")

    artifact_spec = evaluation["required_artifact"]
    artifact_path = root / str(artifact_spec["path"])
    observed_artifact_sha256 = sha256_file(artifact_path) if artifact_path.is_file() else None
    if observed_artifact_sha256 != artifact_spec["sha256"]:
        raise DatasetError(
            "Dynamic PN holdout artifact SHA-256 mismatch: "
            f"expected {artifact_spec['sha256']}, observed {observed_artifact_sha256}"
        )

    # Numeric held-out responses are opened only after both immutable identities pass.
    table = pq.read_table(artifact_path)
    training_ids = tuple(str(value) for value in evaluation["training_specimen_ids"])
    held_out_ids = tuple(str(value) for value in evaluation["held_out_specimen_ids"])
    if not training_ids or not held_out_ids or set(training_ids) & set(held_out_ids):
        raise ConfigurationError("Dynamic PN holdout cell sets must be nonempty and disjoint")
    current_pa, training_curves = _group_curves(
        table, training_ids, "current_pa", "firing_rate_hz"
    )
    held_current_pa, held_out_curves = _group_curves(
        table, held_out_ids, "current_pa", "firing_rate_hz"
    )
    if not np.array_equal(current_pa, held_current_pa):
        raise DatasetError("Dynamic PN training and held-out current grids differ")

    draws = fit["parameter_distribution"]["draws"]
    bank: dict[str, np.ndarray] = {
        key: np.asarray(
            [float(draw["parameters"][key]) for draw in draws], dtype=np.float64
        )
        for key in (
            "rheobase_pa",
            "membrane_tau_ms",
            "refractory_ms",
            "adaptation_tau_ms",
            "adaptation_increment",
        )
    }
    protocol = fit["protocol"]
    model_curves = _simulate_adaptive_bank(
        current_pa,
        bank,
        np.arange(len(draws)),
        integration_step_us=int(protocol["final_integration_step_us"]),
        sample_interval_ms=float(protocol["sample_interval_ms"]),
        rate_window_ms=float(protocol["rate_window_ms"]),
        initial_voltage_phases=tuple(
            float(value) for value in protocol["trial_initial_voltage_phases"]
        ),
    )
    model_mean = np.mean(model_curves, axis=0)
    biological_mean = np.mean(training_curves, axis=0)
    model_rmse = _rmse(held_out_curves, model_mean[None, :])
    biological_rmse = _rmse(held_out_curves, biological_mean[None, :])
    normalized_ratio = model_rmse / biological_rmse

    active_ramp = current_pa > 0.0

    def response_features(curve: np.ndarray) -> dict[str, float | None]:
        active_indices = np.flatnonzero(active_ramp & (curve > 0.0))
        onset = float(current_pa[int(active_indices[0])]) if len(active_indices) else None
        return {
            "response_onset_current_pa": onset,
            "peak_firing_rate_hz": float(np.max(curve[active_ramp])),
        }

    model_features = response_features(model_mean)
    held_out_response_features = [response_features(curve) for curve in held_out_curves]
    held_out_features = [
        {"specimen_id": specimen_id, **features}
        for specimen_id, features in zip(
            held_out_ids, held_out_response_features, strict=True
        )
    ]
    model_onset = model_features["response_onset_current_pa"]
    onset_errors: list[float | None] = []
    for features in held_out_response_features:
        observed_onset = features["response_onset_current_pa"]
        onset_errors.append(
            None
            if model_onset is None or observed_onset is None
            else model_onset - observed_onset
        )
    model_peak = model_features["peak_firing_rate_hz"]
    if model_peak is None:
        raise DatasetError("Dynamic PN model peak feature is unexpectedly missing")
    peak_errors = []
    for features in held_out_response_features:
        observed_peak = features["peak_firing_rate_hz"]
        if observed_peak is None:
            raise DatasetError("Dynamic PN held-out peak feature is unexpectedly missing")
        peak_errors.append(model_peak - observed_peak)
    ratio_limit = float(evaluation["acceptance"]["normalized_error_ratio_max"])
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-pn-dynamic-chronic-condition-holdout-v1",
        "evaluation_id": str(evaluation["evaluation_id"]),
        "evaluation_sha256": sha256_json(evaluation),
        "frozen_fit_path": str(fit_path),
        "frozen_fit_sha256": observed_fit_sha256,
        "held_out_opened_after_identity_checks": True,
        "training_specimen_ids": list(training_ids),
        "held_out_specimen_ids": list(held_out_ids),
        "metrics": {
            "model_to_heldout_rmse_hz": model_rmse,
            "training_cohort_to_heldout_rmse_hz": biological_rmse,
            "normalized_error_ratio": normalized_ratio,
            "per_cell_rmse_hz": [
                _rmse(curve, model_mean) for curve in held_out_curves
            ],
            "model_features": model_features,
            "held_out_features": held_out_features,
            "response_onset_current_errors_pa": onset_errors,
            "peak_firing_rate_errors_hz": peak_errors,
        },
        "acceptance": {
            "normalized_error_ratio_limit": ratio_limit,
            "normalized_error_ratio_pass": normalized_ratio <= ratio_limit,
            "all_predictions_finite": bool(np.all(np.isfinite(model_curves))),
            "cellular_fi_subgate_pass": normalized_ratio <= ratio_limit
            and bool(np.all(np.isfinite(model_curves))),
        },
        "tier_policy": evaluation["acceptance"]["tier_policy"],
        "claim_boundary": str(evaluation["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


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


def _epsc_features(time_ms: np.ndarray, trace_pa: np.ndarray) -> dict[str, float]:
    baseline = float(np.mean(trace_pa[time_ms < 40.0]))
    inward = baseline - trace_pa
    peak_index = int(np.argmax(inward))
    peak = float(inward[peak_index])
    peak_time = float(time_ms[peak_index])
    target = peak / math.e
    after_peak = np.flatnonzero(
        (np.arange(len(time_ms)) > peak_index) & (inward <= target)
    )
    decay_ms = (
        float(time_ms[int(after_peak[0])] - peak_time) if len(after_peak) else math.nan
    )
    return {
        "baseline_pa": baseline,
        "peak_inward_amplitude_pa": peak,
        "peak_time_ms": peak_time,
        "peak_to_one_over_e_ms": decay_ms,
    }


def review_projection_neuron_fit(
    fit_result_path: Path,
    root: Path,
    output: Path,
    *,
    expected_fit_sha256: str,
) -> dict[str, Any]:
    """Audit frozen held-out features without changing or refitting any parameter."""
    observed_sha256 = sha256_file(fit_result_path)
    if observed_sha256 != expected_fit_sha256:
        raise DatasetError(
            f"Frozen Stage 2 fit SHA-256 mismatch: expected {expected_fit_sha256}, "
            f"observed {observed_sha256}"
        )
    fit_result = load_json(fit_result_path)
    if fit_result.get("frozen_before_held_out_evaluation") is not True:
        raise DatasetError("Stage 2 review requires a frozen fit result")
    epsc_parameters = fit_result["uepsc_model"]["parameters"]
    held_out_ids = tuple(
        str(value)
        for value in fit_result["held_out_specimen_ids"]
        if "-uepsc-" in str(value)
    )
    table = pq.read_table(
        root
        / "derived"
        / "auxiliary"
        / "gugel-2023-elife-85443"
        / "figure7"
        / "dl5-uepsc-traces.parquet"
    )
    time_ms, held_out_curves = _group_curves(table, held_out_ids, "time_ms", "current_pa")
    observed_features: list[dict[str, Any]] = [
        {"specimen_id": specimen_id, **_epsc_features(time_ms, curve)}
        for specimen_id, curve in zip(held_out_ids, held_out_curves, strict=True)
    ]

    elapsed = np.maximum(0.0, time_ms - float(epsc_parameters["onset_ms"]))
    kernel = np.exp(-elapsed / float(epsc_parameters["decay_tau_ms"])) - np.exp(
        -elapsed / float(epsc_parameters["rise_tau_ms"])
    )
    kernel[time_ms < float(epsc_parameters["onset_ms"])] = 0.0
    kernel /= np.max(kernel)
    model_trace = -float(epsc_parameters["population_amplitude_pa"]) * kernel
    model_features = _epsc_features(time_ms, model_trace)

    def errors(key: str) -> list[float]:
        return [
            float(model_features[key] - float(specimen[key])) for specimen in observed_features
        ]

    review: dict[str, Any] = {
        "schema_version": "1.0",
        "review_id": "stage2-projection-neuron-frozen-feature-review-v1",
        "frozen_fit_path": str(fit_result_path),
        "frozen_fit_sha256": observed_sha256,
        "parameters_changed": False,
        "held_out_specimen_ids": list(held_out_ids),
        "model_features": model_features,
        "held_out_features": observed_features,
        "feature_errors": {
            "peak_amplitude_error_pa": errors("peak_inward_amplitude_pa"),
            "peak_time_error_ms": errors("peak_time_ms"),
            "peak_to_one_over_e_error_ms": errors("peak_to_one_over_e_ms"),
        },
        "interpretation": (
            "Descriptive post-freeze feature audit. The experiment registered these feature "
            "categories, but no numeric feature thresholds were preregistered."
        ),
        "v2_coverage": {
            "sign": "covered for the registered inward-current waveforms",
            "unitary_amplitude": "covered for three held-out recordings",
            "kinetics": "covered for three held-out recordings",
            "failure_probability": "missing",
            "short_term_plasticity": "missing",
        },
        "validation_tier_awarded": None,
        "tier_blockers": [
            "No preregistered feature-level acceptance thresholds",
            "No held-out release-failure distribution",
            "No held-out short-term-plasticity protocol",
            "Cross-specimen female DL5 evidence is not MaleCNS DM1/DM4 physiology",
        ],
    }
    review["logical_sha256"] = sha256_json(review)
    _atomic_json(output, review)
    return review
