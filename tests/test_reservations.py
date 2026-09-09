# SPDX-License-Identifier: GPL-2.0-or-later
"""The reservation machinery, and the guarantee that reading structure cannot read a value.

The MAT reader is the load-bearing part: if it could decode a payload it would be capable
of spending a holdout by accident. These tests build MAT version 5 containers by hand,
both uncompressed and deflated, and check that the reader returns names and shapes and
nothing else. They also check the two declaration guards, because a reservation that
silently loses a variable to a rename is worse than no reservation at all.
"""

import json
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any

import pytest

from flysim.errors import ConfigurationError
from flysim.reservations import (
    build_reservation_manifest,
    describe_csv,
    describe_xlsx,
    describe_zip,
    read_mat_structure,
)

REPO = Path(__file__).resolve().parents[1]
CONTRACT = REPO / "configs" / "datasets" / "stage2-reservations-v1.json"

_MI_INT8 = 1
_MI_INT32 = 5
_MI_UINT32 = 6
_MI_DOUBLE = 9
_MI_MATRIX = 14
_MI_COMPRESSED = 15
_MX_DOUBLE = 6


def _pad(blob: bytes) -> bytes:
    return blob + b"\x00" * (-len(blob) % 8)


def _element(element_type: int, data: bytes) -> bytes:
    return struct.pack("<II", element_type, len(data)) + _pad(data)


def _matrix(name: str, dimensions: tuple[int, ...], values: list[float]) -> bytes:
    body = (
        _element(_MI_UINT32, struct.pack("<II", _MX_DOUBLE, 0))
        + _element(_MI_INT32, struct.pack(f"<{len(dimensions)}i", *dimensions))
        + _element(_MI_INT8, name.encode("ascii"))
        + _element(_MI_DOUBLE, struct.pack(f"<{len(values)}d", *values))
    )
    return _element(_MI_MATRIX, body)


def _mat_file(elements: list[bytes]) -> bytes:
    header = b"MATLAB 5.0 MAT-file, hand-built fixture".ljust(124, b" ")
    # Bytes 124 to 126 are the version and 126 to 128 the endian indicator, which is the
    # literal text "IM" for a little-endian file rather than a packed integer.
    header += struct.pack("<H", 0x0100) + b"IM"
    assert len(header) == 128
    return header + b"".join(elements)


@pytest.fixture
def uncompressed(tmp_path: Path) -> Path:
    path = tmp_path / "plain.mat"
    path.write_bytes(
        _mat_file(
            [
                _matrix("first", (2, 3), [1.0] * 6),
                _matrix("second", (4, 1), [2.0] * 4),
            ]
        )
    )
    return path


@pytest.fixture
def compressed(tmp_path: Path) -> Path:
    path = tmp_path / "deflated.mat"
    # A deflate stream is not padded to an eight-byte boundary, so two of them in
    # sequence is the case that catches a reader advancing by the wrong amount.
    path.write_bytes(
        _mat_file(
            [
                _element(_MI_COMPRESSED, zlib.compress(_matrix("alpha", (5, 7), [3.0] * 35))),
                _element(_MI_COMPRESSED, zlib.compress(_matrix("beta", (1, 2), [4.0, 5.0]))),
            ]
        )
    )
    return path


def test_names_and_shapes_come_back_from_an_uncompressed_file(uncompressed: Path) -> None:
    variables = read_mat_structure(uncompressed)
    assert [variable.name for variable in variables] == ["first", "second"]
    assert [variable.dimensions for variable in variables] == [(2, 3), (4, 1)]
    assert all(variable.class_name == "double" for variable in variables)
    assert not any(variable.is_complex for variable in variables)


def test_every_variable_is_found_past_a_compressed_element(compressed: Path) -> None:
    # The first version of this reader advanced past a deflate stream to the next
    # eight-byte boundary and so lost every variable after the first.
    variables = read_mat_structure(compressed)
    assert [variable.name for variable in variables] == ["alpha", "beta"]
    assert [variable.dimensions for variable in variables] == [(5, 7), (1, 2)]


def test_the_reader_exposes_no_route_to_a_value(uncompressed: Path) -> None:
    variables = read_mat_structure(uncompressed)
    fields = {field for variable in variables for field in variable.as_dict()}
    assert fields == {"name", "dimensions", "class", "complex"}


def test_a_version_73_container_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    path = tmp_path / "seven-three.mat"
    header = b"MATLAB 7.3 MAT-file, Platform: PCWIN64".ljust(124, b" ")
    path.write_bytes(header + struct.pack("<HH", 0x0200, 0x494D) + b"\x89HDF\r\n\x1a\n")
    with pytest.raises(ConfigurationError, match=r"7\.3"):
        read_mat_structure(path)


def test_a_non_mat_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "not-a-mat.bin"
    path.write_bytes(b"\x00" * 200)
    with pytest.raises(ConfigurationError, match="endian indicator"):
        read_mat_structure(path)


