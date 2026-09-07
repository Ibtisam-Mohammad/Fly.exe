# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from flysim.shiu_reference import (
    build_shiu_figure5g_reference,
    load_or_build_shiu_figure5g_reference,
)


def test_build_shiu_reference_recovers_registered_curve(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive_path = source / "results.zip"
    rate = (
        "exp_name,720575940630907434\nname,\n"
        "JON_F_100Hz,1.0\nJON_F_20Hz,1.0\n"
    )
    std = (
        "exp_name,720575940630907434\nname,\n"
        "JON_F_100Hz,0.0\nJON_F_20Hz,0.0\n"
    )
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("results/figure_5/data/fig_5g_JON_F_rate.csv", rate)
        archive.writestr("results/figure_5/data/fig_5g_JON_F_std.csv", std)
        for frequency in (20, 100):
            buffer = BytesIO()
            pq.write_table(
                pa.table(
                    {
                        "trial": list(range(30)),
                        "flywire_id": [720575940630907434] * 30,
                    }
                ),
                buffer,
            )
            archive.writestr(
                f"results/figure_5/data/JON_F_{frequency}Hz.parquet",
                buffer.getvalue(),
            )
    card = {
        "source_archive": "doi:test",
        "archive_dataset_version": "1.0",
        "artifacts": [
            {
                "filename": "results.zip",
                "bytes": archive_path.stat().st_size,
                "md5": hashlib.md5(archive_path.read_bytes(), usedforsecurity=False).hexdigest(),
                "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            }
        ],
    }
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    output = tmp_path / "reference.json"

    result = build_shiu_figure5g_reference(
        source_root=source,
        dataset_card_path=card_path,
        output_path=output,
    )

    assert result["status"] == "raw-output-analysis-reproduced"
    assert result["curve"][0] == {
        "frequency_hz": 20.0,
        "mean_rate_hz": 1.0,
        "std_rate_hz": 0.0,
    }
    assert result["validation_tier_awarded"] is None


def test_load_reference_reuses_cache_only_for_read_only_registered_archive(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    archive_path = source / "results.zip"
    frequencies = tuple(range(20, 221, 20))
    rate_rows = "\n".join(f"JON_F_{frequency}Hz,1.0" for frequency in frequencies)
    std_rows = "\n".join(f"JON_F_{frequency}Hz,0.0" for frequency in frequencies)
    rate = f"exp_name,720575940630907434\nname,\n{rate_rows}\n"
    std = f"exp_name,720575940630907434\nname,\n{std_rows}\n"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("results/figure_5/data/fig_5g_JON_F_rate.csv", rate)
        archive.writestr("results/figure_5/data/fig_5g_JON_F_std.csv", std)
        for frequency in frequencies:
            buffer = BytesIO()
            pq.write_table(
                pa.table(
                    {
                        "trial": list(range(30)),
                        "flywire_id": [720575940630907434] * 30,
                    }
                ),
                buffer,
            )
            archive.writestr(
                f"results/figure_5/data/JON_F_{frequency}Hz.parquet",
                buffer.getvalue(),
            )
    archive_bytes = archive_path.read_bytes()
    card = {
        "source_archive": "doi:test",
        "archive_dataset_version": "1.0",
        "artifacts": [
            {
                "filename": "results.zip",
                "bytes": len(archive_bytes),
                "md5": hashlib.md5(
                    archive_bytes, usedforsecurity=False
                ).hexdigest(),
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            }
        ]
    }
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps(card), encoding="utf-8")
    output = tmp_path / "reference.json"
    first = build_shiu_figure5g_reference(
        source_root=source,
        dataset_card_path=card_path,
        output_path=output,
    )
    archive_path.chmod(0o444)

    cached = load_or_build_shiu_figure5g_reference(
        source_root=source,
        dataset_card_path=card_path,
        output_path=output,
    )

    assert cached["cache_reused"] is True
    assert cached["sha256"] == first["sha256"]
