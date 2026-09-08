# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression tests for the 2026-09-08 evidence-chain repair.

Each test pins one defect that the independent audit confirmed and that no existing test
could detect.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from flysim.connectome import (
    SparseConnectome,
    graph_array_hashes,
    verify_graph_array_hashes,
)
from flysim.engines.body import COMMAND_FORWARD, COMMAND_IDS, COMMAND_YAW
from flysim.errors import ConfigurationError, DatasetError, ValidationError
from flysim.evidence import resolve_supported_tier
from flysim.provenance import AssumptionRegistry
from flysim.runs import require_clean_worktree
from flysim.scheduler import coupling_quantised_delay_us
from flysim.validation import validate_run

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# --- Step 1: the project tier is derived from a bundle, never asserted -----------------


def _bundle(path: Path, artifact: Path, *, tier: str = "V0") -> None:
    from flysim.evidence import REQUIRED_GATES, ValidationTier, sha256_file

    _write(
        path,
        {
            "schema_version": "1.0",
            "bundle_id": f"20260908T000000Z_{tier}",
            "tier": tier,
            "created_at": "2026-09-08T00:00:00+00:00",
            "required_gates": list(REQUIRED_GATES[ValidationTier(tier)]),
            "gates": {gate: True for gate in REQUIRED_GATES[ValidationTier(tier)]},
            "artifacts": [
                {
                    "name": "pinned",
                    "path": str(artifact),
                    "bytes": artifact.stat().st_size,
                    "sha256": sha256_file(artifact),
                }
            ],
        },
    )


