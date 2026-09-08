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

from flysim.cellular import (
    STIMULUS_IRRECOVERABLE,
    STIMULUS_RESOLVED,
    SpikeDetectionPolicy,
    StepAnalysisPolicy,
    StepDiagnosticsPolicy,
    current_step_features,
    stimulus_free_features,
    summarise_current_step_protocol,
)
from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError, DatasetError
from flysim.provenance import parse_provenance
from flysim.synaptic import epsc_waveform_features, fit_difference_of_exponentials_kernel

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



# Constants read from plot_wave_PN in 02_plot_figs/analyze_PQNtest.ipynb at the pinned commit.
# t0 = t_cross - 0.03 - w + 0.25 with w = 0.0235, and extraction keeps samples after t0 - 0.5.
_NANAMI_PN_ALIGNMENT_WIDTH_S = 0.0235
_NANAMI_PN_EXTRACTION_OFFSET_MS = round(
    (0.5 - (-0.03 - _NANAMI_PN_ALIGNMENT_WIDTH_S + 0.25)) * -1_000.0, 4
)

INVIVO_PACK_CONFIG_ID = "nanami-2024-invivo-cellular-pack-v1"


def _numeric_column(path: Path, *, has_header: bool, scale: float) -> np.ndarray:
    """Read a one-value-per-line trace losslessly, rejecting any nonnumeric row."""
    lines = path.read_text(encoding="ascii").strip().split("\n")
    if has_header:
        header = lines[0].strip()
        if not header or header.replace(".", "").replace("-", "").isdigit():
            raise DatasetError(f"Expected a recording-identifier header line in {path.name}")
        lines = lines[1:]
    values = np.empty(len(lines), dtype=np.float64)
    for index, line in enumerate(lines):
        try:
            values[index] = float(line.strip())
        except ValueError as exc:
            raise DatasetError(
                f"Non-numeric sample at line {index + 1 + int(has_header)} of {path.name}"
            ) from exc
    if not np.all(np.isfinite(values)):
        raise DatasetError(f"Nonfinite membrane sample in {path.name}")
    return values * scale


def _matrix_csv(path: Path) -> np.ndarray:
    rows = [
        [float(cell) for cell in line.split(",")]
        for line in path.read_text(encoding="ascii").strip().split("\n")
    ]
    widths = {len(row) for row in rows}
    if len(widths) != 1:
        raise DatasetError(f"Ragged matrix CSV: {path.name}")
    matrix = np.asarray(rows, dtype=np.float64)
    if not np.all(np.isfinite(matrix)):
        raise DatasetError(f"Nonfinite value in {path.name}")
    return matrix


