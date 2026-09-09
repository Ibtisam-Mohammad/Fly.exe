# SPDX-License-Identifier: GPL-2.0-or-later
"""Immutable reservation manifests for observational data that has not been opened.

A held-out observation is spent the moment somebody looks at it, so a reservation is only
worth as much as the record of what was reserved. This module writes that record before
any value is read: for every declared file it stores the checksum, the byte count and the
*structure* — variable names and array shapes for MATLAB files, column headers and row
counts for tables, entry listings for archives — and then freezes the manifest as an
immutable snapshot named by its own digest.

The readers here are deliberately incapable of returning a value. The MATLAB reader parses
the element headers of the MAT version 5 container and stops at the first data subelement;
it never decodes a numeric payload, so a reservation cannot be spent by running it. That is
a structural guarantee rather than a promise, which is the only kind worth making here.

Two integrity checks make the manifest more than paperwork. Every variable or column the
declaration reserves must exist in the file, so a renamed or reorganised source is caught
rather than silently unreserved; and every variable or column that exists must be either
reserved or explicitly declared unreserved, so nothing escapes the reservation by omission.
"""

from __future__ import annotations

import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flysim.config import load_json, sha256_json
from flysim.datasets import sha256_file
from flysim.errors import ConfigurationError
from flysim.runs import git_metadata, require_clean_worktree
from flysim.stage1 import _atomic_json, _immutable_snapshot

_MAT5_HEADER_BYTES = 128
_MI_COMPRESSED = 15
_MI_MATRIX = 14
_MI_INT8 = 1
_MI_UINT32 = 6
_MI_INT32 = 5
_HDF5_SIGNATURE = b"\x89HDF\r\n\x1a\n"
# Enough of a compressed element to reach the array name, which follows the tag, the array
# flags and the dimensions. Never enough to reach a numeric payload of any size.
_COMPRESSED_PEEK_BYTES = 4096
_CSV_CHUNK_BYTES = 1 << 20

_MAT_CLASS_NAMES: dict[int, str] = {
    1: "cell",
    2: "struct",
    3: "object",
    4: "char",
    5: "sparse",
    6: "double",
    7: "single",
    8: "int8",
    9: "uint8",
    10: "int16",
    11: "uint16",
    12: "int32",
    13: "uint32",
    14: "int64",
    15: "uint64",
}

_SHEET_NAME = re.compile(rb'<sheet[^>]*name="([^"]*)"')


@dataclass(frozen=True, slots=True)
class MatVariable:
    """One top-level MATLAB variable, described without decoding its data."""

    name: str
    dimensions: tuple[int, ...]
    class_name: str
    is_complex: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dimensions": list(self.dimensions),
            "class": self.class_name,
            "complex": self.is_complex,
        }


@dataclass(frozen=True, slots=True)
class _Tag:
    element_type: int
    byte_count: int
    data_offset: int
    next_offset: int


def _read_tag(blob: bytes, offset: int, little: bool) -> _Tag:
    """Parse a MAT version 5 element tag in either of its two forms.

    A small data element packs the byte count into the upper half of the first word and
    occupies exactly eight bytes in total; a full tag is eight bytes followed by data
    padded to an eight-byte boundary. The successor offset differs between the two, so it
    is computed here rather than at each call site, which is where the first version of
    this reader got it wrong.
    """
    if offset + 8 > len(blob):
        raise ConfigurationError("Truncated MATLAB element tag")
    order = "<" if little else ">"
    first, second = struct.unpack_from(order + "II", blob, offset)
    small = first >> 16
    if small:
        return _Tag(first & 0xFFFF, small, offset + 4, offset + 8)
    return _Tag(first, second, offset + 8, offset + 8 + _padded(second))


def _padded(byte_count: int) -> int:
    return (byte_count + 7) & ~7


def _parse_matrix(blob: bytes, offset: int, limit: int, little: bool) -> MatVariable:
    """Read array flags, dimensions and name, then stop before any data subelement."""
    order = "<" if little else ">"
    flags = _read_tag(blob, offset, little)
    if flags.element_type != _MI_UINT32 or flags.byte_count < 8:
        raise ConfigurationError("MATLAB array flags subelement is malformed")
    flags_word = struct.unpack_from(order + "I", blob, flags.data_offset)[0]
    class_id = flags_word & 0xFF
    is_complex = bool((flags_word >> 8) & 0x08)

    dims = _read_tag(blob, flags.next_offset, little)
    if dims.element_type != _MI_INT32:
        raise ConfigurationError("MATLAB dimensions subelement is malformed")
    count = dims.byte_count // 4
    dimensions = tuple(
        int(value) for value in struct.unpack_from(order + f"{count}i", blob, dims.data_offset)
    )

    name = _read_tag(blob, dims.next_offset, little)
    if name.element_type != _MI_INT8:
        raise ConfigurationError("MATLAB array name subelement is malformed")
    if name.data_offset + name.byte_count > limit:
        raise ConfigurationError("MATLAB array name runs past its element")
    label = blob[name.data_offset : name.data_offset + name.byte_count]
    # Everything after the name is the payload. It is never read.
    return MatVariable(
        name=label.decode("ascii", errors="replace"),
        dimensions=dimensions,
        class_name=_MAT_CLASS_NAMES.get(class_id, f"class-{class_id}"),
        is_complex=is_complex,
    )