def test_supported_tier_is_none_when_the_only_bundle_stopped_validating(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    pinned = evidence / "pinned.json"
    _write(pinned, {"value": 1})
    _bundle(evidence / "V0-evidence.json", pinned)
    assert resolve_supported_tier(evidence)["tier"] == "V0"

    _write(pinned, {"value": 2, "grew": "by an unrelated edit"})
    report = resolve_supported_tier(evidence)
    assert report["tier"] is None
    assert report["rejected_bundles"]


def test_supported_tier_prefers_a_reissued_bundle_over_a_stale_one(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    stale_artifact = evidence / "stale.json"
    fresh_artifact = evidence / "fresh.json"
    _write(stale_artifact, {"value": 1})
    _write(fresh_artifact, {"value": 1})
    _bundle(evidence / "V0-evidence.json", stale_artifact)
    _bundle(evidence / "V0-evidence-r2.json", fresh_artifact)
    _write(stale_artifact, {"value": 1, "changed": True})

    report = resolve_supported_tier(evidence)
    assert report["tier"] == "V0"
    assert report["bundle"].endswith("V0-evidence-r2.json")
    assert report["valid_bundles"] == 1


# --- Step 4: evidence-grade runs refuse a dirty worktree -------------------------------


def test_require_clean_worktree_rejects_uncommitted_changes(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "x"],
        cwd=tmp_path,
        check=True,
    )
    (tmp_path / "file.txt").write_text("two\n", encoding="utf-8")

    import flysim.runs as runs

    original = runs.project_root
    runs.project_root = lambda: tmp_path  # type: ignore[assignment]
    try:
        with pytest.raises(ValidationError, match="clean git worktree"):
            require_clean_worktree("An evidence-grade run")
        subprocess.run(["git", "checkout", "--", "file.txt"], cwd=tmp_path, check=True)
        assert require_clean_worktree("An evidence-grade run")["dirty"] is False
    finally:
        runs.project_root = original  # type: ignore[assignment]


# --- Step 5: GeNN realises the registered synaptic delay -------------------------------


def test_track_a_axonal_delay_compensates_genn_delivery_latency() -> None:
    from flysim.engines.genn import TrackAGeNNParameters

    registry = AssumptionRegistry.load(PROJECT_ROOT / "configs" / "assumptions.json")
    values = TrackAGeNNParameters.from_mapping(registry.value_map("TRACKA-01"))
    assert values.delay_steps == 1
    assert values.axonal_delay_steps == values.delay_steps - 1


def test_stage1_axonal_delay_compensates_genn_delivery_latency() -> None:
    from flysim.circuit import TransferLIFParameters

    parameters = TransferLIFParameters(
        dt_ms=0.1,
        duration_ms=1.0,
        resting_mv=-52.0,
        reset_mv=-52.0,
        threshold_mv=-45.0,
        membrane_tau_ms=20.0,
        synapse_tau_ms=5.0,
        refractory_ms=2.2,
        synaptic_delay_ms=0.3,
        synaptic_mv_per_contact=0.275,
        tonic_drive_mv=0.0,
        reset_synaptic_state_on_spike=True,
        state_updater="source-faithful-linear",
        genn_precision="float64-reference",
    )
    parameters.validate()
    assert parameters.delay_steps == 3
    assert parameters.axonal_delay_steps == 2


@pytest.mark.parametrize("delay_steps", [1, 2, 3])
def test_one_synapse_impulse_arrives_after_the_registered_delay(
    delay_steps: int, tmp_path: Path
) -> None:
    """A forced presynaptic spike must reach the postsynaptic cell after exactly
    ``delay_steps``, which is what makes GeNN agree with NumPy and Brian2."""
    pygenn = pytest.importorskip("pygenn")

    dt_ms = 0.1
    model = pygenn.GeNNModel("double", f"delay_probe_{delay_steps}", backend="single_threaded_cpu")
    model.dt = dt_ms
    source = model.add_neuron_population(
        "source",
        1,
        pygenn.create_neuron_model(
            "forced",
            vars=[("Forced", "scalar")],
            sim_code="",
            threshold_condition_code="Forced > 0.5",
            reset_code="Forced = 0.0;",
        ),
        {},
        {"Forced": 0.0},
    )
    target = model.add_neuron_population(
        "target",
        1,
        pygenn.create_neuron_model(
            "accumulator",
            vars=[("V", "scalar")],
            sim_code="V += Isyn;",
        ),
        {},
        {"V": 0.0},
    )
    synapses = model.add_synapse_population(
        "edge",
        "SPARSE",
        source,
        target,
        pygenn.init_weight_update("StaticPulse", {}, {"g": np.array([1.0])}),
        pygenn.init_postsynaptic("DeltaCurr"),
    )
    synapses.set_sparse_connections(np.array([0], dtype=np.uint32), np.array([0], dtype=np.uint32))
    synapses.axonal_delay_steps = delay_steps - 1
    build_path = tmp_path / f"delay-probe-{delay_steps}"
    build_path.mkdir(parents=True, exist_ok=True)
    model.build(path_to_model=str(build_path), always_rebuild=False)
    model.load()
    try:
        source.vars["Forced"].view[:] = 1.0
        source.vars["Forced"].push_to_device()
        arrival: int | None = None
        for step in range(1, 12):
            model.step_time()
            target.vars["V"].pull_from_device()
            if arrival is None and float(target.vars["V"].view[0]) != 0.0:
                arrival = step
        assert arrival == delay_steps + 1, (
            f"a spike emitted during step 1 with a registered {delay_steps}-step delay must "
            f"first affect the target at step {delay_steps + 1}, observed {arrival}"
        )
    finally:
        model.unload()


# --- Step 6: interface delays are registered at the value the loop realises ------------


def test_coupling_quantised_delay_matches_queue_polling() -> None:
    assert coupling_quantised_delay_us(0, 15000) == 0
    assert coupling_quantised_delay_us(2000, 15000) == 15000
    assert coupling_quantised_delay_us(15000, 15000) == 15000
    assert coupling_quantised_delay_us(16000, 15000) == 30000


def test_registry_declares_the_delays_the_scheduler_realises() -> None:
    registry = AssumptionRegistry.load(PROJECT_ROOT / "configs" / "assumptions.json")
    timing = registry.value_map("NUM-01")
    coupling = int(timing["track_a_coupling_us"])
    for registered, effective in (
        ("sensory_delay_us", "effective_sensory_delay_us"),
        ("motor_delay_us", "effective_motor_delay_us"),
    ):
        assert int(timing[effective]) == coupling_quantised_delay_us(
            int(timing[registered]), coupling
        )


def test_reference_demo_publishes_its_timing_contract() -> None:
    from flysim.factory import build_reference_demo

    demo = build_reference_demo(seed=1)
    contract = demo.scheduler.timing_contract()
    assert contract["registered_sensory_delay_us"] == 2000
    assert contract["effective_sensory_delay_us"] == 15000
    assert contract["effective_motor_delay_us"] == 15000
    result = demo.scheduler.run_until(demo.duration_us)
    assert result.timing == contract


# --- Step 7: forward and yaw are normalized drives, not velocities ---------------------


def test_actuator_ids_and_units_describe_normalized_drives() -> None:
    from flysim.factory import build_reference_demo

    assert COMMAND_FORWARD == "actuator:forward-drive"
    assert COMMAND_YAW == "actuator:yaw-drive"
    demo = build_reference_demo(seed=1)
    result = demo.scheduler.run_until(2_000_000)
    actuators = result.trace[-1]["actuators"]
    assert actuators["ids"] == list(COMMAND_IDS)
    assert "mm/s" not in actuators["units"]
    assert actuators["units"].startswith("normalized-drive")
    assert actuators["metadata"]["normalized_controller_drive"] is True
    forward = actuators["values"][0]
    yaw = actuators["values"][1]
    assert 0.0 <= forward <= 1.0
    assert -1.0 <= yaw <= 1.0


# --- Step 8: the settled body starts outside the dust patch ----------------------------


class _StubBody:
    """Exercise the dust-clearance guard without building a MuJoCo model."""

    def __init__(self, x_mm: float, dust_x_mm: float, radius: float, clearance: float) -> None:
        from flysim.engines.flygym import FlyGymTrackABodyEngine

        self._x = x_mm
        self.parameters = type(
            "P",
            (),
            {
                "dust_x_mm": dust_x_mm,
                "dust_y_mm": 0.0,
                "dust_radius_mm": radius,
                "dust_entry_clearance_mm": clearance,
            },
        )()
        self._guard = FlyGymTrackABodyEngine._assert_settled_outside_dust

    def _pose(self) -> tuple[float, float, float, float]:
        return (self._x, 0.0, 0.0, 0.0)

    def check(self) -> None:
        self._guard(self)  # type: ignore[arg-type]


def test_settled_body_inside_the_dust_patch_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="outside the dust patch"):
        _StubBody(x_mm=0.851, dust_x_mm=2.0, radius=1.5, clearance=0.25).check()


