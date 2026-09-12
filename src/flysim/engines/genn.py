# SPDX-License-Identifier: GPL-2.0-or-later
"""Persistent direct-PyGeNN adapter for the full-graph Track A baseline."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from flysim.connectome import SparseConnectome
from flysim.contracts import NeuralInputFrame, NeuralOutputFrame, SignalType
from flysim.errors import CausalityError, ConfigurationError

TRACK_A_GENN_MODEL_VERSION = "4"
DEGREE_BUCKET_UPPER_BOUNDS = (64, 128, 256, 512, 1024, 2048, 4096, 8192)
#: How many distinct input id tuples to remember. A run normally alternates between a
#: handful of channel combinations, so this is generous; it is bounded so that a caller
#: varying its id set every interval cannot grow the cache without limit.
_INPUT_INDEX_CACHE_LIMIT = 64

HETEROGENEOUS_NEURON_PARAMETER_NAMES = (
    "MembraneDecay",
    "SynapseDecay",
    "SynapticVoltageCoefficient",
    "Vrest",
    "Vreset",
    "Vthresh",
    "TauRefrac",
    "Tonic",
)

CELL_PARAMETER_KEYS = (
    "resting_mv",
    "reset_mv",
    "threshold_mv",
    "membrane_tau_ms",
    "synapse_tau_ms",
    "refractory_ms",
    "tonic_drive_mv",
)


def derive_neuron_arrays(
    values: dict[str, np.ndarray], *, dt_ms: float, neuron_count: int
) -> dict[str, np.ndarray]:
    """Convert per-neuron physical membrane parameters into the engine coefficients.

    The registry stores physical units so it stays readable against a paper. The kernel
    needs decay coefficients, so the conversion lives here rather than in the registry.
    """
    missing = [key for key in CELL_PARAMETER_KEYS if key not in values]
    if missing:
        raise ConfigurationError(f"Per-neuron parameters omit {missing}")
    arrays = {key: np.asarray(values[key], dtype=np.float64) for key in CELL_PARAMETER_KEYS}
    for key, array in arrays.items():
        if array.shape != (neuron_count,):
            raise ConfigurationError(
                f"Per-neuron parameter {key} has shape {array.shape}, expected ({neuron_count},)"
            )
        if not np.all(np.isfinite(array)):
            raise ConfigurationError(f"Per-neuron parameter {key} contains nonfinite values")
    membrane_tau = arrays["membrane_tau_ms"]
    synapse_tau = arrays["synapse_tau_ms"]
    if np.any(membrane_tau <= 0.0) or np.any(synapse_tau <= 0.0):
        raise ConfigurationError("Per-neuron membrane and synapse time constants must be positive")
    if np.any(arrays["threshold_mv"] <= arrays["resting_mv"]):
        raise ConfigurationError("Per-neuron threshold must sit above resting potential")
    refractory = arrays["refractory_ms"] - dt_ms
    if np.any(refractory < 0.0):
        raise ConfigurationError(
            "Per-neuron refractory period must be at least one neural step; GeNN cannot "
            "represent a refractory period shorter than the timestep"
        )
    membrane_decay = np.exp(-dt_ms / membrane_tau)
    synapse_decay = np.exp(-dt_ms / synapse_tau)
    separated = ~np.isclose(synapse_tau, membrane_tau)
    coefficient = np.where(
        separated,
        np.divide(
            synapse_tau * (synapse_decay - membrane_decay),
            np.where(separated, synapse_tau - membrane_tau, 1.0),
        ),
        dt_ms * membrane_decay / membrane_tau,
    )
    return {
        "MembraneDecay": membrane_decay,
        "SynapseDecay": synapse_decay,
        "SynapticVoltageCoefficient": coefficient,
        "Vrest": arrays["resting_mv"],
        "Vreset": arrays["reset_mv"],
        "Vthresh": arrays["threshold_mv"],
        "TauRefrac": refractory,
        "Tonic": arrays["tonic_drive_mv"],
    }


@dataclass(frozen=True, slots=True)
class TrackAGeNNParameters:
    neural_dt_us: int
    resting_mv: float
    reset_mv: float
    threshold_mv: float
    membrane_tau_ms: float
    synapse_tau_ms: float
    refractory_ms: float
    synaptic_delay_ms: float
    synaptic_mv_per_contact: float
    central_entry_outgoing_gain: float
    tonic_drive_mv: float
    reset_synaptic_state_on_spike: bool
    # Attenuation-only per-target synaptic normalisation. A neuron integrating far more
    # incoming contacts than the median has, by cable theory, more membrane area and a
    # lower input resistance, so one contact deflects it less. This exponent declares how
    # much of that scaling to apply:
    #
    #     scale[target] = (reference / max(in_contacts[target], reference)) ** exponent
    #
    # with reference the median incoming-contact count over neurons that receive any
    # input. At 0.0 every scale is exactly 1.0 and the weights are byte-identical to a
    # run that predates this parameter, which is why 0.0 is the default. At 1.0 total
    # synaptic drive becomes size-invariant. Sparsely connected neurons are never
    # amplified, so the normalisation cannot manufacture instability at the tail.
    # P/E: a declared cable-theory-shaped choice, not a measurement.
    synaptic_target_normalisation_exponent: float = 0.0
    # Spike-frequency adaptation. Each spike adds this many millivolts to an
    # after-hyperpolarisation that decays with adaptation_tau_ms and is subtracted from
    # the effective resting baseline. At 0.0 the generated kernel is byte-identical to the
    # one that predates this parameter. P/E: universal in real neurons, but the value here
    # is declared, not measured.
    adaptation_increment_mv: float = 0.0
    adaptation_tau_ms: float = 200.0
    # Millivolts per inhibitory contact, relative to an excitatory one. The engine's
    # original behaviour is 1.0, which asserts that a predicted-inhibitory contact and a
    # predicted-excitatory contact deflect the membrane equally. Nothing supports that:
    # the signs are transmitter predictions, and the cholinergic and GABAergic synapses
    # being predicted differ in conductance and reversal potential. P/E, searched.
    inhibitory_weight_gain: float = 1.0

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> TrackAGeNNParameters:
        values = cls(
            **{
                name: raw[name]
                for name in cls.__dataclass_fields__
                if name in raw or cls.__dataclass_fields__[name].default is MISSING
            }
        )
        if min(
            values.neural_dt_us,
            values.membrane_tau_ms,
            values.synapse_tau_ms,
            values.refractory_ms,
            values.synaptic_delay_ms,
        ) <= 0:
            raise ConfigurationError("Track A GeNN time constants must be positive")
        if values.synaptic_mv_per_contact < 0:
            raise ConfigurationError("Track A synaptic scale cannot be negative")
        if values.central_entry_outgoing_gain < 1.0:
            raise ConfigurationError("Track A central-entry gain cannot be below one")
        if not 0.0 <= values.synaptic_target_normalisation_exponent <= 1.0:
            raise ConfigurationError(
                "Per-target synaptic normalisation exponent must lie in [0, 1]"
            )
        if values.adaptation_increment_mv < 0.0:
            raise ConfigurationError("Adaptation increment cannot be negative")
        if values.adaptation_tau_ms <= 0.0:
            raise ConfigurationError("Adaptation time constant must be positive")
        if values.inhibitory_weight_gain < 0.0:
            raise ConfigurationError("Inhibitory weight gain cannot be negative")
        if values.synaptic_delay_ms * 1000 % values.neural_dt_us != 0:
            raise ConfigurationError("Track A synaptic delay must align with the neural step")
        if values.delay_steps < 1:
            raise ConfigurationError(
                "Track A synaptic delay must be at least one neural step; GeNN cannot "
                "deliver a spike within the step that emitted it"
            )
        return values

    @property
    def dt_ms(self) -> float:
        return self.neural_dt_us / 1000.0

    @property
    def delay_steps(self) -> int:
        return round(self.synaptic_delay_ms / self.dt_ms)

    @property
    def axonal_delay_steps(self) -> int:
        """GeNN ``axonal_delay_steps`` that realises :attr:`delay_steps` of total delay.

        GeNN's generated code presents synaptic input to the postsynaptic neuron on the
        step after the presynaptic spike even with ``axonal_delay_steps = 0``. Assigning
        ``delay_steps`` therefore executed the registered 0.1 ms delay as 0.2 ms and put
        every GeNN backend one step behind NumPy and Brian2.
        """
        return self.delay_steps - 1

    @property
    def membrane_decay(self) -> float:
        return float(np.exp(-self.dt_ms / self.membrane_tau_ms))

    @property
    def synapse_decay(self) -> float:
        return float(np.exp(-self.dt_ms / self.synapse_tau_ms))

    @property
    def synaptic_voltage_coefficient(self) -> float:
        if np.isclose(self.synapse_tau_ms, self.membrane_tau_ms):
            return self.dt_ms * self.membrane_decay / self.membrane_tau_ms
        return float(
            self.synapse_tau_ms
            / (self.synapse_tau_ms - self.membrane_tau_ms)
            * (self.synapse_decay - self.membrane_decay)
        )

    @property
    def genn_refractory_ms(self) -> float:
        return self.refractory_ms - self.dt_ms


class TrackAGeNNEngine:
    """Keep one complete MaleCNS model loaded across every body exchange."""

    def __init__(self, build_path: Path, *, variant: str = "exact") -> None:
        self.build_path = build_path
        self.variant = variant
        self._t_us = 0
        self._graph: SparseConnectome | None = None
        self._parameters: TrackAGeNNParameters | None = None
        self._model: Any = None
        self._populations: tuple[Any, ...] = ()
        self._input_rates: tuple[Any, ...] = ()
        self._group_by_dense: np.ndarray | None = None
        self._local_by_dense: np.ndarray | None = None
        self._group_dense_indices: tuple[np.ndarray, ...] = ()
        self._sparse_layout: dict[str, Any] = {}
        self._flat_offsets: np.ndarray | None = None
        self._flat_index_by_dense: np.ndarray | None = None
        # Monitor pools key on their name; readout sets key on their ids.
        self._pool_flat_index: dict[
            str | tuple[str, tuple[int, ...]], np.ndarray
        ] = {}
        self._input_dense_index: dict[tuple[str, tuple[Any, ...]], np.ndarray] = {}
        self._last_frame_counts: np.ndarray | None = None
        self._last_counts: dict[int, float] = {}
        self._last_pool_counts: dict[str, np.ndarray] = {}
        self._model_identity: str | None = None
        self._cell_parameters: dict[str, Any] = {}
        self._loaded = False

    @property
    def t_us(self) -> int:
        return self._t_us

    def initialize(self, graph: SparseConnectome, parameters: dict[str, Any], seed: int) -> None:
        from pygenn import GeNNModel, create_neuron_model, init_postsynaptic, init_weight_update

        graph.validate()
        values = TrackAGeNNParameters.from_mapping(parameters)
        signs = np.asarray(parameters.get("functional_edge_signs"), dtype=np.float32)
        if signs.shape != graph.contact_counts.shape:
            raise ConfigurationError("Track A edge signs do not align with the complete graph")
        if not np.all(np.isin(signs, (-1.0, 0.0, 1.0))):
            raise ConfigurationError("Track A functional signs must be -1, 0, or 1")
        entry_body_ids = tuple(int(value) for value in parameters.get("entry_body_ids", ()))
        if not entry_body_ids:
            raise ConfigurationError("Track A central-entry body IDs are required")
        entry_by_dense = np.zeros(graph.neuron_count, dtype=np.bool_)
        for body_id in entry_body_ids:
            entry_by_dense[graph.dense_index(body_id)] = True
        # A neuron whose signal regime resolves to graded has no registered transmission
        # model here. Substituting the spiking model for it would be an undeclared
        # modelling decision, so the engine refuses the graph instead.
        regimes = tuple(str(value) for value in parameters.get("signal_regimes", ()))
        if regimes:
            if len(regimes) != graph.neuron_count:
                raise ConfigurationError(
                    "Track A signal regimes do not align with the complete graph"
                )
            graded = int(np.count_nonzero(np.asarray(regimes) == "graded"))
            if graded:
                raise ConfigurationError(
                    f"{graded} neurons resolve to the graded signal regime and no graded "
                    "transmission model is registered; refusing to run them as spiking cells"
                )
        per_neuron_raw = parameters.get("per_neuron_parameters")
        per_neuron: dict[str, np.ndarray] | None = None
        if per_neuron_raw is not None:
            per_neuron = derive_neuron_arrays(
                {key: np.asarray(value) for key, value in per_neuron_raw.items()},
                dt_ms=values.dt_ms,
                neuron_count=graph.neuron_count,
            )
        if self._loaded:
            raise ConfigurationError("Track A GeNN engine is already initialized")
        if "CUDA_PATH" not in os.environ:
            nvcc = shutil.which("nvcc")
            if nvcc is not None:
                os.environ["CUDA_PATH"] = str(Path(nvcc).resolve().parent.parent)

        reset_code = (
            "V = Vreset; SpikeCount += 1.0; "
            "RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac;"
        )
        if values.reset_synaptic_state_on_spike:
            reset_code = (
                "V = Vreset; G = 0.0; SpikeCount += 1.0; "
                "RefracTime = InputRateHz > 0.0 ? 0.0 : TauRefrac;"
            )
        # Shared parameters compile to constants and per-neuron vars to memory reads, so a
        # homogeneous graph keeps the cheaper model and the identical generated kernel.
        shared_names = () if per_neuron is not None else HETEROGENEOUS_NEURON_PARAMETER_NAMES
        promoted_vars = (
            tuple((name, "scalar") for name in HETEROGENEOUS_NEURON_PARAMETER_NAMES)
            if per_neuron is not None
            else ()
        )
        # Adaptation is opt-in, and when it is off the model below is character-for-
        # character the one that predates it, so every recorded run regenerates the same
        # kernel and the same model identity.
        adapting = values.adaptation_increment_mv > 0.0
        if adapting:
            adaptation_params = ("AdaptDecay", "AdaptIncrement")
            neuron_model = create_neuron_model(
                "MaleCNSTrackAAdaptiveLIF",
                params=(*shared_names, *adaptation_params),
                vars=(
                    *promoted_vars,
                    ("V", "scalar"),
                    ("G", "scalar"),
                    ("A", "scalar"),
                    ("RefracTime", "scalar"),
                    ("SpikeCount", "scalar"),
                    ("InputRateHz", "scalar"),
                ),
                sim_code="""
                A = A * AdaptDecay;
                if (RefracTime > 0.0) {
                    RefracTime -= dt;
                    V = Vreset;
                }
                else {
                    const scalar oldG = G;
                    const scalar baseline = Vrest + Tonic - A;
                    V = baseline + ((V - baseline) * MembraneDecay)
                        + (oldG * SynapticVoltageCoefficient);
                    G = oldG * SynapseDecay;
                    G += Isyn;
                }
                """,
                threshold_condition_code=(
                    "(InputRateHz > 0.0 && gennrand_uniform() < InputRateHz * dt / 1000.0) "
                    "|| (RefracTime <= 0.0 && V > Vthresh)"
                ),
                reset_code=reset_code + " A += AdaptIncrement;",
            )
        else:
            neuron_model = create_neuron_model(
                "MaleCNSTrackALIF",
                params=shared_names,
                vars=(
                    *promoted_vars,
                    ("V", "scalar"),
                    ("G", "scalar"),
                    ("RefracTime", "scalar"),
                    ("SpikeCount", "scalar"),
                    ("InputRateHz", "scalar"),
                ),
                sim_code="""
            if (RefracTime > 0.0) {
                RefracTime -= dt;
                V = Vreset;
            }
            else {
                const scalar oldG = G;
                const scalar baseline = Vrest + Tonic;
                V = baseline + ((V - baseline) * MembraneDecay)
                    + (oldG * SynapticVoltageCoefficient);
                G = oldG * SynapseDecay;
                G += Isyn;
            }
            """,
                threshold_condition_code=(
                    "(InputRateHz > 0.0 && gennrand_uniform() < InputRateHz * dt / 1000.0) "
                    "|| (RefracTime <= 0.0 && V > Vthresh)"
                ),
                reset_code=reset_code,
            )
        identity = hashlib.sha256()
        identity.update(TRACK_A_GENN_MODEL_VERSION.encode())
        identity.update(graph.source_sha256.encode())
        identity.update(signs.astype("<f4", copy=False).tobytes())
        identity.update(np.asarray(sorted(entry_body_ids), dtype="<u8").tobytes())
        # A parameter added after a run was recorded must not change that run's identity
        # when it sits at the value which reproduces the older behaviour exactly. Each new
        # field is therefore omitted from the identity while it is neutral, and included
        # the moment it is not.
        identity_payload = {
            name: getattr(values, name) for name in values.__dataclass_fields__
        }
        if values.synaptic_target_normalisation_exponent == 0.0:
            identity_payload.pop("synaptic_target_normalisation_exponent")
        if not adapting:
            identity_payload.pop("adaptation_increment_mv")
            identity_payload.pop("adaptation_tau_ms")
        if values.inhibitory_weight_gain == 1.0:
            identity_payload.pop("inhibitory_weight_gain")
        identity.update(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
        )
        # The random seed configures runtime RNG state but does not change the
        # generated CUDA model; all seeds of one graph/parameter variant share
        # the same compiled binary.
        identity.update(self.variant.encode())
        if per_neuron is None:
            identity.update(b"homogeneous")
        else:
            identity.update(b"per-neuron")
            for name in HETEROGENEOUS_NEURON_PARAMETER_NAMES:
                identity.update(per_neuron[name].astype("<f8", copy=False).tobytes())
        self._model_identity = identity.hexdigest()
        model = GeNNModel(
            "float",
            f"track_a_{self._model_identity[:12]}",
            backend="cuda",
            manual_device_id=0,
        )
        model.dt = values.dt_ms
        model.seed = seed
        # A single GeNN ragged projection would pad every source row to the
        # 11k-edge maximum out-degree. On MaleCNS this expands 25.6M logical
        # edges into about 1.85B slots. Disjoint degree buckets preserve the
        # exact graph while bounding the padding of every projection.
        out_degree = np.bincount(graph.source_indices, minlength=graph.neuron_count)
        group_by_dense = np.searchsorted(
            np.asarray(DEGREE_BUCKET_UPPER_BOUNDS), out_degree, side="right"
        ).astype(np.uint8)
        group_count = len(DEGREE_BUCKET_UPPER_BOUNDS) + 1
        group_dense_indices = tuple(
            np.flatnonzero(group_by_dense == group_index).astype(np.uint32)
            for group_index in range(group_count)
        )
        local_by_dense = np.empty(graph.neuron_count, dtype=np.uint32)
        populations: list[Any] = []
        adaptation_values = {
            "AdaptDecay": float(np.exp(-values.dt_ms / values.adaptation_tau_ms)),
            "AdaptIncrement": values.adaptation_increment_mv,
        }
        homogeneous_params = {
            "MembraneDecay": values.membrane_decay,
            "SynapseDecay": values.synapse_decay,
            "SynapticVoltageCoefficient": values.synaptic_voltage_coefficient,
            "Vrest": values.resting_mv,
            "Vreset": values.reset_mv,
            "Vthresh": values.threshold_mv,
            "TauRefrac": values.genn_refractory_ms,
            "Tonic": values.tonic_drive_mv,
        }
        neuron_params = {} if per_neuron is not None else homogeneous_params
        if adapting:
            neuron_params = {**neuron_params, **adaptation_values}
        for group_index, dense_indices in enumerate(group_dense_indices):
            if dense_indices.size == 0:
                raise ConfigurationError(
                    f"Track A degree bucket {group_index} unexpectedly has no neurons"
                )
            local_by_dense[dense_indices] = np.arange(
                dense_indices.size, dtype=np.uint32
            )
            neuron_vars: dict[str, Any] = {
                "V": values.resting_mv,
                "G": 0.0,
                "RefracTime": 0.0,
                "SpikeCount": 0.0,
                "InputRateHz": 0.0,
            }
            if adapting:
                neuron_vars["A"] = 0.0
            if per_neuron is not None:
                for name in HETEROGENEOUS_NEURON_PARAMETER_NAMES:
                    neuron_vars[name] = per_neuron[name][dense_indices]
                # Each neuron starts at its own resting potential, not a shared one.
                neuron_vars["V"] = per_neuron["Vrest"][dense_indices]
            populations.append(
                model.add_neuron_population(
                    f"neurons_{group_index}",
                    int(dense_indices.size),
                    neuron_model,
                    neuron_params,
                    neuron_vars,
                )
            )

        # Per-target normalisation scale, computed once over the whole graph so every
        # projection uses the same reference. Exactly ones at exponent 0.
        target_scale = np.ones(graph.neuron_count, dtype=np.float32)
        normalisation_report: dict[str, Any] = {
            "exponent": values.synaptic_target_normalisation_exponent,
            "applied": False,
        }
        if values.synaptic_target_normalisation_exponent > 0.0:
            in_contacts = np.bincount(
                graph.target_indices,
                weights=graph.contact_counts.astype(np.float64),
                minlength=graph.neuron_count,
            )
            receiving = in_contacts[in_contacts > 0.0]
            if receiving.size == 0:
                raise ConfigurationError(
                    "Per-target normalisation needs at least one neuron with input"
                )
            reference = float(np.median(receiving))
            ratio = reference / np.maximum(in_contacts, reference)
            target_scale = np.power(
                ratio, values.synaptic_target_normalisation_exponent
            ).astype(np.float32)
            normalisation_report = {
                "exponent": values.synaptic_target_normalisation_exponent,
                "applied": True,
                "reference_in_contacts_median": reference,
                "attenuated_neuron_count": int(np.count_nonzero(target_scale < 1.0)),
                "min_scale": float(target_scale.min()),
                "mean_scale": float(target_scale.mean()),
                "rule": (
                    "scale = (median_in_contacts / max(in_contacts, median)) ** exponent; "
                    "attenuation only, never amplification"
                ),
            }

        logical_edges = 0
        padded_slots = 0
        projection_count = 0
        for source_group in range(group_count):
            source_selection = group_by_dense[graph.source_indices] == source_group
            source_dense = graph.source_indices[source_selection]
            target_dense = graph.target_indices[source_selection]
            source_signs = signs[source_selection]
            source_contacts = graph.contact_counts[source_selection]
            source_entry = entry_by_dense[graph.source_indices[source_selection]]
            for target_group in range(group_count):
                selection = group_by_dense[target_dense] == target_group
                edge_count = int(np.count_nonzero(selection))
                if edge_count == 0:
                    continue
                pre = local_by_dense[source_dense[selection]]
                post = local_by_dense[target_dense[selection]]
                weights = (
                    source_contacts[selection].astype(np.float32)
                    * source_signs[selection]
                    * np.float32(values.synaptic_mv_per_contact)
                    * np.where(
                        source_entry[selection],
                        np.float32(values.central_entry_outgoing_gain),
                        np.float32(1.0),
                    )
                    * target_scale[target_dense[selection]]
                    * np.where(
                        source_signs[selection] < 0.0,
                        np.float32(values.inhibitory_weight_gain),
                        np.float32(1.0),
                    )
                )
                synapses = model.add_synapse_population(
                    f"edges_{source_group}_{target_group}",
                    "SPARSE",
                    populations[source_group],
                    populations[target_group],
                    init_weight_update("StaticPulse", {}, {"g": weights}),
                    init_postsynaptic("DeltaCurr"),
                )
                synapses.set_sparse_connections(pre, post)
                synapses.axonal_delay_steps = values.axonal_delay_steps
                logical_edges += edge_count
                padded_slots += (
                    int(synapses.max_connections)
                    * int(group_dense_indices[source_group].size)
                )
                projection_count += 1
        if logical_edges != graph.edge_count:
            raise ConfigurationError(
                f"Track A sparse layout retained {logical_edges} of {graph.edge_count} edges"
            )
        self.build_path.mkdir(parents=True, exist_ok=True)
        model.build(path_to_model=str(self.build_path), always_rebuild=False)
        model.load()
        self._graph = graph
        self._parameters = values
        self._model = model
        self._populations = tuple(populations)
        self._input_rates = tuple(pop.vars["InputRateHz"] for pop in populations)
        self._group_by_dense = group_by_dense
        self._local_by_dense = local_by_dense
        self._group_dense_indices = group_dense_indices
        self._cell_parameters = {
            "heterogeneous": per_neuron is not None,
            "promoted_to_per_neuron_vars": (
                list(HETEROGENEOUS_NEURON_PARAMETER_NAMES) if per_neuron is not None else []
            ),
            "signal_regimes_supplied": bool(regimes),
            "signal_regime_counts": (
                {
                    regime: int(np.count_nonzero(np.asarray(regimes) == regime))
                    for regime in sorted(set(regimes))
                }
                if regimes
                else None
            ),
            "resolution": parameters.get("cell_parameter_report"),
        }
        self._sparse_layout = {
            "strategy": "out-degree-bucketed-disjoint-populations-v1",
            "degree_bucket_upper_bounds": list(DEGREE_BUCKET_UPPER_BOUNDS),
            "population_sizes": [int(indices.size) for indices in group_dense_indices],
            "projection_count": projection_count,
            "logical_edges": logical_edges,
            "padded_slots": padded_slots,
            "padding_factor": padded_slots / logical_edges,
            "central_entry_body_count": len(entry_body_ids),
            "central_entry_outgoing_gain": values.central_entry_outgoing_gain,
            "per_target_normalisation": normalisation_report,
            "inhibitory_weight_gain": values.inhibitory_weight_gain,
            "spike_frequency_adaptation": {
                "enabled": adapting,
                "increment_mv_per_spike": values.adaptation_increment_mv,
                "tau_ms": values.adaptation_tau_ms,
                "kernel": (
                    "MaleCNSTrackAAdaptiveLIF" if adapting else "MaleCNSTrackALIF"
                ),
            },
        }
        # Flat offsets over the disjoint degree-bucket populations. The buckets partition
        # the neurons, so concatenating their SpikeCount views yields one array that any
        # pool can be gathered from with a single vectorised take.
        sizes = [int(indices.size) for indices in group_dense_indices]
        self._flat_offsets = np.concatenate(
            [np.zeros(1, dtype=np.int64), np.cumsum(np.asarray(sizes, dtype=np.int64))]
        )[:-1]
        self._flat_index_by_dense = (
            self._flat_offsets[group_by_dense.astype(np.int64)]
            + local_by_dense.astype(np.int64)
        )
        self._pool_flat_index.clear()
        self._input_dense_index.clear()
        self._last_frame_counts = None
        self._t_us = 0
        self._last_counts.clear()
        self._last_pool_counts.clear()
        self._loaded = True

    def push_inputs(self, frame: NeuralInputFrame) -> None:
        graph, _ = self._require_ready()
        if frame.t_us != self._t_us:
            raise CausalityError(
                f"Track A input time {frame.t_us} does not match engine time {self._t_us}"
            )
        if frame.signal_type is not SignalType.FIRING_RATE or frame.units != "Hz":
            raise ConfigurationError("Track A GeNN inputs must be firing rates in Hz")
        assert self._group_by_dense is not None and self._local_by_dense is not None
        for variable in self._input_rates:
            variable.view.fill(0.0)
        if frame.ids:
            if any(not isinstance(identifier, int) for identifier in frame.ids):
                raise ConfigurationError("Track A GeNN input IDs must be numeric body IDs")
            values = np.asarray(frame.values, dtype=np.float64)
            if not np.all(np.isfinite(values)) or np.any(values < 0.0):
                raise ConfigurationError("Track A input rates must be finite and nonnegative")
            # A multi-sensory bus pushes thousands of ids every coupling interval, and the
            # scalar loop this replaces cost about 29 ms per 15912-id frame against a 15 ms
            # interval -- the injection alone was slower than the biology it stood in for.
            # The dense-index map is cached on the id tuple, mirroring read_outputs.
            cache_key = ("__push_inputs__", frame.ids)
            dense = self._input_dense_index.get(cache_key)
            if dense is None:
                dense = np.fromiter(
                    (graph.dense_index(int(identifier)) for identifier in frame.ids),
                    dtype=np.int64,
                    count=len(frame.ids),
                )
                if len(self._input_dense_index) >= _INPUT_INDEX_CACHE_LIMIT:
                    self._input_dense_index.clear()
                self._input_dense_index[cache_key] = dense
            groups = self._group_by_dense[dense]
            locals_ = self._local_by_dense[dense]
            for group_index, variable in enumerate(self._input_rates):
                selected = groups == group_index
                if selected.any():
                    variable.view[locals_[selected]] = values[selected]
        for variable in self._input_rates:
            variable.push_to_device()

    def step_until(self, t_us: int) -> None:
        _, parameters = self._require_ready()
        if t_us < self._t_us:
            raise CausalityError(f"Cannot step GeNN backward from {self._t_us} to {t_us}")
        delta_us = t_us - self._t_us
        if delta_us % parameters.neural_dt_us:
            raise CausalityError("Track A coupling boundary is not aligned to the neural step")
        for _ in range(delta_us // parameters.neural_dt_us):
            self._model.step_time()
        self._t_us = t_us

    def read_outputs(self, ids: tuple[str | int, ...], window_us: int) -> NeuralOutputFrame:
        graph, _ = self._require_ready()
        if window_us <= 0:
            raise ConfigurationError("Track A output window must be positive")
        if any(not isinstance(identifier, int) for identifier in ids):
            raise ConfigurationError("Track A GeNN output IDs must be numeric body IDs")
        assert self._group_by_dense is not None and self._local_by_dense is not None
        body_ids = [int(identifier) for identifier in ids]
        # Keyed on the ids themselves, not on how many there are. Two different readout
        # sets of equal length -- three behaviours whose pools happen to sum alike, or a
        # monitor pool and a readout pool -- collided on the count and the second silently
        # reused the first one's flat index, returning one population's spikes under
        # another population's name.
        key = ("__read_outputs__", tuple(body_ids))
        index = self._pool_flat_index.get(key)
        if index is None:
            index = self._flat_index(body_ids)
            self._pool_flat_index[key] = index
        flat = self._flat_counts()
        cumulative_all = flat[index].astype(np.float64)
        previous_all = np.fromiter(
            (self._last_counts.get(body_id, 0.0) for body_id in body_ids),
            dtype=np.float64,
            count=len(body_ids),
        )
        if np.any(cumulative_all < previous_all):
            raise CausalityError("Track A spike counter moved backward")
        delta_all = cumulative_all - previous_all
        # The raw per-interval spike count is retained beside the derived rate. At a
        # 15 ms coupling interval one spike is 66.7 Hz, so a consumer that wants to
        # filter the rate causally needs the integer count rather than the quantised
        # rate it was divided into.
        values = (delta_all / (window_us / 1_000_000.0)).tolist()
        counts = np.rint(delta_all).astype(np.int64).tolist()
        for body_id, cumulative in zip(body_ids, cumulative_all.tolist(), strict=True):
            self._last_counts[body_id] = cumulative
        return NeuralOutputFrame(
            t_us=self._t_us,
            ids=ids,
            values=tuple(values),
            units="Hz",
            signal_type=SignalType.FIRING_RATE,
            provenance="M/P/E",
            assumption_ids=("ND-01", "ND-02", "ND-03", "ND-04", "ND-05", "TRACKA-01"),
            metadata={
                "backend": "direct-pygenn-5.4",
                "model_identity": self._model_identity,
                "variant": self.variant,
                "window_us": window_us,
                "spike_counts": dict(zip(ids, counts, strict=True)),
                "full_graph": True,
                "neurons": graph.neuron_count,
                "edges": graph.edge_count,
                "sparse_layout": self._sparse_layout,
                "cell_parameters": self._cell_parameters,
                "physiological_default": False,
                "warning": "Shiu transmitter-only regression baseline; not fitted physiology",
            },
        )

    def _locate(self, body_ids: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
        """Group and within-group indices for a set of body IDs."""
        graph, _ = self._require_ready()
        assert self._group_by_dense is not None and self._local_by_dense is not None
        dense = np.fromiter(
            (graph.dense_index(int(body_id)) for body_id in body_ids),
            dtype=np.int64,
            count=len(body_ids),
        )
        return self._group_by_dense[dense], self._local_by_dense[dense]

    def _flat_index(self, body_ids: Sequence[int]) -> np.ndarray:
        """Indices into the concatenated SpikeCount view for these bodies."""
        graph, _ = self._require_ready()
        assert self._flat_index_by_dense is not None
        dense = np.fromiter(
            (graph.dense_index(int(body_id)) for body_id in body_ids),
            dtype=np.int64,
            count=len(body_ids),
        )
        return self._flat_index_by_dense[dense]

    def _flat_counts(self) -> np.ndarray:
        """One concatenated, device-synchronised SpikeCount array over every neuron."""
        variables = tuple(pop.vars["SpikeCount"] for pop in self._populations)
        for variable in variables:
            variable.pull_from_device()
        return np.concatenate([np.asarray(variable.view) for variable in variables])

    def population_activity(
        self, pools: Mapping[str, Sequence[int]], window_us: int
    ) -> dict[str, dict[str, float]]:
        """Binned spike activity per named pool, differenced since the last call.

        This is the global-activity recorder. It reads whole populations rather than
        per-neuron traces, so an 89,390-body optic lobe costs one device pull and a
        vectorised gather, not a membrane trace at the 0.1 ms neural step.
        """
        self._require_ready()
        if window_us <= 0:
            raise ConfigurationError("Population activity window must be positive")
        flat = self._flat_counts()
        seconds = window_us / 1_000_000.0
        report: dict[str, dict[str, float]] = {}
        for name, body_ids in pools.items():
            if not body_ids:
                raise ConfigurationError(f"Activity pool {name} is empty")
            index = self._pool_flat_index.get(name)
            if index is None or index.size != len(body_ids):
                index = self._flat_index(body_ids)
                self._pool_flat_index[name] = index
            cumulative = flat[index].astype(np.float64)
            previous = self._last_pool_counts.get(name)
            if previous is None:
                previous = np.zeros_like(cumulative)
            delta = cumulative - previous
            if np.any(delta < 0.0):
                raise CausalityError(f"Track A spike counter moved backward in pool {name}")
            self._last_pool_counts[name] = cumulative
            report[name] = {
                "bodies": float(index.size),
                "spikes": float(delta.sum()),
                "mean_rate_hz": float(delta.sum() / index.size / seconds),
                "active_fraction": float(np.count_nonzero(delta) / index.size),
                "max_rate_hz": float(delta.max() / seconds) if index.size else 0.0,
            }
        return report

    def spike_counts_since_last_frame(self) -> np.ndarray:
        """Per-neuron spike count since the previous call, in dense graph order.

        This is what the brain view renders. It is one device pull and one subtraction
        over 165,122 counters, and it carries neuron identity, which a population rate
        does not and a membrane trace would only bury under ten thousand samples a second.
        """
        self._require_ready()
        assert self._flat_index_by_dense is not None
        flat = self._flat_counts()
        cumulative = flat[self._flat_index_by_dense].astype(np.float64)
        previous = self._last_frame_counts
        if previous is None:
            previous = np.zeros_like(cumulative)
        delta = cumulative - previous
        if np.any(delta < 0.0):
            raise CausalityError("Track A spike counter moved backward")
        self._last_frame_counts = cumulative
        counts: np.ndarray = np.rint(delta).astype(np.int32)
        return counts

    def read_state(self, body_ids: Sequence[int]) -> dict[str, list[float]]:
        """Membrane voltage and synaptic state for a declared, selected body set.

        Deliberately not every neuron and deliberately not at the neural step: the caller
        names the bodies and calls this at coupling boundaries.
        """
        self._require_ready()
        if not body_ids:
            raise ConfigurationError("read_state needs at least one body ID")
        groups, locals_ = self._locate(body_ids)
        out: dict[str, list[float]] = {}
        for name in ("V", "G", "SpikeCount"):
            variables = tuple(pop.vars[name] for pop in self._populations)
            for variable in variables:
                variable.pull_from_device()
            views = tuple(np.asarray(variable.view) for variable in variables)
            out[name] = [
                float(views[g][i]) for g, i in zip(groups, locals_, strict=True)
            ]
        out["body_ids"] = [float(body_id) for body_id in body_ids]
        return out

    def checkpoint(self) -> dict[str, Any]:
        graph, _ = self._require_ready()
        return {
            "t_us": self._t_us,
            "backend": "direct-pygenn-5.4",
            "model_identity": self._model_identity,
            "variant": self.variant,
            "neurons": graph.neuron_count,
            "edges": graph.edge_count,
            "sparse_layout": self._sparse_layout,
            "cell_parameters": self._cell_parameters,
            "state_arrays_omitted": "optional Track A checkpoint is metadata-only",
        }

    def close(self) -> None:
        if self._loaded:
            self._model.unload()
            self._loaded = False

    def _require_ready(self) -> tuple[SparseConnectome, TrackAGeNNParameters]:
        if not self._loaded or self._graph is None or self._parameters is None:
            raise ConfigurationError("Track A GeNN engine is not initialized")
        return self._graph, self._parameters
