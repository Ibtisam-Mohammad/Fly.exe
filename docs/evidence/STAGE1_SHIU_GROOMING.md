# Stage 1 Shiu antennal-grooming transfer

- Implementation commit: `2e909709b0c05d4f9ab023fd27693a36252bc3dc`
- Immutable transfer report: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-antennal-grooming-transfer-1290b8d717eaff49.json`
- Transfer report SHA-256: `1290b8d717eaff4956fa90f0e5fe233a5ab25022e4a72d1de5165ead3d9aa577`
- Published-output reference: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-figure5g-reference.json`
- Reference report SHA-256: `c8a8a26682f58a1dc7b084a610f47db1013bfbf3ec75f66249da27dcb5ff409b`
- Validation tier awarded: **none; V0 Structural remains the project maximum**

## Completed scope

The authors' repository is pinned at commit
`91bdd1e7dcf193f3e7ca5a8933497fcef63b7960`. The Edmond v3.0 `results.zip` archive is
checksum-locked at 4,499,610,373 bytes, source MD5
`f6f2e314821fa6a4196214e3b2b14bc4`, and local SHA-256
`f757c8e18e3826c89ba12f930bee455bb6dc22f28403a27161e9b9d9f0a65e93`.

The archived Figure 5g JON-F-to-aBN1 mean and population-standard-deviation series were
recomputed from all 11 raw Parquet outputs and matched the authors' derived CSVs exactly. This
reproduces the archived output analysis; it does not rerun all 330 whole-brain Brian2 trials and
is not independent biological evidence.

The paper-author MaleCNS/FlyWire crosswalk maps 58 of 60 JON-F source cells to `JO-FV`,
`JO-FD1`, or `JO-FD2`. Those types resolve to 78 MaleCNS bodies. FlyWire aBN1 maps to
MaleCNS type `SAD093`, resolving bodies `11718` and `521358`. Only 39 of the 78 input bodies
have a direct shortest path to these readouts in the traced aggregate graph, producing a
41-neuron, 129-edge induced circuit. The other 39 are recorded as present but without a shortest
path; none is silently removed from the crosswalk record.

Two of the three FlyWire inhibitory cells map to type `CB0496`, but MaleCNS v1.0 has no body
with that annotation. The silencing transfer is therefore explicitly unavailable. No substitute
was guessed.

The command below executes the transferred model and controls:

```text
flysim benchmark circuit --experiment shiu-antennal-grooming \
  --root /srv/flybrain-data \
  --graph /srv/flybrain-data/derived/male-cns-v1.0/graph \
  --backend brian2 --backend genn
```

## Measured result

All 11 archived FlyWire aBN1 frequency points from 20 through 220 Hz now run with the same three
registered seeds. With the source fallback of 0.275 mV/contact, the transferred MaleCNS
bilateral mean rises from 0.0 to 60.333 Hz, versus 0.0 to 4.633 Hz in the archived FlyWire
output. The full-curve correlation is 0.861. The rising direction transfers, but the amplitude
does not. This remains a cross-connectome simulation-to-simulation comparison, not reproduction
of MaleCNS physiology.

Six structural variants completed at all 11 frequencies and three seeds each:

| Variant | Mean bilateral readout rate across 33 runs |
|---|---:|
| Exact graph | 29.682 Hz |
| Cell-type-only | 59.576 Hz |
| Randomized weights | 17.303 Hz |
| Shuffled connectivity | 14.758 Hz |
| Uniform weights | 13.333 Hz |
| Weak-edge dropout | 21.045 Hz |

The exact graph differs materially from several controls, but the cell-type-only control responds
more strongly. Consequently the result does not establish that exact individual wiring is needed
for the response. Four transmitter-unresolved policies also ran; every selected neuron had a
registered transmitter label, so those policies are identical for this circuit.

The source-faithful scheduler makes Brian2's linear updater semantics explicit: state update,
threshold, delayed synaptic write, reset, and rejection of writes to an `unless refractory`
state. NumPy and Brian2 now have identical spike identities, counts, and rates; their maximum
timing difference is approximately `1.1e-13` ms. The bounded float64 reference GeNN run also
has identical identities, counts, and rates, with a maximum difference of one 0.1-ms step.
Whole-CNS production remains float32; float64 is used here only to make the small-circuit
numerical oracle deterministic.

The report now embeds the versioned `male-cns-cell-dynamics-v0.1` registry. It assigns a
class-level spiking prior to the 39 selected JO-F bodies and preserves both `SAD093` readouts as
unresolved LIF-versus-passive-graded alternatives. The report also enumerates all 13 observed
type-pair edge classes. The source-faithful LIF regression remains active for this result;
typed hybrid execution and type-pair scales are not fitted or enabled.

The preregistered `ND-04` fit searched 11 nonnegative global contact scales using only 20, 100,
and 220 Hz. It selected 0.075 mV/contact with a training RMSE of 2.259 Hz. After freezing that
value, all eight held-out frequencies from 40 through 200 Hz produced zero bilateral readout
activity even though every archived reference mean was positive. Held-out positive-response
coverage is therefore 0/8 and held-out RMSE is 1.631 Hz. The held-out set was not used for
retuning. A single global contact scale is rejected as an adequate transfer model for this
circuit.

## Claim boundary and next gate

This work completes the first bounded Stage 1 experiment, its crosswalk, source-faithful backend
parity, 11-frequency sweep, controls, held-out fit test, and immutable report. It does not pass
the Stage 1 exit gate and awards no V1, V2, or V3 evidence. The blockers are now explicit: the
global `ND-04` scale fails held-out transfer, mapped `CB0496` silencing is unavailable, and the
reference is simulation output rather than biological response data. The next gate is
preregistered execution of the prepared Figure 2 feeding screen, using its biological labels
only for held-out evaluation, before any selected V3 review.

## GeNN delay correction, 2026-09-08

The one-step GeNN offset recorded in this report was a defect, not a property of the backend.
GeNN presents synaptic input to the postsynaptic neuron on the step after the presynaptic spike
even with `axonal_delay_steps = 0`, and the adapters assigned the full registered `delay_steps`
on top of that, so the registered 0.1 ms delay executed as 0.2 ms. The adapters now assign
`delay_steps - 1`, and `tests/test_repairs.py` pins the semantics with a one-synapse impulse
probe at one, two and three steps on the CPU backend. Every measurement in this report predates
that fix, so a rerun would move the GeNN spike times one step earlier and remove the offset.