def read_mat_structure(path: Path) -> tuple[MatVariable, ...]:
    """Describe the top-level variables of a MAT version 5 file, reading no values.

    A version 7.3 file is HDF5 rather than a MAT container and is reported as such by
    raising, because guessing at its structure would be worse than saying nothing.
    """
    with path.open("rb") as stream:
        head = stream.read(_MAT5_HEADER_BYTES)
        if len(head) < _MAT5_HEADER_BYTES:
            raise ConfigurationError("File is shorter than a MAT version 5 header")
        if head.startswith(_HDF5_SIGNATURE) or head[:16].startswith(b"MATLAB 7.3"):
            raise ConfigurationError(
                "MATLAB version 7.3 file: an HDF5 container, whose structure this "
                "header-only reader deliberately does not parse"
            )
        endian = head[126:128]
        if endian == b"IM":
            little = True
        elif endian == b"MI":
            little = False
        else:
            raise ConfigurationError("Not a MAT version 5 file: endian indicator absent")
        body = stream.read()

    variables: list[MatVariable] = []
    cursor = 0
    while cursor + 8 <= len(body):
        tag = _read_tag(body, cursor, little)
        if tag.element_type not in {_MI_COMPRESSED, _MI_MATRIX}:
            break
        end = tag.data_offset + tag.byte_count
        if tag.element_type == _MI_COMPRESSED:
            peek = zlib.decompressobj().decompress(
                body[tag.data_offset : end], _COMPRESSED_PEEK_BYTES
            )
            inner = _read_tag(peek, 0, little)
            if inner.element_type != _MI_MATRIX:
                raise ConfigurationError("Compressed MATLAB element is not an array")
            variables.append(_parse_matrix(peek, inner.data_offset, len(peek), little))
        else:
            variables.append(_parse_matrix(body, tag.data_offset, end, little))
        cursor = _skip_padding(body, end)
    return tuple(variables)


def _skip_padding(body: bytes, position: int) -> int:
    """Step over up to seven zero bytes of alignment padding.

    Writers disagree about whether a top-level element is padded to an eight-byte
    boundary: MATLAB does not pad a deflate stream and does pad an uncompressed array.
    Skipping zeros handles both without having to know which wrote the file, and it is
    safe because no element type is zero.
    """
    limit = min(position + 8, len(body))
    while position < limit and body[position] == 0:
        position += 1
    return position


def describe_csv(path: Path, *, delimiter: str = ",") -> dict[str, Any]:
    """Column headers and row count. Only the first line is decoded."""
    with path.open("rb") as stream:
        first = stream.readline()
        newlines = 0
        last = b""
        while True:
            chunk = stream.read(_CSV_CHUNK_BYTES)
            if not chunk:
                break
            newlines += chunk.count(b"\n")
            last = chunk
    header = first.decode("utf-8-sig", errors="replace").rstrip("\r\n")
    columns = [field.strip('"') for field in header.split(delimiter)] if header else []
    # A final line without a newline still holds a row, and a file that is nothing but a
    # header holds none. Both cases are real in this staging directory.
    rows = 0 if not last else newlines + (0 if last.endswith(b"\n") else 1)
    return {"columns": columns, "data_rows": rows}


def describe_zip(path: Path) -> dict[str, Any]:
    """Entry names and sizes. No entry is opened."""
    with zipfile.ZipFile(path) as archive:
        entries = [
            {"name": info.filename, "bytes": info.file_size}
            for info in archive.infolist()
            if not info.is_dir()
        ]
    return {"entries": len(entries), "names": [entry["name"] for entry in entries]}


def describe_xlsx(path: Path) -> dict[str, Any]:
    """Sheet names from the workbook part. No cell is read."""
    with zipfile.ZipFile(path) as archive:
        try:
            workbook = archive.read("xl/workbook.xml")
        except KeyError as error:  # pragma: no cover - malformed workbook
            raise ConfigurationError(f"Not an xlsx workbook: {path.name}") from error
        parts = [name for name in archive.namelist() if not name.endswith("/")]
    sheets = [match.decode("utf-8") for match in _SHEET_NAME.findall(workbook)]
    return {"sheets": sheets, "parts": len(parts)}


def _describe(path: Path, kind: str) -> dict[str, Any]:
    if kind == "matlab-v5":
        return {"variables": [variable.as_dict() for variable in read_mat_structure(path)]}
    if kind == "csv":
        return describe_csv(path)
    if kind == "zip":
        return describe_zip(path)
    if kind == "xlsx":
        return describe_xlsx(path)
    if kind == "opaque":
        return {
            "structure_read": False,
            "why": "no reader in the environment; checksum and byte count only",
        }
    raise ConfigurationError(f"Unknown reservation file kind: {kind!r}")


