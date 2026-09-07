# SPDX-License-Identifier: GPL-2.0-or-later
"""Checksum and recover the published Shiu Figure 5g reference curve."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import statistics
import zipfile
from pathlib import Path
from typing import Any

from flysim.config import load_json
from flysim.datasets import sha256_file
from flysim.errors import DatasetError


def _file_digests(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> tuple[str, str]:
    md5_digest = hashlib.md5(usedforsecurity=False)
    sha256_digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_bytes):
            md5_digest.update(chunk)
            sha256_digest.update(chunk)
    return md5_digest.hexdigest(), sha256_digest.hexdigest()


def _unique_member(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise DatasetError(
            f"Expected one results.zip member ending in {suffix!r}, found {len(matches)}"
        )
    return matches[0]


def _series_csv(payload: bytes, expected_prefix: str) -> tuple[list[dict[str, float]], str]:
    digest = hashlib.sha256(payload).hexdigest()
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    if len(rows) < 2 or len(rows[0]) != 2:
        raise DatasetError("Published Figure 5g CSV is not a two-column pandas Series export")
    curve: list[dict[str, float]] = []
    for row in rows[1:]:
        if len(row) != 2:
            raise DatasetError(f"Unexpected Figure 5g curve row: {row!r}")
        if not row[0].startswith(expected_prefix):
            continue
        frequency_text = row[0].removeprefix(expected_prefix).removesuffix("Hz")
        curve.append({"frequency_hz": float(frequency_text), "value": float(row[1])})
    if not curve:
        raise DatasetError("Published Figure 5g CSV contains no expected experiment rows")
    return sorted(curve, key=lambda item: item["frequency_hz"]), digest


def _raw_rate_curve(
    archive: zipfile.ZipFile,
    frequencies: list[float],
    *,
    readout_flywire_id: int,
    trials: int,
    duration_ms: float,
) -> tuple[list[dict[str, float]], list[dict[str, Any]]]:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    curve: list[dict[str, float]] = []
    members: list[dict[str, Any]] = []
    for frequency in frequencies:
        member = _unique_member(archive, f"JON_F_{int(frequency)}Hz.parquet")
        content = archive.read(member)
        table = pq.read_table(io.BytesIO(content), columns=["trial", "flywire_id"])
        selected = table.filter(pc.equal(table["flywire_id"], readout_flywire_id))
        counts = [0] * trials
        for trial in selected["trial"].to_pylist():
            trial_index = int(trial)
            if not 0 <= trial_index < trials:
                raise DatasetError(f"Raw Figure 5g trial index is out of bounds: {trial_index}")
            counts[trial_index] += 1
        scale = 1000.0 / duration_ms
        rates = [count * scale for count in counts]
        curve.append(
            {
                "frequency_hz": frequency,
                "mean_rate_hz": float(statistics.fmean(rates)),
                "std_rate_hz": float(statistics.pstdev(rates)),
            }
        )
        members.append(
            {
                "member": member,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return curve, members


def build_shiu_figure5g_reference(
    *,
    source_root: Path,
    dataset_card_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Validate results.zip and recover the author-generated mean/std rate curve."""
    card = load_json(dataset_card_path)
    registered = {str(item["filename"]): item for item in card["artifacts"]}
    archive_record = registered["results.zip"]
    archive_path = source_root / "results.zip"
    if not archive_path.is_file():
        raise DatasetError(f"Shiu result archive is not checksum-locked: {archive_path}")
    if archive_path.stat().st_size != int(archive_record["bytes"]):
        raise DatasetError("Shiu result archive byte count does not match its dataset card")
    observed_md5, observed_sha256 = _file_digests(archive_path)
    if observed_md5 != str(archive_record["md5"]):
        raise DatasetError("Shiu result archive MD5 does not match the source archive record")
    registered_sha256 = archive_record.get("sha256")
    if registered_sha256 is not None and observed_sha256 != str(registered_sha256):
        raise DatasetError("Shiu result archive SHA-256 does not match its dataset card")

    with zipfile.ZipFile(archive_path) as archive:
        rate_member = _unique_member(archive, "fig_5g_JON_F_rate.csv")
        std_member = _unique_member(archive, "fig_5g_JON_F_std.csv")
        rate_curve, rate_sha256 = _series_csv(archive.read(rate_member), "JON_F_")
        std_curve, std_sha256 = _series_csv(archive.read(std_member), "JON_F_")
    if [item["frequency_hz"] for item in rate_curve] != [
        item["frequency_hz"] for item in std_curve
    ]:
        raise DatasetError("Published Figure 5g rate and standard-deviation axes differ")
    derived_curve = [
        {
            "frequency_hz": rate["frequency_hz"],
            "mean_rate_hz": rate["value"],
            "std_rate_hz": std["value"],
        }
        for rate, std in zip(rate_curve, std_curve, strict=True)
    ]
    with zipfile.ZipFile(archive_path) as archive:
        curve, raw_members = _raw_rate_curve(
            archive,
            [item["frequency_hz"] for item in derived_curve],
            readout_flywire_id=720575940630907434,
            trials=30,
            duration_ms=1000.0,
        )
    for raw, derived in zip(curve, derived_curve, strict=True):
        if (
            abs(raw["mean_rate_hz"] - derived["mean_rate_hz"]) > 1e-12
            or abs(raw["std_rate_hz"] - derived["std_rate_hz"]) > 1e-12
        ):
            raise DatasetError(
                f"Raw and author-derived Figure 5g rates differ at {raw['frequency_hz']} Hz"
            )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": "shiu-figure-5g-jon-f-abn1",
        "status": "raw-output-analysis-reproduced",
        "source_archive": card["source_archive"],
        "source_archive_version": card["archive_dataset_version"],
        "source_archive_path": str(archive_path.resolve()),
        "source_archive_bytes": archive_path.stat().st_size,
        "source_archive_md5": observed_md5,
        "source_archive_sha256": observed_sha256,
        "rate_member": rate_member,
        "rate_member_sha256": rate_sha256,
        "std_member": std_member,
        "std_member_sha256": std_sha256,
        "raw_members": raw_members,
        "readout_flywire_id": 720575940630907434,
        "trials": 30,
        "duration_ms": 1000.0,
        "curve": curve,
        "reproduction_boundary": (
            "The rate and population standard deviation were recomputed from all 11 raw JON-F "
            "Parquet outputs and matched the author-derived CSVs exactly. This reproduces the "
            "archived output analysis; it does not rerun all 330 whole-brain Brian2 trials or "
            "provide biological validation."
        ),
        "validation_tier_awarded": None,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)
    return {**payload, "output": str(output_path.resolve()), "sha256": sha256_file(output_path)}
