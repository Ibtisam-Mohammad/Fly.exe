# SPDX-License-Identifier: GPL-2.0-or-later
"""Loss-aware import of the published Track A grooming trajectory."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import sys
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from flysim.errors import DatasetError

OZDIL_FIG1_PANEL_C_SHA256 = (
    "89826e646018a5184f13b2ccbdcb4f7713ed26deab98f84fcddf8e237a55892e"
)

TRAJECTORY_COLUMNS = (
    "Angle_LF_ThC_yaw",
    "Angle_LF_ThC_pitch",
    "Angle_LF_ThC_roll",
    "Angle_LF_CTr_pitch",
    "Angle_LF_CTr_roll",
    "Angle_LF_FTi_pitch",
    "Angle_LF_TiTa_pitch",
    "Angle_RF_ThC_yaw",
    "Angle_RF_ThC_pitch",
    "Angle_RF_ThC_roll",
    "Angle_RF_CTr_pitch",
    "Angle_RF_CTr_roll",
    "Angle_RF_FTi_pitch",
    "Angle_RF_TiTa_pitch",
    "Angle_head_roll",
    "Angle_head_pitch",
    "Angle_head_yaw",
    "Angle_antenna_yaw_L",
    "Angle_antenna_pitch_L",
    "Angle_antenna_yaw_R",
    "Angle_antenna_pitch_R",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _first_true_block(mask: np.ndarray) -> slice:
    indices = np.flatnonzero(mask)
    if not indices.size:
        raise DatasetError("The Ozdil trajectory contains no active stimulus interval")
    breaks = np.flatnonzero(np.diff(indices) != 1)
    stop_offset = int(breaks[0] + 1) if breaks.size else int(indices.size)
    return slice(int(indices[0]), int(indices[stop_offset - 1]) + 1)


def extract_grooming_trajectory(columns: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Extract the first contiguous JO-F stimulus bout and convert degrees to radians."""
    required = {"Time", "Stimulus", *TRAJECTORY_COLUMNS}
    missing = sorted(required - columns.keys())
    if missing:
        raise DatasetError(f"Ozdil Figure 1 trajectory columns are missing: {missing}")
    time_s = np.asarray(columns["Time"], dtype=np.float64)
    stimulus = np.asarray(columns["Stimulus"], dtype=np.float64)
    if time_s.ndim != 1 or stimulus.shape != time_s.shape:
        raise DatasetError("Ozdil time and stimulus columns must be aligned vectors")
    selection = _first_true_block(stimulus > 0.5)
    selected_time = time_s[selection]
    if selected_time.size < 2 or np.any(np.diff(selected_time) <= 0):
        raise DatasetError("Ozdil stimulus timebase is too short or not strictly increasing")
    angles_deg = np.column_stack(
        [np.asarray(columns[name], dtype=np.float64)[selection] for name in TRAJECTORY_COLUMNS]
    )
    if angles_deg.shape != (selected_time.size, len(TRAJECTORY_COLUMNS)):
        raise DatasetError("Ozdil joint-angle columns are not aligned with the timebase")
    if not np.all(np.isfinite(angles_deg)):
        raise DatasetError("Ozdil grooming angles contain NaN or infinite values")
    return {
        "time_s": selected_time - selected_time[0],
        "angles_rad": np.deg2rad(angles_deg),
        "column_names": np.asarray(TRAJECTORY_COLUMNS, dtype="U40"),
    }