def _structure_names(kind: str, structure: dict[str, Any]) -> list[str]:
    if kind == "matlab-v5":
        return [str(item["name"]) for item in structure["variables"]]
    if kind == "csv":
        return [str(name) for name in structure["columns"]]
    if kind == "zip":
        return [str(name) for name in structure["names"]]
    if kind == "xlsx":
        return [str(name) for name in structure["sheets"]]
    return []


def _check_declaration(
    *, file_id: str, kind: str, present: list[str], reserved: list[str], unreserved: list[str]
) -> dict[str, Any]:
    """Reserved names must exist, and existing names must be classified."""
    if kind == "opaque":
        return {"checked": False, "why": "structure was not read"}
    missing = [name for name in reserved if name not in present]
    if missing:
        raise ConfigurationError(
            f"{file_id}: reserved names absent from the file: {sorted(missing)}"
        )
    unknown_unreserved = [name for name in unreserved if name not in present]
    if unknown_unreserved:
        raise ConfigurationError(
            f"{file_id}: names declared unreserved are absent: {sorted(unknown_unreserved)}"
        )
    classified = set(reserved) | set(unreserved)
    unclassified = sorted(name for name in present if name not in classified)
    if unclassified:
        raise ConfigurationError(
            f"{file_id}: names present but neither reserved nor declared unreserved: "
            f"{unclassified}"
        )
    return {
        "checked": True,
        "names_present": len(present),
        "names_reserved": len(reserved),
        "names_declared_unreserved": len(unreserved),
    }


def build_reservation_manifest(
    *,
    contract_path: Path,
    staging_root: Path,
    output_path: Path,
    allow_dirty_tree: bool = False,
) -> dict[str, Any]:
    """Checksum and describe every reserved file, then freeze the manifest."""
    worktree = (
        git_metadata()
        if allow_dirty_tree
        else require_clean_worktree("A reservation manifest")
    )
    contract = load_json(contract_path)
    if contract.get("schema_version") != "1.0":
        raise ConfigurationError("Unsupported reservation contract schema")
    datasets: list[dict[str, Any]] = []
    for declared in contract["datasets"]:
        files: list[dict[str, Any]] = []
        for entry in declared["files"]:
            path = staging_root / str(entry["path"])
            if not path.is_file():
                raise ConfigurationError(f"Reserved file is missing: {path}")
            kind = str(entry["kind"])
            structure = _describe(path, kind)
            present = _structure_names(kind, structure)
            if entry.get("reserve_all"):
                if entry.get("reserved_names") or entry.get("unreserved_names"):
                    raise ConfigurationError(
                        f"{entry['path']}: reserve_all cannot be combined with an "
                        "explicit name split"
                    )
                # Everything the structure reader found is reserved. The manifest still
                # records the full list, so the record is no less specific than an
                # enumeration would have been.
                reserved = list(present)
                unreserved = []
            else:
                reserved = [str(name) for name in entry.get("reserved_names", [])]
                unreserved = [str(name) for name in entry.get("unreserved_names", [])]
            files.append(
                {
                    "path": str(entry["path"]),
                    "kind": kind,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "role": str(entry["role"]),
                    "structure": structure,
                    "reserved_names": reserved,
                    "unreserved_names": unreserved,
                    "reserve_all_declared": bool(entry.get("reserve_all", False)),
                    "declaration_check": _check_declaration(
                        file_id=str(entry["path"]),
                        kind=kind,
                        present=present,
                        reserved=reserved,
                        unreserved=unreserved,
                    ),
                }
            )
        datasets.append(
            {
                "id": str(declared["id"]),
                "source": str(declared["source"]),
                "seal": str(declared["seal"]),
                "release_condition": str(declared["release_condition"]),
                "files": files,
                "reserved_files": len(files),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "result_id": str(contract["manifest_id"]),
        "contract_id": str(contract["contract_id"]),
        "contract_sha256": sha256_json(contract),
        "provenance": "M",
        "staging_root": str(staging_root),
        "reservation_rule": contract["reservation_rule"],
        "what_this_reader_cannot_do": (
            "The MATLAB reader parses element headers and stops at the first data "
            "subelement, so it cannot return a numeric value. The table reader decodes "
            "the header line and counts newlines. The archive readers list entries. No "
            "reserved observation is decoded by building this manifest."
        ),
        "datasets": datasets,
        "reserved_datasets": len(datasets),
        "reserved_files": sum(int(item["reserved_files"]) for item in datasets),
        "claim_boundary": (
            "A record of what is reserved and unopened. It scores nothing, awards no "
            "tier, and makes no claim about any value inside the files it describes."
        ),
        "code_commit": worktree["commit"],
        "worktree_dirty": worktree["dirty"],
        "evidence_grade": not worktree["dirty"],
    }
    payload["logical_sha256"] = sha256_json(payload)
    _atomic_json(output_path, payload)
    snapshot, digest = _immutable_snapshot(output_path)
    return {
        **payload,
        "output": str(output_path.resolve()),
        "sha256": digest,
        "immutable_snapshot": str(snapshot),
    }
