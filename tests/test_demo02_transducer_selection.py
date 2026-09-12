# SPDX-License-Identifier: GPL-2.0-or-later
from __future__ import annotations

from flysim.demo02_embodied import _bindings
from flysim.sensory_atlas import ChannelKey, SensoryAtlas


def _atlas() -> SensoryAtlas:
    keyed = {
        ChannelKey("tarsal-taste", "leg-front", "L"): (1,),
        ChannelKey("tarsal-taste", "leg-front", "R"): (2,),
        ChannelKey("tarsal-taste", "leg-hind", "L"): (3,),
        ChannelKey("tarsal-taste", "leg-hind", "R"): (4,),
    }
    return SensoryAtlas(
        registry_id="fixture",
        annotations_sha256="fixture",
        channels={str(key): value for key, value in keyed.items()},
        channel_keys=tuple(keyed),
        modality_kind={"tarsal-taste": "declared"},
        modality_bodies={"tarsal-taste": (1, 2, 3, 4)},
        modality_note={},
        surrogates={},
        unassigned=(),
        entry_union=(1, 2, 3, 4),
        entry_union_sha256="fixture",
    )


def test_feeding_binding_uses_the_registered_search_rate() -> None:
    bindings = _bindings(
        _atlas(),
        "feeding",
        variant="exact",
        parameters={"taste_max_rate_hz": 800.0},
    )
    assert bindings
    assert all(binding.transducer.max_rate_hz == 800.0 for binding in bindings)
