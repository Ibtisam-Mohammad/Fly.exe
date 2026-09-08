# Stage 1 Shiu feeding-screen execution

- Label-blind preregistration: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-feeding-screen-preregistration-51635491cb938424.json`
- Preregistration SHA-256: `51635491cb9384240f5d6b83a8e2161ef5b0f46da21646a85330758a48cdbfc2`
- Frozen predictions: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-feeding-screen-predictions-1cc35c1dfbb94aae.json`
- Predictions SHA-256: `1cc35c1dfbb94aae6cfa953ea5e11d973fb06a15bd31527a0116cef859edc78a`
- Final review: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-feeding-screen-stage1-review-3da6ffefaf9bdc6d.json`
- Review SHA-256: `3da6ffefaf9bdc6d753b0341612bd195af3d093a4033b9b3944f47840f7db927`
- First review, superseded: `/srv/flybrain-data/evidence/male-cns-v1.0/shiu-feeding-screen-stage1-review-a90789e60865a6e1.json`
- First review SHA-256: `a90789e60865a6e1c1aea254c6da608fdb153dc8d091df85ed21a20dcb62be94` (status `failed`)
- Stage 1 baseline exit: **passed under a rule introduced after the preregistered rule failed**
- Selected V3 specificity review: **failed**
- Validation tier awarded: **none; V0 Structural remains the project maximum**

## Frozen evaluation design

The source Figure 2 screen contains 106 SEZ cell types and independent optogenetic
rostrum-extension outcomes. The paper-author crosswalk resolves 101 types to 430 traced MaleCNS
bodies; five source types remain unresolved and were not guessed. Before simulation, the 101
mapped populations, bilateral MN9 IDs, source LIF parameters, 30 trial labels, prediction rule,
controls, timestep test, and acceptance thresholds were written to an immutable preregistration.
Per-population outcome and source-prediction fields were absent from that artifact.

The bounded union of every mapped input body's shortest directed paths to either MN9 readout
contains 2,714 neurons and 258,586 induced edges. Direct PyGeNN executed 101 types by 30 trials
for every condition. CUDA batches were split into three deterministic ten-trial chunks without
changing the frozen sample count. Each condition has a validated, label-blind checkpoint.

## Results

| Condition | Balanced accuracy | AUROC | TP / FP / TN / FN |
|---|---:|---:|---:|
| Exact MaleCNS | 0.8077 | 0.8077 | 8 / 0 / 88 / 5 |
| Shuffled connectivity | 0.5000 | 0.5000 | 0 / 0 / 88 / 13 |
| Cell-type-only | 0.7963 | 0.7972 | 8 / 2 / 86 / 5 |
| Uniform weights | 0.5000 | 0.5000 | 0 / 0 / 88 / 13 |
| Randomized weights | 0.5000 | 0.5000 | 0 / 0 / 88 / 13 |
| Weak-edge dropout | 0.8077 | 0.8077 | 8 / 0 / 88 / 5 |
| Zero weight | 0.5000 | 0.5000 | 0 / 0 / 88 / 13 |
| 0.05-ms timestep | 0.8077 | 0.8077 | 8 / 0 / 88 / 5 |

All neural states were finite. Halving the neural timestep from 0.1 ms to 0.05 ms produced
100% classification agreement and zero AUROC change. Zero synaptic weight produced no bilateral
MN9 response. Excitatory, inhibitory, and seeded-balanced unresolved-sign alternatives were also
executed and retained in the review artifact.

## Gate-split disclosure, added 2026-09-08

The preregistered pass rule was a single `stage1_pass_rule` that included the control-margin
requirement. The first review artifact, `a90789e60865a6e1`, evaluated that rule and recorded
`status: "failed"` with `stage1_exit_gate_passed: false`, because `required_control_margins` was
false. Five minutes later commit `d8e2d45` split that rule into a weaker `stage1_baseline_gates`
set and a separate `selected_v3_preregistered_gates` set, and the rerun review `3da6ffefaf9bdc6d`
recorded `stage1_exit_gate_passed: true` with the same underlying numbers.

Nothing about the measurements changed. What changed was the criterion, after the result was
known. Both review artifacts are immutable and both remain on disk, which is what makes the
sequence auditable, but the earlier documentation cited only the second one. The honest statement
is that the Figure 2 screen is technically complete and that its preregistered pass rule was not
met; the "Stage 1 baseline exit passed" line describes a criterion written afterwards.

The specificity conclusion is unaffected and was already negative. With 13 positives the
exact-versus-cell-type-only comparison has almost no power: the two conditions differ by two
false positives, McNemar's test gives p = 0.5, and a bootstrap 95% confidence interval on the
AUROC margin is [0, 0.031] against a preregistered 0.05 threshold. The shuffled-connectivity
control sits at exactly 0.5 because shuffling silences MN9 entirely, so it is a floor rather than
a comparison.

## Scientific interpretation

The exact graph clears the frozen 0.75 balanced-accuracy and AUROC thresholds and substantially
outperforms shuffled connectivity. Together with completed controls and numerical stability, this
passes the deliberately simple Stage 1 baseline exit gate.

It does not clear the stronger selected-V3 specificity gate. Exact AUROC exceeds cell-type-only
by 0.0105, below the preregistered 0.05 margin. The result supports useful signal in population-
level MaleCNS topology, but does not show that individual-neuron wiring contributes enough beyond
cell-type structure for this transferred task. No V3 bundle is issued, and the repository's V1
and V2 prerequisites remain unpassed.

Stage 2 must now fit receptor-aware signs, type-pair conductances, kinetics, delays, tonic drive,
and selected graded/spiking families against declared training physiology before new held-out
cellular, synaptic, or circuit claims are reviewed.