def test_csv_structure_is_headers_and_a_row_count(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text("cell_type,gaba,acetylcholine\na,1,0\nb,0,1\n", encoding="utf-8")
    described = describe_csv(path)
    assert described["columns"] == ["cell_type", "gaba", "acetylcholine"]
    assert described["data_rows"] == 2


def test_csv_row_count_survives_a_missing_final_newline(tmp_path: Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_text("a,b\n1,2\n3,4", encoding="utf-8")
    assert describe_csv(path)["data_rows"] == 2


def test_a_byte_order_mark_does_not_become_part_of_a_column_name(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_bytes("﻿species,known_nt\nx,y\n".encode())
    assert describe_csv(path)["columns"] == ["species", "known_nt"]


def test_archive_structure_is_entry_names(tmp_path: Path) -> None:
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/one.csv", "a,b\n")
        archive.writestr("data/two.csv", "c,d\n")
    described = describe_zip(path)
    assert described["entries"] == 2
    assert sorted(described["names"]) == ["data/one.csv", "data/two.csv"]


def test_workbook_structure_is_sheet_names(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook><sheets><sheet name="Responses" sheetId="1"/>'
            '<sheet name="Notes" sheetId="2"/></sheets></workbook>',
        )
    assert describe_xlsx(path)["sheets"] == ["Responses", "Notes"]


def _contract(datasets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "contract_id": "fixture",
        "manifest_id": "fixture",
        "reservation_rule": {"reserved": "no"},
        "datasets": datasets,
    }


def _write_contract(tmp_path: Path, datasets: list[dict[str, Any]]) -> Path:
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(_contract(datasets)), encoding="utf-8")
    return path


def _dataset(files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "fixture-dataset",
        "source": "fixture",
        "seal": "reserved",
        "release_condition": "a committed contract",
        "files": files,
    }


def test_a_reserved_name_that_is_absent_is_an_error(tmp_path: Path, uncompressed: Path) -> None:
    contract = _write_contract(
        tmp_path,
        [
            _dataset(
                [
                    {
                        "path": uncompressed.name,
                        "kind": "matlab-v5",
                        "role": "fixture",
                        "reserved_names": ["first", "renamed_away"],
                        "unreserved_names": ["second"],
                    }
                ]
            )
        ],
    )
    with pytest.raises(ConfigurationError, match="reserved names absent"):
        build_reservation_manifest(
            contract_path=contract,
            staging_root=uncompressed.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_a_name_that_is_neither_reserved_nor_released_is_an_error(
    tmp_path: Path, uncompressed: Path
) -> None:
    contract = _write_contract(
        tmp_path,
        [
            _dataset(
                [
                    {
                        "path": uncompressed.name,
                        "kind": "matlab-v5",
                        "role": "fixture",
                        "reserved_names": ["first"],
                    }
                ]
            )
        ],
    )
    with pytest.raises(ConfigurationError, match="neither reserved nor declared unreserved"):
        build_reservation_manifest(
            contract_path=contract,
            staging_root=uncompressed.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_reserve_all_covers_every_name_and_records_them(
    tmp_path: Path, uncompressed: Path
) -> None:
    contract = _write_contract(
        tmp_path,
        [
            _dataset(
                [
                    {
                        "path": uncompressed.name,
                        "kind": "matlab-v5",
                        "role": "fixture",
                        "reserve_all": True,
                    }
                ]
            )
        ],
    )
    manifest = build_reservation_manifest(
        contract_path=contract,
        staging_root=uncompressed.parent,
        output_path=tmp_path / "out.json",
        allow_dirty_tree=True,
    )
    entry = manifest["datasets"][0]["files"][0]
    assert entry["reserved_names"] == ["first", "second"]
    assert entry["declaration_check"]["names_present"] == 2
    assert len(entry["sha256"]) == 64


def test_reserve_all_cannot_be_combined_with_a_name_split(
    tmp_path: Path, uncompressed: Path
) -> None:
    contract = _write_contract(
        tmp_path,
        [
            _dataset(
                [
                    {
                        "path": uncompressed.name,
                        "kind": "matlab-v5",
                        "role": "fixture",
                        "reserve_all": True,
                        "unreserved_names": ["second"],
                    }
                ]
            )
        ],
    )
    with pytest.raises(ConfigurationError, match="reserve_all cannot be combined"):
        build_reservation_manifest(
            contract_path=contract,
            staging_root=uncompressed.parent,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_a_missing_reserved_file_is_an_error(tmp_path: Path) -> None:
    contract = _write_contract(
        tmp_path,
        [
            _dataset(
                [
                    {
                        "path": "gone.mat",
                        "kind": "matlab-v5",
                        "role": "fixture",
                        "reserve_all": True,
                    }
                ]
            )
        ],
    )
    with pytest.raises(ConfigurationError, match="Reserved file is missing"):
        build_reservation_manifest(
            contract_path=contract,
            staging_root=tmp_path,
            output_path=tmp_path / "out.json",
            allow_dirty_tree=True,
        )


def test_the_real_contract_seals_takagi_and_names_a_release_condition() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    datasets = {item["id"]: item for item in contract["datasets"]}
    takagi = datasets["takagi-2024-osn-expansion-pn-adaptation"]
    assert takagi["seal"].startswith("SEALED")
    assert "circuit-level prediction contract" in takagi["release_condition"]
    assert all(entry.get("reserve_all") for entry in takagi["files"])


def test_the_real_contract_leaves_the_transmitter_join_keys_readable() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    datasets = {item["id"]: item for item in contract["datasets"]}
    files = {
        entry["path"]: entry
        for entry in datasets["drosophila-neurotransmitter-ground-truth"]["files"]
    }
    ground_truth = files["drosophila-neurotransmitters/gt_data.csv"]
    # The measurement is reserved; the labels saying which cells were measured are not,
    # because a holdout is spent by seeing the measurement.
    assert "acetylcholine" in ground_truth["reserved_names"]
    assert "gaba" in ground_truth["reserved_names"]
    assert "cell_type" in ground_truth["unreserved_names"]
    assert "cell_type" not in ground_truth["reserved_names"]
    male_cns = files[
        "drosophila-neurotransmitters/gt_sources/male_cns/202509-male_cns_gt_data.csv"
    ]
    assert "cell_type_mcns" in male_cns["unreserved_names"]


def test_the_real_contract_records_that_analysis_code_was_read() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    rule = contract["reservation_rule"]
    assert "analysis_code_is_not_a_value" in rule
    assert "compound rather than unitary" in rule["analysis_code_is_not_a_value"]