def import_invivo_cellular_pack(
    config_path: Path,
    source: Path,
    output_directory: Path,
) -> dict[str, Any]:
    """Normalize the locked in vivo cellular pack without deriving any observable.

    The pack is deliberately imported as four separate artifacts rather than one pooled
    table, because only the MBON-alpha1 protocol publishes its injected current. Pooling
    would make it possible to write a query that silently treats a stimulus-free trace as
    if its current were known.
    """
    config = load_json(config_path)
    if config.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported in vivo cellular pack config schema")
    if config.get("dataset_id") != INVIVO_PACK_CONFIG_ID:
        raise ConfigurationError("Config does not describe the registered in vivo cellular pack")
    expected_commit = str(config["source_commit"])
    head, dirty = _git_identity(source)
    if head != expected_commit:
        raise DatasetError(
            f"In vivo pack commit mismatch: expected {expected_commit}, observed {head}"
        )
    if dirty:
        raise DatasetError("In vivo pack checkout has local changes; refusing an unlocked import")

    artifacts = list(config["artifacts"])
    verified: list[dict[str, Any]] = []
    for artifact in artifacts:
        path = source / str(artifact["path"])
        if not path.is_file():
            raise DatasetError(f"Locked in vivo artifact is missing: {artifact['path']}")
        observed = sha256_file(path)
        if observed != str(artifact["sha256"]):
            raise DatasetError(
                f"In vivo artifact SHA-256 mismatch for {artifact['path']}: "
                f"expected {artifact['sha256']}, observed {observed}"
            )
        if path.stat().st_size != int(artifact["bytes"]):
            raise DatasetError(f"In vivo artifact size mismatch for {artifact['path']}")
        verified.append({"path": str(artifact["path"]), "sha256": observed})

    sample_interval_us = int(1_000_000 / int(config["sampling_rate_hz"]))
    output_directory.mkdir(parents=True, exist_ok=True)
    normalized: list[dict[str, Any]] = []

    current = _matrix_csv(source / "invivo_results/MBON/MBONa1_step_I.csv")
    voltage = _matrix_csv(source / "invivo_results/MBON/MBONa1_step_V.csv")
    time_base = _matrix_csv(source / "invivo_results/MBON/MBONa1_step_t.csv")
    if current.shape != voltage.shape:
        raise DatasetError("MBON injected-current and voltage matrices have different shapes")
    if time_base.shape != (1, current.shape[1]):
        raise DatasetError("MBON time base does not span one sweep")
    observed_interval_us = round(float(time_base[0, 1] - time_base[0, 0]) * 1_000_000)
    if observed_interval_us != sample_interval_us:
        raise DatasetError(
            f"MBON time base implies {observed_interval_us} us per sample, "
            f"registered rate implies {sample_interval_us} us"
        )
    sweeps, samples = current.shape
    mbon_path = output_directory / "mbon-alpha1-current-steps.parquet"
    _write_parquet_atomic(
        pa.table(
            {
                "sweep_index": pa.array(
                    np.repeat(np.arange(sweeps, dtype=np.uint8), samples), type=pa.uint8()
                ),
                "t_us": pa.array(
                    np.tile(
                        np.round(time_base[0] * 1_000_000).astype(np.uint64), sweeps
                    ),
                    type=pa.uint64(),
                ),
                "injected_current_pa": pa.array(current.reshape(-1), type=pa.float64()),
                "membrane_voltage_mv": pa.array(voltage.reshape(-1), type=pa.float64()),
            }
        ),
        mbon_path,
    )
    normalized.append(
        {
            "path": mbon_path.name,
            "cell_class": "MBON-alpha1",
            "specimen_ids": ["nanami-mbon-a1-step"],
            "sweeps": int(sweeps),
            "rows": int(sweeps * samples),
            "sha256": sha256_file(mbon_path),
            "stimulus_resolution": STIMULUS_RESOLVED,
            "units": {
                "t_us": "us",
                "injected_current_pa": "pA",
                "membrane_voltage_mv": "mV",
            },
        }
    )

    ln_artifacts = sorted(
        (item for item in artifacts if item["cell_class"] == "antennal-lobe local neuron"),
        key=lambda item: (str(item["specimen_id"]), int(item["trial_index"])),
    )
    specimen_ids: list[str] = []
    trial_indices: list[int] = []
    timestamps: list[np.ndarray] = []
    voltages: list[np.ndarray] = []
    for artifact in ln_artifacts:
        # The redistributed LN files store volts and carry a recording-identifier header.
        trace = _numeric_column(
            source / str(artifact["path"]), has_header=True, scale=1_000.0
        )
        specimen_ids.extend([str(artifact["specimen_id"])] * trace.size)
        trial_indices.extend([int(artifact["trial_index"])] * trace.size)
        timestamps.append(np.arange(trace.size, dtype=np.uint64) * sample_interval_us)
        voltages.append(trace)
    ln_path = output_directory / "ln-voltage-traces.parquet"
    _write_parquet_atomic(
        pa.table(
            {
                "specimen_id": pa.array(specimen_ids, type=pa.string()),
                "trial_index": pa.array(trial_indices, type=pa.uint8()),
                "t_us": pa.array(np.concatenate(timestamps), type=pa.uint64()),
                "membrane_voltage_mv": pa.array(np.concatenate(voltages), type=pa.float64()),
            }
        ),
        ln_path,
    )
    normalized.append(
        {
            "path": ln_path.name,
            "cell_class": "antennal-lobe local neuron",
            "specimen_ids": sorted({str(item["specimen_id"]) for item in ln_artifacts}),
            "trials": len(ln_artifacts),
            "rows": int(sum(trace.size for trace in voltages)),
            "sha256": sha256_file(ln_path),
            "stimulus_resolution": STIMULUS_IRRECOVERABLE,
            "units": {"t_us": "us", "membrane_voltage_mv": "mV"},
            "originating_study": config["originating_studies"]["antennal-lobe local neuron"],
        }
    )

    kc_trace = _numeric_column(
        source / "invivo_results/KC/KC_181016_4_00_v.txt", has_header=False, scale=1.0
    )
    kc_path = output_directory / "kc-voltage-trace.parquet"
    _write_parquet_atomic(
        pa.table(
            {
                "t_us": pa.array(
                    np.arange(kc_trace.size, dtype=np.uint64) * sample_interval_us,
                    type=pa.uint64(),
                ),
                "membrane_voltage_mv": pa.array(kc_trace, type=pa.float64()),
            }
        ),
        kc_path,
    )
    normalized.append(
        {
            "path": kc_path.name,
            "cell_class": "Kenyon cell",
            "specimen_ids": ["inada-kc-181016-4-00"],
            "rows": int(kc_trace.size),
            "sha256": sha256_file(kc_path),
            "stimulus_resolution": STIMULUS_IRRECOVERABLE,
            "units": {"t_us": "us", "membrane_voltage_mv": "mV"},
            "originating_study": config["originating_studies"]["Kenyon cell"],
        }
    )

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "nanami-2024-invivo-cellular-pack-v1",
        "source_repository": str(config["source_repository"]),
        "source_commit": head,
        "paper": str(config["paper"]),
        "provenance": "M/P/I",
        "assumption_ids": ["ND-01", "ND-02", "ND-05"],
        "sample_interval_us": sample_interval_us,
        "verified_source_artifacts": verified,
        "verified_source_artifact_count": len(verified),
        "normalized_artifacts": normalized,
        "originating_studies": dict(config["originating_studies"]),
        "stimulus_resolution": dict(config["stimulus_resolution"]),
        "mbon_alpha1_protocol": {
            "status": "resolved from the paper Methods and reproduced by the published "
            "injected-current file",
            "quotation": "The I-V relationship was measured before pairing by injecting 1-s "
            "square pulses with incrementing amplitudes (0-10 pA, 2 pA steps).",
            "observed_amplitudes_pa": sorted(
                float(value) for value in np.unique(current[current != 0.0])
            ),
            "observed_step_duration_ms": float(
                np.count_nonzero(current[0] != 0.0) * sample_interval_us / 1_000.0
            ),
            "low_pass_filter_hz": 5_000,
            "digitisation_hz": int(config["sampling_rate_hz"]),
        },
        "pn_protocol_correction": {
            "supersedes": "nanami-2024-pn-current-clamp-trace-v1 protocol_reconstruction",
            "superseded_manifest_left_unchanged": True,
            "defects": [
                {
                    "field": "step_levels",
                    "withdrawn_value": [3, 4, 5, 6, 7, 8, 9, 10],
                    "finding": "those integers are the list I4 in 02_plot_figs/"
                    "analyze_PQNtest.ipynb, which sets the stimulus amplitudes of the "
                    "in-silico PQN model, not of the in vivo recording",
                    "authors_statement": "All variables and parameters are purely abstract "
                    "with no physical units.",
                },
                {
                    "field": "step_level_units",
                    "withdrawn_value": "unresolved source-code units; do not assume pA",
                    "finding": "the question is not open: the model amplitudes are "
                    "dimensionless by the authors own statement, and the in vivo amplitudes "
                    "are never published, so they are irrecoverable rather than unresolved",
                    "authors_statement": "Multiple levels of depolarizing currents were "
                    "injected into the soma of individual PNs.",
                },
                {
                    "field": "extraction_start_relative_to_first_crossing_ms",
                    "withdrawn_value": -306.5,
                    "corrected_value": _NANAMI_PN_EXTRACTION_OFFSET_MS,
                    "finding": "plot_wave_PN sets t0 = t_cross - 0.03 - w + 0.25 with "
                    "w = 0.0235 and then keeps samples after t0 - 0.5",
                },
                {
                    "field": "window_count_and_spacing",
                    "withdrawn_value": "eight 1 s windows every 2 s",
                    "corrected_value": "three 1 s display windows at 4 s spacing",
                    "finding": "plot_wave_PN shifts the extracted trace by "
                    "-4*(k+1)+2 seconds for k in 0..2 against a 0-1 s axis; the eight came "
                    "from the eight in-silico levels, not from the recording",
                },
            ],
            "stimulus_amplitudes": "irrecoverable",
            "consequence": "the PN trace can never support a current-referenced F-I "
            "comparison; only current-independent observables are scorable against it",
        },
        "claim_boundary": str(config["forbidden_claim"]),
        "validation_tier_awarded": None,
    }
    manifest["logical_sha256"] = sha256_json(manifest)
    _atomic_json(output_directory / "manifest.json", manifest)
    return manifest




