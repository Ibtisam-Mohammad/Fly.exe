# SPDX-License-Identifier: GPL-2.0-or-later
from flysim.engines.reference import OUTPUT_FEED, OUTPUT_GROOM, SENSOR_CONTAMINATION
from flysim.factory import build_reference_demo


def _signature(trace: tuple[dict, ...]) -> list[tuple[int, str, float, float]]:
    return [
        (
            item["t_us"],
            item["state"],
            round(item["body"]["x_mm"], 8),
            round(item["body"]["contamination"], 8),
        )
        for item in trace
    ]


def test_reference_demo_completes_in_required_order() -> None:
    demo = build_reference_demo(seed=1)
    result = demo.scheduler.run_until(demo.duration_us)
    assert result.completed
    targets = [event["to_state"] for event in result.events]
    assert targets == ["GROOM", "SEEK_RESUME", "FEED_INITIATION", "COMPLETE"]


def test_reference_demo_is_deterministic_for_fixed_seed() -> None:
    first = build_reference_demo(seed=7)
    second = build_reference_demo(seed=7)
    left = first.scheduler.run_until(first.duration_us)
    right = second.scheduler.run_until(second.duration_us)
    assert _signature(left.trace) == _signature(right.trace)


def test_groom_readout_ablation_blocks_grooming() -> None:
    demo = build_reference_demo(seed=1, ablated_outputs=frozenset({OUTPUT_GROOM}))
    result = demo.scheduler.run_until(demo.duration_us)
    assert not result.completed
    assert "GROOM" not in [event["to_state"] for event in result.events]


def test_contamination_input_ablation_blocks_grooming() -> None:
    demo = build_reference_demo(seed=1, ablated_inputs=frozenset({SENSOR_CONTAMINATION}))
    result = demo.scheduler.run_until(demo.duration_us)
    assert not result.completed
    assert "GROOM" not in [event["to_state"] for event in result.events]


def test_feed_readout_ablation_blocks_feeding() -> None:
    demo = build_reference_demo(seed=1, ablated_outputs=frozenset({OUTPUT_FEED}))
    result = demo.scheduler.run_until(demo.duration_us)
    assert not result.completed
    assert "FEED_INITIATION" not in [event["to_state"] for event in result.events]