def test_registered_track_a_geometry_leaves_dust_clearance_after_settling() -> None:
    """The published settling offset must not put the thorax in the dust at t=0."""
    registry = AssumptionRegistry.load(PROJECT_ROOT / "configs" / "assumptions.json")
    body = registry.value_map("BODY-01")
    settled_x_mm = float(body["initial_x_mm"]) + 0.851
    clearance = (
        abs(settled_x_mm - float(body["dust_x_mm"])) - float(body["dust_radius_mm"])
    )
    assert clearance >= float(body["dust_entry_clearance_mm"])


def test_run_validation_rejects_excess_grooming_displacement(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    record = {
        "t_us": 15000,
        "state": "GROOM",
        "body": {"t_us": 15000},
        "sensors": {"t_us": 15000},
        "neural": {"t_us": 15000},
        "actuators": {"t_us": 15000},
    }
    (run / "trace.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    from flysim.validation import _sha256_file

    _write(
        run / "manifest.json",
        {
            "run_id": "test",
            "scenario": {},
            "assumption_set": {},
            "random_seed": 1,
            "backends": {},
            "connectome": {"graph_used": False},
            "scaffolds": [],
            "omissions": [],
            "git": {},
            "artifacts": {
                "trace": "trace.jsonl",
                "trace_sha256": _sha256_file(run / "trace.jsonl"),
            },
            "result": {
                "completed": False,
                "events": [{"t_us": 15000, "to_state": "GROOM"}],
                "highest_validation_tier": None,
            },
            "run_metadata": {
                "groom_net_displacement_limit_mm": 2.5,
                "groom_net_displacement_mm": 6.55,
            },
        },
    )
    report = validate_run(run)
    # Artifact integrity and behavioural acceptance are separate: the record is well formed,
    # so it stays valid, but the declared limit is reported as breached.
    assert report["valid"] is True
    assert report["behavioral_criteria_passed"] is False
    assert report["behavioral"]["groom_displacement_passed"] is False
    assert report["behavioral"]["groom_net_displacement_mm"] == 6.55
    assert "exceeds" in report["behavioral"]["groom_displacement_note"]


def test_run_validation_passes_grooming_displacement_within_the_limit(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    record = {
        "t_us": 15000,
        "state": "GROOM",
        "body": {"t_us": 15000},
        "sensors": {"t_us": 15000},
        "neural": {"t_us": 15000},
        "actuators": {"t_us": 15000},
    }
    (run / "trace.jsonl").write_text(json.dumps(record) + chr(10), encoding="utf-8")
    from flysim.validation import _sha256_file

    _write(
        run / "manifest.json",
        {
            "run_id": "test",
            "scenario": {},
            "assumption_set": {},
            "random_seed": 1,
            "backends": {},
            "connectome": {"graph_used": False},
            "scaffolds": [],
            "omissions": [],
            "git": {},
            "artifacts": {
                "trace": "trace.jsonl",
                "trace_sha256": _sha256_file(run / "trace.jsonl"),
            },
            "result": {
                "completed": False,
                "events": [{"t_us": 15000, "to_state": "GROOM"}],
                "highest_validation_tier": None,
            },
            "run_metadata": {
                "groom_net_displacement_limit_mm": 2.5,
                "groom_net_displacement_mm": 1.2,
            },
        },
    )
    report = validate_run(run)
    assert report["valid"] is True
    assert report["behavioral_criteria_passed"] is True


def test_run_validation_rejects_events_absent_from_the_trace(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    record = {
        "t_us": 15000,
        "state": "SEEK",
        "body": {"t_us": 15000},
        "sensors": {"t_us": 15000},
        "neural": {"t_us": 15000},
        "actuators": {"t_us": 15000},
    }
    (run / "trace.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    from flysim.validation import _sha256_file

    _write(
        run / "manifest.json",
        {
            "run_id": "test",
            "scenario": {},
            "assumption_set": {},
            "random_seed": 1,
            "backends": {},
            "connectome": {"graph_used": False},
            "scaffolds": [],
            "omissions": [],
            "git": {},
            "artifacts": {
                "trace": "trace.jsonl",
                "trace_sha256": _sha256_file(run / "trace.jsonl"),
            },
            "result": {
                "completed": False,
                "events": [{"t_us": 15000, "to_state": "FEED_INITIATION"}],
                "highest_validation_tier": None,
            },
        },
    )
    report = validate_run(run)
    assert report["valid"] is False
    assert any("is not in the trace" in item for item in report["failures"])


# --- Step 9: every required control carries a falsifiable criterion --------------------


def test_every_required_control_has_a_falsifiable_criterion() -> None:
    experiment = json.loads(
        (PROJECT_ROOT / "configs" / "experiments" / "track-a-acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    criteria = experiment["control_criteria"]
    for control in experiment["required_controls"]:
        assert control in criteria, control
        assert criteria[control]["type"] in {
            "blocked-transition",
            "readout-degradation",
            "artifact-present",
            "graph-unused",
            "transition-signature-identical",
        }
    shuffled = criteria["shuffled-connectome"]
    assert shuffled["type"] == "readout-degradation"
    assert shuffled["must_not_complete"] is True
    assert 0.0 < float(shuffled["max_fraction_of_exact_peak"]) < 1.0


# --- Step 10: the held-out positions have never been used ------------------------------


def test_held_out_food_positions_are_new_and_are_not_the_arena_default() -> None:
    experiment = json.loads(
        (PROJECT_ROOT / "configs" / "experiments" / "track-a-acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    registry = AssumptionRegistry.load(PROJECT_ROOT / "configs" / "assumptions.json")
    body = registry.value_map("BODY-01")
    default = (float(body["food_x_mm"]), float(body["food_y_mm"]))
    used = {
        (float(item["x"]), float(item["y"]))
        for item in experiment["previously_used_food_positions_mm"]
    }
    held_out = {
        (float(item["x"]), float(item["y"]))
        for item in experiment["held_out_food_positions_mm"]
    }
    assert not held_out & used
    assert default not in held_out


# --- Step 12: the runtime graph arrays are pinned --------------------------------------


def _small_graph() -> SparseConnectome:
    return SparseConnectome(
        body_ids=np.array([10, 20, 30], dtype=np.uint64),
        source_indices=np.array([0, 1], dtype=np.uint32),
        target_indices=np.array([1, 2], dtype=np.uint32),
        contact_counts=np.array([4, 7], dtype=np.uint32),
        source_release="male-cns:v1.0",
        source_sha256="0" * 64,
    )


def test_graph_directory_records_and_verifies_array_hashes(tmp_path: Path) -> None:
    path = tmp_path / "graph"
    _small_graph().save_directory(path, extra_manifest={})
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["array_sha256"]) == {
        "body_ids.npy",
        "source_indices.npy",
        "target_indices.npy",
        "contact_counts.npy",
    }
    assert verify_graph_array_hashes(path, manifest)["verified"] is True
    assert SparseConnectome.load(path).edge_count == 2


def test_graph_load_detects_a_changed_runtime_array(tmp_path: Path) -> None:
    path = tmp_path / "graph"
    _small_graph().save_directory(path, extra_manifest={})
    tampered = np.load(path / "contact_counts.npy")
    tampered[0] = 99
    np.save(path / "contact_counts.npy", tampered)

    with pytest.raises(DatasetError, match="Runtime graph array changed"):
        SparseConnectome.load(path)


def test_graph_manifest_without_hashes_reports_unverified(tmp_path: Path) -> None:
    path = tmp_path / "graph"
    _small_graph().save_directory(path, extra_manifest={})
    manifest_path = path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["array_sha256"]
    _write(manifest_path, manifest)

    report = verify_graph_array_hashes(path, manifest)
    assert report == {
        "verified": False,
        "reason": "the graph manifest records no per-array hashes",
    }
    assert graph_array_hashes(path)