def _class_signalling_evidence(
    unit_resolved: dict[str, Any], stimulus_free: dict[str, Any]
) -> dict[str, Any]:
    """Per-class somatic spike amplitude, and what it does and does not establish.

    A small somatic spike is exactly what a spiking neuron produces when the spike is
    initiated in the axon and attenuates on the way to the soma, which is the published
    conclusion for Drosophila projection neurons. Somatic amplitude therefore constrains
    the observation model, and cannot on its own classify a cell type as graded.
    """
    classes: list[dict[str, Any]] = []
    lowest = min(unit_resolved["by_prominence_mv"], key=lambda key: float(key))
    mbon_sweeps = unit_resolved["by_prominence_mv"][lowest]["per_sweep"]
    mbon_spiking = [item for item in mbon_sweeps if int(item["spike_count"]) > 0]
    classes.append(
        {
            "cell_class": "MBON-alpha1",
            "animal_count": 1,
            "detection_prominence_mv": float(lowest),
            "somatic_spike_amplitude_mv": None,
            "spikes_detected": bool(mbon_spiking),
            "overshoots_zero_mv": False,
            "note": "amplitude is reported per sweep in the unit-resolved block",
        }
    )
    for relative, block in stimulus_free.items():
        name = relative.rsplit("/", 1)[-1]
        if "per_animal" in block:
            amplitudes = [
                float(item["somatic_spike_amplitude_mv"])
                for item in block["per_animal"]
                if item["somatic_spike_amplitude_mv"] is not None
            ]
            overshooting = sum(int(item["overshooting_trials"]) for item in block["per_animal"])
            trials = sum(int(item["trial_count"]) for item in block["per_animal"])
            classes.append(
                {
                    "cell_class": "antennal-lobe local neuron",
                    "artifact": name,
                    "animal_count": int(block["animal_count"]),
                    "somatic_spike_amplitude_mv": (
                        float(np.median(amplitudes)) if amplitudes else None
                    ),
                    "overshooting_trials": overshooting,
                    "trial_count": trials,
                    "overshoots_zero_mv": overshooting > 0,
                }
            )
            continue
        detected = {
            prominence: record
            for prominence, record in block["by_prominence_mv"].items()
            if record["somatic_spike_amplitude_mv"] is not None
        }
        smallest = (
            min(detected, key=lambda key: float(key)) if detected else None
        )
        classes.append(
            {
                "cell_class": (
                    "Kenyon cell"
                    if name.startswith("kc")
                    else "olfactory projection neuron"
                ),
                "artifact": name,
                "animal_count": int(block["animal_count"]),
                "lowest_prominence_with_detections_mv": (
                    float(smallest) if smallest is not None else None
                ),
                "somatic_spike_amplitude_mv": (
                    float(detected[smallest]["somatic_spike_amplitude_mv"])
                    if smallest is not None
                    else None
                ),
                "median_spike_peak_mv": (
                    detected[smallest]["median_spike_peak_mv"] if smallest is not None else None
                ),
                "overshoots_zero_mv": (
                    detected[smallest]["overshoots_zero_mv"] if smallest is not None else None
                ),
            }
        )
    return {
        "per_class": classes,
        "finding": "Somatic spike amplitude differs several-fold across these four classes, "
        "so no single absolute spike threshold serves all of them.",
        "does_not_establish": "A small somatic spike does not classify a cell as graded. "
        "Axonal spike initiation followed by passive attenuation to the soma produces the "
        "same measurement, and that is the published conclusion for Drosophila projection "
        "neurons in the source already pinned as the project passive prior.",
        "registry_consequence": "This evidence constrains the observation model and the "
        "per-type threshold, and is not sufficient to move any cell type out of the "
        "unresolved signal regime.",
    }


def _sealed_pn_challenge_feasibility(stimulus_free: dict[str, Any]) -> dict[str, Any]:
    """Whether the reserved external PN trace can still be scored against a frozen model."""
    relative = next(key for key in stimulus_free if key.endswith("pn-voltage-trace.parquet"))
    block = stimulus_free[relative]["by_prominence_mv"]
    counts = {
        prominence: int(record["spike_count"]) for prominence, record in block.items()
    }
    detected = {
        prominence: record
        for prominence, record in block.items()
        if int(record["spike_count"]) > 0
    }
    return {
        "spike_count_by_prominence_mv": counts,
        "feasible": False,
        "blocking_reasons": [
            "the in vivo stimulus amplitudes are irrecoverable, so no current-referenced "
            "observable can be compared",
            "somatic spikes in this trace do not reach the primary 10 mV prominence, so the "
            "spike count depends on the detector setting rather than on the recording",
            "at the lowest tested prominence the whole 20 s trace yields "
            + str(min(counts.values(), default=0))
            + " to "
            + str(max(counts.values(), default=0))
            + " spikes, which is too few for a per-epoch adaptation statistic",
        ],
        "detected_at_prominence_mv": sorted(float(key) for key in detected),
        "consequence": "The reserved Nanami PN trace is retired as a scoring source. It "
        "remains locked as a resting-potential and somatic-amplitude reference.",
    }


