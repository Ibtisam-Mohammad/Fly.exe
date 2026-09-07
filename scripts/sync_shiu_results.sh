#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
set -euo pipefail

output_dir="${1:-/srv/flybrain-data/raw/auxiliary/shiu-2024-brain-model}"
expected_bytes=4499610373
expected_md5="f6f2e314821fa6a4196214e3b2b14bc4"
url="https://edmond.mpg.de/api/access/datafile/223847"
partial="${output_dir}/results.zip.part"
final="${output_dir}/results.zip"

mkdir -p "${output_dir}"
exec 9>"${output_dir}/results.zip.lock"
if ! flock -n 9; then
    printf '{"error":"download_locked","retryable":true,"status":"failed"}\n' >&2
    exit 75
fi
if [[ -f "${final}" ]]; then
    actual_bytes="$(stat -c %s "${final}")"
    actual_md5="$(md5sum "${final}" | cut -d ' ' -f 1)"
    [[ "${actual_bytes}" == "${expected_bytes}" && "${actual_md5}" == "${expected_md5}" ]]
else
    curl --location --fail --retry 20 --retry-all-errors --retry-delay 5 \
        --continue-at - --output "${partial}" "${url}"
    actual_bytes="$(stat -c %s "${partial}")"
    if (( actual_bytes > expected_bytes )); then
        prefix_md5="$(
            dd if="${partial}" iflag=count_bytes count="${expected_bytes}" \
                bs=8M status=none | md5sum | cut -d ' ' -f 1
        )"
        if [[ "${prefix_md5}" != "${expected_md5}" ]]; then
            printf '{"error":"oversized_unrecoverable","retryable":false,"status":"failed"}\n' >&2
            exit 65
        fi
        truncate -s "${expected_bytes}" "${partial}"
        actual_bytes="${expected_bytes}"
    fi
    actual_md5="$(md5sum "${partial}" | cut -d ' ' -f 1)"
    [[ "${actual_bytes}" == "${expected_bytes}" && "${actual_md5}" == "${expected_md5}" ]]
    mv -- "${partial}" "${final}"
fi

actual_sha256="$(sha256sum "${final}" | cut -d ' ' -f 1)"
printf '{"bytes":%s,"file":"%s","md5":"%s","sha256":"%s","status":"ok"}\n' \
    "${actual_bytes}" "${final}" "${actual_md5}" "${actual_sha256}"