def _load_checksum_locked_pickle(source: Path) -> Mapping[str, Any]:
    """Load the publisher pickle only after exact identity verification.

    The official file was produced with an older pandas module path. The temporary
    alias only restores that class lookup; it does not relax the checksum gate.
    """
    if _sha256(source) != OZDIL_FIG1_PANEL_C_SHA256:
        raise DatasetError("Refusing to load an unrecognized Ozdil Figure 1 pickle")
    try:
        import pandas as pd
    except ImportError as exc:
        raise DatasetError("Importing the Ozdil trajectory requires pandas") from exc
    legacy = types.ModuleType("pandas.core.indexes.numeric")
    legacy.Int64Index = pd.Index  # type: ignore[attr-defined]
    legacy.UInt64Index = pd.Index  # type: ignore[attr-defined]
    legacy.Float64Index = pd.Index  # type: ignore[attr-defined]
    sys.modules[legacy.__name__] = legacy
    try:
        with source.open("rb") as stream:
            frame = pickle.load(stream)
    finally:
        sys.modules.pop(legacy.__name__, None)
    if not hasattr(frame, "columns"):
        raise DatasetError("Ozdil Figure 1 pickle did not contain a table")
    return {str(name): frame[name].to_numpy() for name in frame.columns}


def import_grooming_trajectory(source: Path, output: Path) -> dict[str, Any]:
    """Create a portable, immutable NPZ derivative for FlyGym replay."""
    if not source.is_file():
        raise DatasetError(f"Ozdil Figure 1 trajectory is missing: {source}")
    manifest_path = output.with_suffix(output.suffix + ".json")
    if output.exists() or manifest_path.exists():
        if not output.is_file() or not manifest_path.is_file():
            raise DatasetError(f"Incomplete grooming derivative exists: {output}")
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(raw_manifest, dict):
            raise DatasetError("Existing grooming derivative manifest is malformed")
        manifest: dict[str, Any] = raw_manifest
        if manifest.get("source_sha256") != _sha256(source):
            raise DatasetError("Existing grooming derivative has a different source")
        if manifest.get("derivative_sha256") != _sha256(output):
            raise DatasetError("Existing grooming derivative checksum changed")
        return manifest

    trajectory = extract_grooming_trajectory(_load_checksum_locked_pickle(source))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".part")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            time_s=trajectory["time_s"],
            angles_rad=trajectory["angles_rad"],
            column_names=trajectory["column_names"],
        )
    os.replace(temporary, output)
    payload = {
        "schema_version": "1.0",
        "dataset_id": "ozdil-2026-antennal-grooming-fig1-panel-c",
        "source": str(source.resolve()),
        "source_sha256": _sha256(source),
        "source_datafile_id": 10810237,
        "paper": "https://doi.org/10.1038/s41467-026-72152-x",
        "selection": "first contiguous bilateral JO-F optogenetic stimulus interval",
        "source_sample_interval_s": float(np.median(np.diff(trajectory["time_s"]))),
        "samples": int(trajectory["time_s"].size),
        "duration_s": float(trajectory["time_s"][-1]),
        "signals": trajectory["column_names"].tolist(),
        "source_units": "degrees",
        "derivative_units": "radians",
        "provenance": "P/E",
        "assumption_ids": ["DATA-03", "SENS-04", "BODY-01", "MOTOR-03"],
        "claim_boundary": (
            "Cross-animal tethered elicited kinematics used as a position-controller "
            "trajectory; not MaleCNS neural or biological muscle validation."
        ),
        "derivative": str(output.resolve()),
        "derivative_sha256": _sha256(output),
    }
    part = manifest_path.with_suffix(manifest_path.suffix + ".part")
    part.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(part, manifest_path)
    return payload


def load_grooming_trajectory(path: Path) -> dict[str, np.ndarray]:
    if not path.is_file():
        raise DatasetError(f"Grooming trajectory derivative is missing: {path}")
    with np.load(path, allow_pickle=False) as data:
        result = {name: np.array(data[name], copy=True) for name in data.files}
    if set(result) != {"time_s", "angles_rad", "column_names"}:
        raise DatasetError("Grooming trajectory derivative has an unexpected schema")
    if result["angles_rad"].shape != (
        result["time_s"].size,
        result["column_names"].size,
    ):
        raise DatasetError("Grooming trajectory derivative arrays are not aligned")
    return result