def _pack_table(root: Path, relative: str, expected_sha256: str) -> pa.Table:
    path = root / relative
    observed = sha256_file(path) if path.is_file() else None
    if observed != expected_sha256:
        raise DatasetError(
            f"Cellular-observable artifact SHA-256 mismatch for {relative}: "
            f"expected {expected_sha256}, observed {observed}"
        )
    return pq.read_table(path)


def measure_invivo_cellular_pack(
    contract_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Measure V1 observables under a preregistered contract, tagged by stimulus resolution.

    Every unit-bearing observable is refused for a source whose stimulus amplitudes were
    never published. That refusal is the point of the function: it is what stops an
    irrecoverable protocol from being laundered into a membrane time constant.
    """
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported cellular-observable contract schema")
    parse_provenance(str(contract["provenance"]))
    sample_interval_us = int(contract["sample_interval_us"])
    detection = contract["spike_detection"]
    primary_policy = SpikeDetectionPolicy.from_mapping(detection["primary"])
    step_policy = StepAnalysisPolicy.from_mapping(contract["step_analysis"])
    # Diagnostics are opt-in per contract so a contract written before they existed keeps
    # reproducing the artifact it produced.
    diagnostics = (
        StepDiagnosticsPolicy.from_mapping(contract["review_diagnostics"])
        if contract.get("review_diagnostics") is not None
        else None
    )
    prominences = [primary_policy.prominence_mv] + [
        float(value) for value in detection["sensitivity_prominence_mv"]
    ]

    required = {str(item["path"]): item for item in contract["required_artifacts"]}
    resolutions = {
        str(item["path"]): str(item["stimulus_resolution"])
        for item in contract["required_artifacts"]
    }
    tables = {
        relative: _pack_table(root, relative, str(item["sha256"]))
        for relative, item in required.items()
    }

    def policy_at(prominence_mv: float) -> SpikeDetectionPolicy:
        return SpikeDetectionPolicy(
            prominence_mv=prominence_mv,
            prominence_window_ms=primary_policy.prominence_window_ms,
            refractory_ms=primary_policy.refractory_ms,
            resting_mask_ms=primary_policy.resting_mask_ms,
        )

    mbon_relative = next(key for key in tables if "mbon-alpha1" in key)
    mbon = tables[mbon_relative].to_pydict()
    sweep_index = np.asarray(mbon["sweep_index"], dtype=np.int64)
    sweeps = int(sweep_index.max()) + 1
    current = np.stack(
        [np.asarray(mbon["injected_current_pa"], dtype=np.float64)[sweep_index == k]
         for k in range(sweeps)]
    )
    voltage = np.stack(
        [np.asarray(mbon["membrane_voltage_mv"], dtype=np.float64)[sweep_index == k]
         for k in range(sweeps)]
    )
    if resolutions[mbon_relative] != STIMULUS_RESOLVED:
        raise ConfigurationError("The MBON protocol must be registered as unit-resolved")
    mbon_by_prominence: dict[str, Any] = {}
    for prominence in prominences:
        features = current_step_features(
            current,
            voltage,
            sample_interval_us=sample_interval_us,
            spike_policy=policy_at(prominence),
            step_policy=step_policy,
            upstroke_criterion_mv_per_ms=float(
                contract["step_analysis"]["upstroke_criterion_mv_per_ms"]
            ),
            threshold_search_window_ms=float(
                contract["step_analysis"]["threshold_search_window_ms"]
            ),
            diagnostics=diagnostics,
        )
        mbon_by_prominence[f"{prominence:g}"] = {
            "per_sweep": features,
            "summary": summarise_current_step_protocol(features),
        }

    stimulus_free: dict[str, Any] = {}
    for relative, table in tables.items():
        if relative == mbon_relative:
            continue
        if resolutions[relative] != STIMULUS_IRRECOVERABLE:
            raise ConfigurationError(
                f"{relative} is registered as unit-resolved but carries no injected current"
            )
        payload = table.to_pydict()
        voltages = np.asarray(payload["membrane_voltage_mv"], dtype=np.float64)
        if "specimen_id" in payload:
            specimens = np.asarray(payload["specimen_id"], dtype=object)
            trials = np.asarray(payload["trial_index"], dtype=np.int64)
            per_trial: list[dict[str, Any]] = []
            for specimen in sorted(set(specimens.tolist())):
                for trial in sorted(set(trials[specimens == specimen].tolist())):
                    selection = (specimens == specimen) & (trials == trial)
                    record = stimulus_free_features(
                        voltages[selection],
                        sample_interval_us=sample_interval_us,
                        spike_policy=primary_policy,
                        report_pre_spike_baseline=diagnostics is not None,
                    )
                    per_trial.append(
                        {"specimen_id": specimen, "trial_index": int(trial), **record}
                    )
            per_animal = []
            for specimen in sorted({item["specimen_id"] for item in per_trial}):
                rows = [item for item in per_trial if item["specimen_id"] == specimen]
                amplitudes = [
                    float(item["somatic_spike_amplitude_mv"])
                    for item in rows
                    if item["somatic_spike_amplitude_mv"] is not None
                ]
                animal: dict[str, Any] = {
                    "specimen_id": specimen,
                    "trial_count": len(rows),
                    "resting_potential_mv": float(
                        np.median([float(item["resting_potential_mv"]) for item in rows])
                    ),
                    "somatic_spike_amplitude_mv": (
                        float(np.median(amplitudes)) if amplitudes else None
                    ),
                    "overshooting_trials": sum(
                        1 for item in rows if item["overshoots_zero_mv"] is True
                    ),
                }
                if diagnostics is not None:
                    pre_spike = [
                        float(item["pre_first_spike_resting_potential_mv"])
                        for item in rows
                        if item.get("pre_first_spike_resting_potential_mv") is not None
                    ]
                    animal["pre_first_spike_resting_potential_mv"] = (
                        float(np.median(pre_spike)) if pre_spike else None
                    )
                    animal["pre_first_spike_duration_range_ms"] = [
                        float(min(item["pre_first_spike_duration_ms"] for item in rows)),
                        float(max(item["pre_first_spike_duration_ms"] for item in rows)),
                    ]
                per_animal.append(animal)
            resting = [item["resting_potential_mv"] for item in per_animal]
            block: dict[str, Any] = {
                "stimulus_resolution": STIMULUS_IRRECOVERABLE,
                "animal_count": len(per_animal),
                "per_trial": per_trial,
                "per_animal": per_animal,
                "resting_potential_across_animals_mv": {
                    "median": float(np.median(resting)),
                    "minimum": float(min(resting)),
                    "maximum": float(max(resting)),
                },
            }
            if diagnostics is not None:
                pre_spike_resting = [
                    float(item["pre_first_spike_resting_potential_mv"])
                    for item in per_animal
                    if item.get("pre_first_spike_resting_potential_mv") is not None
                ]
                block["pre_first_spike_resting_potential_across_animals_mv"] = (
                    {
                        "median": float(np.median(pre_spike_resting)),
                        "minimum": float(min(pre_spike_resting)),
                        "maximum": float(max(pre_spike_resting)),
                        "definition": (
                            "median voltage before the first detected spike of each trial, "
                            "so before any unpublished stimulus epoch and its "
                            "after-hyperpolarization"
                        ),
                    }
                    if pre_spike_resting
                    else None
                )
            stimulus_free[relative] = block
        else:
            by_prominence = {
                f"{prominence:g}": stimulus_free_features(
                    voltages,
                    sample_interval_us=sample_interval_us,
                    spike_policy=policy_at(prominence),
                    report_pre_spike_baseline=diagnostics is not None,
                )
                for prominence in prominences
            }
            stimulus_free[relative] = {
                "stimulus_resolution": STIMULUS_IRRECOVERABLE,
                "animal_count": 1,
                "by_prominence_mv": by_prominence,
            }

    primary = mbon_by_prominence[f"{primary_policy.prominence_mv:g}"]["summary"]
    measured_values = [
        primary["resting_potential_mv"],
        primary["membrane_tau_ms"],
        primary["input_resistance_mohm"],
    ]
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": str(contract["experiment_id"]),
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "sample_interval_us": sample_interval_us,
        "spike_detection_primary": primary_policy.as_dict(),
        "spike_detection_sensitivity_prominence_mv": prominences[1:],
        "step_analysis": step_policy.as_dict(),
        "unit_resolved": {
            "cell_class": "MBON-alpha1",
            "relative_path": mbon_relative,
            "by_prominence_mv": mbon_by_prominence,
        },
        "stimulus_free": stimulus_free,
        "signalling_evidence": _class_signalling_evidence(
            {"by_prominence_mv": mbon_by_prominence}, stimulus_free
        ),
        "sealed_pn_challenge": _sealed_pn_challenge_feasibility(stimulus_free),
        "v1_coverage": {
            "resting_voltage": "measured for four classes; a multi-animal distribution exists "
            "only for the four-animal antennal-lobe LN set",
            "membrane_time_constant": "measured for one MBON-alpha1 cell only; no registered "
            "source publishes a unit-resolved current step for any projection-neuron type",
            "input_resistance": "measured for one MBON-alpha1 cell only",
            "adaptation": "measured wherever at least four interspike intervals occur",
            "projection_neuron_coverage": "none of the three V1 observables is available as a "
            "multi-animal, type-resolved projection-neuron distribution",
        },
        "artifact_validity": {
            "all_required_artifacts_match_sha256": True,
            "all_measured_values_finite": all(
                value is None or math.isfinite(float(value)) for value in measured_values
            ),
            "unit_bearing_observables_only_from_unit_resolved_sources": True,
        },
        "tier_policy": str(contract["tier_policy"]),
        "declared_blockers": [str(value) for value in contract["declared_blockers"]],
        "claim_boundary": str(contract["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    if diagnostics is not None:
        result["review_diagnostics"] = diagnostics.as_dict()
        result["disclosure"] = str(contract.get("disclosure", ""))
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


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
    initial_voltage_matrix: np.ndarray | None = None,
    initial_adaptation_matrix: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorized candidate simulation used only for bounded model fitting.

    ``initial_voltage_matrix`` and ``initial_adaptation_matrix`` give each candidate its own
    per-trial starting state, which is how the VAL-01 ensemble varies seeds without adding a
    noise process the source data cannot constrain. Omitting both reproduces the shared-phase
    behaviour exactly, so every earlier frozen result is unchanged.
    """
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
    if initial_voltage_matrix is None:
        v = np.broadcast_to(
            np.asarray(initial_voltage_phases, dtype=np.float64),
            (len(indices), trial_count),
        ).copy()
    else:
        v = np.asarray(initial_voltage_matrix, dtype=np.float64).copy()
        if v.shape != (len(indices), trial_count):
            raise ConfigurationError(
                "Initial voltage matrix must be one row per candidate and one column per trial"
            )
    if initial_adaptation_matrix is None:
        adaptation = np.zeros((len(indices), trial_count), dtype=np.float64)
    else:
        adaptation = np.asarray(initial_adaptation_matrix, dtype=np.float64).copy()
        if adaptation.shape != (len(indices), trial_count):
            raise ConfigurationError(
                "Initial adaptation matrix must be one row per candidate and one column per trial"
            )
        if np.any(adaptation < 0.0):
            raise ConfigurationError("Initial adaptation states cannot be negative")
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

    training_ids = tuple(str(value) for value in evaluation["training_specimen_ids"])
    held_out_ids = tuple(str(value) for value in evaluation["held_out_specimen_ids"])
    if not training_ids or not held_out_ids or set(training_ids) & set(held_out_ids):
        raise ConfigurationError("Dynamic PN holdout cell sets must be nonempty and disjoint")
    metrics, all_predictions_finite = _dynamic_holdout_metrics(
        fit,
        artifact_path,
        training_ids,
        held_out_ids,
        integration_step_us=int(fit["protocol"]["final_integration_step_us"]),
    )
    ratio_limit = float(evaluation["acceptance"]["normalized_error_ratio_max"])
    normalized_ratio = float(metrics["normalized_error_ratio"])
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
        "metrics": metrics,
        "acceptance": {
            "normalized_error_ratio_limit": ratio_limit,
            "normalized_error_ratio_pass": normalized_ratio <= ratio_limit,
            "all_predictions_finite": all_predictions_finite,
            "cellular_fi_subgate_pass": normalized_ratio <= ratio_limit
            and all_predictions_finite,
        },
        "tier_policy": evaluation["acceptance"]["tier_policy"],
        "claim_boundary": str(evaluation["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


def review_dynamic_projection_neuron_timestep(
    review_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Review the frozen dynamic-PN holdout conclusion at a smaller timestep."""
    review = load_json(review_path)
    if review.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported dynamic PN timestep review schema")
    parse_provenance(str(review["provenance"]))

    result_spec = review["frozen_holdout_result"]
    result_path = root / str(result_spec["path"])
    observed_result_sha256 = sha256_file(result_path) if result_path.is_file() else None
    if observed_result_sha256 != result_spec["sha256"]:
        raise DatasetError(
            "Frozen dynamic PN holdout result SHA-256 mismatch: "
            f"expected {result_spec['sha256']}, observed {observed_result_sha256}"
        )
    frozen_result = load_json(result_path)
    if frozen_result.get("validation_tier_awarded") is not None:
        raise DatasetError("Dynamic PN timestep review cannot extend a tier-bearing result")

    fit_path = Path(str(frozen_result["frozen_fit_path"]))
    if not fit_path.is_absolute():
        fit_path = root / fit_path
    observed_fit_sha256 = sha256_file(fit_path) if fit_path.is_file() else None
    if observed_fit_sha256 != frozen_result["frozen_fit_sha256"]:
        raise DatasetError("Frozen dynamic PN fit changed after held-out evaluation")
    fit = load_json(fit_path)
    reference_step_us = int(review["reference_integration_step_us"])
    if int(fit["protocol"]["final_integration_step_us"]) != reference_step_us:
        raise DatasetError("Dynamic PN reference integration step does not match frozen fit")

    artifact_spec = review["required_artifact"]
    artifact_path = root / str(artifact_spec["path"])
    observed_artifact_sha256 = sha256_file(artifact_path) if artifact_path.is_file() else None
    if observed_artifact_sha256 != artifact_spec["sha256"]:
        raise DatasetError("Dynamic PN timestep source artifact SHA-256 mismatch")

    sensitivity_step_us = int(review["sensitivity_integration_step_us"])
    if sensitivity_step_us <= 0 or sensitivity_step_us >= reference_step_us:
        raise ConfigurationError("Sensitivity timestep must be positive and below the reference")
    training_ids = tuple(str(value) for value in frozen_result["training_specimen_ids"])
    held_out_ids = tuple(str(value) for value in frozen_result["held_out_specimen_ids"])
    sensitivity_metrics, sensitivity_finite = _dynamic_holdout_metrics(
        fit,
        artifact_path,
        training_ids,
        held_out_ids,
        integration_step_us=sensitivity_step_us,
    )

    ratio_limit = float(frozen_result["acceptance"]["normalized_error_ratio_limit"])
    reference_ratio = float(frozen_result["metrics"]["normalized_error_ratio"])
    sensitivity_ratio = float(sensitivity_metrics["normalized_error_ratio"])
    reference_pass = bool(frozen_result["acceptance"]["cellular_fi_subgate_pass"])
    sensitivity_pass = sensitivity_ratio <= ratio_limit and sensitivity_finite
    conclusion_preserved = reference_pass == sensitivity_pass
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "review_id": str(review["review_id"]),
        "review_sha256": sha256_json(review),
        "frozen_holdout_result_path": str(result_path),
        "frozen_holdout_result_sha256": observed_result_sha256,
        "frozen_fit_sha256": observed_fit_sha256,
        "parameters_changed": False,
        "reference": {
            "integration_step_us": reference_step_us,
            "normalized_error_ratio": reference_ratio,
            "cellular_fi_subgate_pass": reference_pass,
        },
        "sensitivity": {
            "integration_step_us": sensitivity_step_us,
            "metrics": sensitivity_metrics,
            "all_predictions_finite": sensitivity_finite,
            "cellular_fi_subgate_pass": sensitivity_pass,
        },
        "acceptance": {
            "same_subgate_conclusion": conclusion_preserved,
            "all_sensitivity_predictions_finite": sensitivity_finite,
            "numerical_sensitivity_pass": conclusion_preserved and sensitivity_finite,
        },
        "tier_policy": str(review["tier_policy"]),
        "claim_boundary": str(review["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


def _dynamic_holdout_metrics(
    fit: dict[str, Any],
    artifact_path: Path,
    training_ids: tuple[str, ...],
    held_out_ids: tuple[str, ...],
    *,
    integration_step_us: int,
) -> tuple[dict[str, Any], bool]:
    table = pq.read_table(artifact_path)
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
        integration_step_us=integration_step_us,
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
    model_onset = model_features["response_onset_current_pa"]
    onset_errors = [
        None
        if model_onset is None or features["response_onset_current_pa"] is None
        else model_onset - features["response_onset_current_pa"]
        for features in held_out_response_features
    ]
    model_peak = model_features["peak_firing_rate_hz"]
    peak_errors = [
        None
        if model_peak is None or features["peak_firing_rate_hz"] is None
        else model_peak - features["peak_firing_rate_hz"]
        for features in held_out_response_features
    ]
    return (
        {
            "model_to_heldout_rmse_hz": model_rmse,
            "training_cohort_to_heldout_rmse_hz": biological_rmse,
            "normalized_error_ratio": model_rmse / biological_rmse,
            "per_cell_rmse_hz": [_rmse(curve, model_mean) for curve in held_out_curves],
            "model_features": model_features,
            "held_out_features": [
                {"specimen_id": specimen_id, **features}
                for specimen_id, features in zip(
                    held_out_ids, held_out_response_features, strict=True
                )
            ],
            "response_onset_current_errors_pa": onset_errors,
            "peak_firing_rate_errors_hz": peak_errors,
        },
        bool(np.all(np.isfinite(model_curves))),
    )


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
    """The frozen Stage 2 kernel fit; the grid now lives in ``flysim.synaptic`` unchanged."""
    return fit_difference_of_exponentials_kernel(time_ms, fit_curves)


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



def _repository_root() -> Path:
    """Project root, resolved from this module rather than from a caller-supplied path."""
    return Path(__file__).resolve().parents[2]


def _guard_consumed_cells(
    requested: tuple[str, ...], forbidden: frozenset[str]
) -> tuple[str, ...]:
    """Refuse to read a recorded cell that an earlier evaluation has already consumed."""
    overlap = sorted(forbidden.intersection(requested))
    if overlap:
        raise DatasetError(
            f"Refusing to read already consumed recorded cells: {overlap}"
        )
    return requested


def build_projection_neuron_ensemble(
    experiment_path: Path,
    root: Path,
    output: Path,
) -> dict[str, Any]:
    """Widen the frozen PN family into a VAL-01 uncertainty ensemble, and score nothing.

    VAL-01 asks for five parameter samples by four seeds. The frozen family had two
    per-cell draws and a deterministic integrator, so it met neither half. The parameter
    samples come from rejection sampling over the candidates the two training cells cannot
    distinguish, and the seeds vary the unobserved membrane and adaptation state at protocol
    onset rather than injecting a noise process the data cannot constrain.

    Every registered F-I recording has already been consumed, so this function deliberately
    reads no held-out cell and produces no score.
    """
    contract = load_json(experiment_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported PN ensemble contract schema")
    parse_provenance(str(contract["provenance"]))

    frozen_spec = contract["frozen_fit"]
    fit_path = root / str(frozen_spec["path"])
    observed_fit_sha256 = sha256_file(fit_path) if fit_path.is_file() else None
    if observed_fit_sha256 != str(frozen_spec["sha256"]):
        raise DatasetError(
            "Frozen PN fit SHA-256 mismatch: "
            f"expected {frozen_spec['sha256']}, observed {observed_fit_sha256}"
        )
    fit = load_json(fit_path)
    if fit.get("frozen_before_external_evaluation") is not True:
        raise DatasetError("The PN ensemble must be built from a pre-frozen fit")

    artifact_spec = contract["required_artifact"]
    artifact_path = root / str(artifact_spec["path"])
    observed_artifact_sha256 = sha256_file(artifact_path) if artifact_path.is_file() else None
    if observed_artifact_sha256 != str(artifact_spec["sha256"]):
        raise DatasetError(
            "PN ensemble source artifact SHA-256 mismatch: "
            f"expected {artifact_spec['sha256']}, observed {observed_artifact_sha256}"
        )

    training_ids = tuple(str(value) for value in contract["training_specimen_ids"])
    forbidden_ids = frozenset(str(value) for value in contract["forbidden_specimen_ids"])
    if set(training_ids) & forbidden_ids:
        raise ConfigurationError("A training cell is also listed as consumed")
    if set(training_ids) != set(fit["fit_specimen_ids"]):
        raise ConfigurationError(
            "The ensemble must use exactly the training cells the frozen fit used"
        )

    settings = contract["ensemble"]
    sample_count = int(settings["parameter_samples"])
    seed_count = int(settings["seeds_per_condition"])
    tolerance = float(settings["acceptance_tolerance_ratio"])
    if sample_count < 5 or seed_count < 4:
        raise ConfigurationError(
            "VAL-01 requires at least five parameter samples and four seeds per condition"
        )
    if tolerance <= 1.0:
        raise ConfigurationError("Acceptance tolerance must exceed the best achievable loss")

    protocol = fit["protocol"]
    final_step_us = int(protocol["final_integration_step_us"])
    sample_interval_ms = float(protocol["sample_interval_ms"])
    rate_window_ms = float(protocol["rate_window_ms"])
    bank_settings = fit["candidate_bank"]

    policy_source = contract["parameter_policy_source"]
    policy_path = _repository_root() / str(policy_source["path"])
    if not policy_path.is_file():
        raise ConfigurationError(
            f"The ensemble contract names a missing parameter-policy source: {policy_path}"
        )
    parameter_policy = load_json(policy_path)["parameter_policy"]
    bank = _adaptive_candidate_bank(
        int(bank_settings["size"]),
        int(bank_settings["seed"]),
        membrane_taus_ms=tuple(float(value) for value in parameter_policy["membrane_tau_ms"]),
        rheobase_range_pa=tuple(parameter_policy["rheobase_pa_range"]),
        refractory_range_ms=tuple(parameter_policy["refractory_ms_range"]),
        adaptation_tau_range_ms=tuple(parameter_policy["adaptation_tau_ms_range"]),
        adaptation_increment_range=tuple(parameter_policy["adaptation_increment_range"]),
    )
    if not bank_settings["selected_indices"]:
        raise DatasetError("The frozen fit records no selected candidate")

    # The artifact legitimately contains the consumed cells, so the guard has to sit at the
    # point of reading rather than on the file.
    table = pq.read_table(artifact_path)
    requested = _guard_consumed_cells(training_ids, forbidden_ids)
    current_pa, training_curves = _group_curves(
        table, requested, "current_pa", "firing_rate_hz"
    )

    # Re-score the whole candidate bank against the training cells so acceptance is defined
    # over every candidate, not only the two the frozen fit happened to select.
    initial_phases = tuple(float(value) for value in protocol["trial_initial_voltage_phases"])
    all_indices = np.arange(int(bank_settings["size"]))
    rates = _simulate_adaptive_bank(
        current_pa,
        bank,
        all_indices,
        integration_step_us=final_step_us,
        sample_interval_ms=sample_interval_ms,
        rate_window_ms=rate_window_ms,
        initial_voltage_phases=initial_phases,
    )
    residual = rates[:, None, :] - training_curves[None, :, :]
    losses = np.mean(
        np.where(
            np.abs(residual) <= 5.0, 0.5 * residual**2, 5.0 * (np.abs(residual) - 2.5)
        ),
        axis=2,
    )
    best_per_cell = np.min(losses, axis=0)
    accepted = np.flatnonzero(np.any(losses <= best_per_cell[None, :] * tolerance, axis=1))
    if accepted.size < sample_count:
        raise DatasetError(
            f"Rejection sampling accepted only {accepted.size} candidates, fewer than the "
            f"{sample_count} parameter samples VAL-01 requires"
        )
    generator = np.random.default_rng(int(settings["sample_seed"]))
    selected = np.sort(generator.choice(accepted, size=sample_count, replace=False))

    condition = settings["initial_condition_distribution"]
    phase_low = float(condition["voltage_phase"]["low"])
    phase_high = float(condition["voltage_phase"]["high"])
    adaptation_low = float(condition["adaptation_state"]["low"])
    adaptation_high = float(condition["adaptation_state"]["high"])
    seed_generator = np.random.default_rng(int(settings["sample_seed"]) + 1)
    initial_voltages = seed_generator.uniform(phase_low, phase_high, (sample_count, seed_count))
    initial_adaptation = seed_generator.uniform(
        adaptation_low, adaptation_high, (sample_count, seed_count)
    )
    member_rates = _simulate_adaptive_bank(
        current_pa,
        bank,
        selected,
        integration_step_us=final_step_us,
        sample_interval_ms=sample_interval_ms,
        rate_window_ms=rate_window_ms,
        initial_voltage_phases=tuple(float(value) for value in initial_voltages[0]),
        initial_voltage_matrix=initial_voltages,
        initial_adaptation_matrix=initial_adaptation,
    )
    ensemble_mean = np.mean(member_rates, axis=0)
    spread_low = np.percentile(member_rates, 5.0, axis=0)
    spread_high = np.percentile(member_rates, 95.0, axis=0)
    inside = np.mean(
        (training_curves >= spread_low[None, :]) & (training_curves <= spread_high[None, :])
    )

    members = [
        {
            "sample_index": index,
            "candidate_index": int(candidate),
            "parameters": {key: float(values[candidate]) for key, values in bank.items()},
            "initial_voltage_phases": [float(value) for value in initial_voltages[index]],
            "initial_adaptation_states": [float(value) for value in initial_adaptation[index]],
        }
        for index, candidate in enumerate(selected)
    ]
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": "stage2-pn-uncertainty-ensemble-v1",
        "experiment_id": str(contract["experiment_id"]),
        "experiment_sha256": sha256_json(contract),
        "provenance": str(contract["provenance"]),
        "frozen_fit_path": str(fit_path),
        "frozen_fit_sha256": observed_fit_sha256,
        "parameters_refitted": False,
        "training_specimen_ids": list(training_ids),
        "specimen_ids_read": list(requested),
        "consumed_cell_guard": (
            "every recorded-cell identifier passed to the reader is checked against the "
            "consumed list before the read, and a match raises"
        ),
        "forbidden_specimen_ids": sorted(forbidden_ids),
        "candidate_bank_size": int(bank_settings["size"]),
        "accepted_candidate_count": int(accepted.size),
        "acceptance_tolerance_ratio": tolerance,
        "ensemble": {
            "parameter_samples": sample_count,
            "seeds_per_condition": seed_count,
            "member_count": sample_count * seed_count,
            "members": members,
        },
        "parameter_uncertainty": {
            "described_over": "every candidate the training cells cannot distinguish",
            "accepted_ranges": {
                key: {
                    "minimum": float(np.min(values[accepted])),
                    "median": float(np.median(values[accepted])),
                    "maximum": float(np.max(values[accepted])),
                    "max_to_min_ratio": (
                        float(np.max(values[accepted]) / np.min(values[accepted]))
                        if float(np.min(values[accepted])) > 0.0
                        else None
                    ),
                }
                for key, values in bank.items()
            },
            "finding": (
                "A 25 percent loss tolerance admits candidates spanning several-fold ranges "
                "in rheobase and adaptation. The two training cells do not constrain this "
                "family tightly, and the previously reported 7.630 Hz training RMSE is a "
                "property of scoring each per-cell best fit on the cell that selected it."
            ),
        },
        "training_diagnostics": {
            "ensemble_mean_rmse_hz": _rmse(training_curves, ensemble_mean[None, :]),
            "frozen_two_draw_training_rmse_hz": float(fit["training"]["rmse_hz"]),
            "training_fraction_inside_5_to_95_band": float(inside),
            "band_is_not_a_gate": (
                "The training curves selected these candidates, so coverage of the band is a "
                "descriptive diagnostic and not a validation result."
            ),
        },
        "acceptance": {
            "meets_val01_parameter_samples": sample_count >= 5,
            "meets_val01_seeds_per_condition": seed_count >= 4,
            "all_predictions_finite": bool(np.all(np.isfinite(member_rates))),
            "no_forbidden_specimen_read": True,
            "held_out_evaluation_performed": False,
        },
        "tier_policy": str(contract["tier_policy"]),
        "declared_blockers": [str(value) for value in contract["declared_blockers"]],
        "claim_boundary": str(contract["claim_boundary"]),
        "validation_tier_awarded": None,
    }
    result["logical_sha256"] = sha256_json(result)
    _atomic_json(output, result)
    return result


def _epsc_features(time_ms: np.ndarray, trace_pa: np.ndarray) -> dict[str, float]:
    """Delegate to the shared definition so the frozen review and the preregistered
    held-out test cannot drift apart."""
    return epsc_waveform_features(time_ms, trace_pa)


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
