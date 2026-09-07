# Stage 1 Shiu antennal-grooming transfer

- Implementation commit: `1c2c097093ba73a65a7b88c6364bd296a634ce70`
- Immutable transfer report: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-antennal-grooming-transfer-30e3e5c6eec6fa62.json`
- Transfer report SHA-256: `30e3e5c6eec6fa62a727e8ce77790c7958bbda0e0c5cbfe1be73019f6e72fcf0`
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

At 20, 100, and 220 Hz, the archived FlyWire aBN1 means are 0.0, 0.933, and 4.633 Hz. The
transferred MaleCNS bilateral means across three seeds are 0.0, 26.167, and 70.667 Hz. The
frequency-response correlation is 0.983, so the rising direction transfers, but the amplitude
does not. This is a cross-connectome simulation-to-simulation comparison, not reproduction of
MaleCNS physiology.

Six structural controls completed at three frequencies and three seeds each:

| Variant | Mean bilateral readout rate across nine runs |
|---|---:|
| Exact graph | 32.278 Hz |
| Cell-type-only | 64.556 Hz |
| Randomized weights | 18.222 Hz |
| Shuffled connectivity | 16.944 Hz |
| Uniform weights | 14.444 Hz |
| Weak-edge dropout | 22.667 Hz |

The exact graph differs materially from several controls, but the cell-type-only control responds
more strongly. Consequently the result does not establish that exact individual wiring is needed
for the response. Four transmitter-unresolved policies also ran; every selected neuron had a
registered transmitter label, so those policies are identical for this circuit.

Direct float32 GeNN matches NumPy in total spikes and readout rates, with maximum neuron-wise
timing error within one 0.1-ms step. The transferred Brian2 Euler run differs by three spikes and
has a maximum readout-rate relative error of 9.09%, exceeding the preregistered 1% gate. The
older deterministic three-neuron backend fixture remains passing; this larger transferred circuit
reveals a solver-semantics discrepancy that must be resolved rather than hidden.

## Claim boundary and next gate

This work completes the first bounded Stage 1 experiment, its crosswalk, backends, controls, and
immutable report. It does not pass the Stage 1 exit gate and awards no V1, V2, or V3 evidence.
The next gate is to reconcile the Brian2 transfer against the authors' linear state updater, retain
the amplitude mismatch as a fitted-model target, and reproduce a second independent circuit with
biological stimulation or silencing evidence before a selected V3 review.
