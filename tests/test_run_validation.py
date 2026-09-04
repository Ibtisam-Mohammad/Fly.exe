# SPDX-License-Identifier: GPL-2.0-or-later
import json
from pathlib import Path

from flysim.factory import build_reference_demo
from flysim.runs import write_run
from flysim.validation import validate_run


def test_run_manifest_is_honest_and_valid(tmp_path: Path) -> None:
    demo = build_reference_demo(seed=1)
    result = demo.scheduler.run_until(demo.duration_us)
    written = write_run(
        result,
        demo.scenario,
        demo.registry,
        seed=1,
        output_root=tmp_path,
        ablated_inputs=(),
        ablated_outputs=(),
    )
    manifest = json.loads(written.manifest_path.read_text(encoding="utf-8"))
    assert manifest["connectome"]["graph_used"] is False
    assert manifest["result"]["highest_validation_tier"] is None
    assert manifest["result"]["scientific_validation_passed"] is False
    assert manifest["scaffolds"]
    report = validate_run(written.directory)
    assert report["valid"]
    assert report["required_sequence_observed"]


def test_trace_mutation_is_detected(tmp_path: Path) -> None:
    demo = build_reference_demo(seed=1)
    result = demo.scheduler.run_until(demo.duration_us)
    written = write_run(
        result,
        demo.scenario,
        demo.registry,
        seed=1,
        output_root=tmp_path,
        ablated_inputs=(),
        ablated_outputs=(),
    )
    with written.trace_path.open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    report = validate_run(written.directory)
    assert not report["valid"]
    assert any("checksum mismatch" in failure for failure in report["failures"])

