# DEMO-01 progress ledger

Working ledger for the five-stage push to a rendered full-graph closed-loop video.
Branch `demo-01-embodiment`. Tier stays **V0 Structural**; every dynamics parameter is
P/E; the neural->locomotor decoder is E. Updated as each stage closes.

## Rule this ledger exists to enforce

No stage may be reopened by loosening a criterion that a previous stage froze. If a
frozen criterion fails, the failure is recorded here and the *stimulus or the declared
populations* change, never the threshold. See `docs/adr/` for the standing discipline.

## Stage status

| stage | what it closes | state |
|-------|----------------|-------|
| S0 | Route measurement: which sensory->descending path is structurally usable | DONE 2026-09-10 |
| S1 | A neural-only operating point that passes frozen C1-C5 on a visual route | **PASSED** 2026-09-10: 31 of 108 candidates met all five criteria |
| S2 | E-provenance decoder tuned on development scenarios, then frozen | **FROZEN** 2026-09-10: yaw gain 1.6, threshold 0.6, sign +1 |
| S3 | Engineering acceptance contract frozen, identical-seed control matrix run | contract frozen; stance defect found and fixed; matrix running |
| S4 | Video: brain view + body view + traces + control comparison | renderer built and validated; final render pending |
| S5 | Retinotopic upgrade / further chapters | out of scope for this push |

## S0 findings (measured 2026-09-10, read-only, exact graph)

Signed contact-share flow on the exact 165,122-body / 25,563,197-edge graph with ND-10
Shiu-regression signs and the `zero` unresolved policy.

| route | hops | direct contacts | share of target input | flow at first reach | laterality h1-h4 |
|-------|------|-----------------|----------------------|--------------------|------------------|
| ORN_DM1/DM4 -> DNa01/02 (failed route) | 3 | 0 | 0.00% | 6.6e-05 | none |
| LC4 -> DNp02/03/04/06 | 1 | 19,465 | 19.95% | 1.35e-01 | +1.00 / +0.97 / +1.00 / +0.86 |
| LC4 -> DNp01 (giant fibre) | 1 | 6,362 | 17.32% | 4.47e-02 | +1.00 / +0.62 / +0.42 / +0.13 |
| LPLC2 -> DNp02/03/04/06 | 2 | 369 | 5.25% | 2.73e-02 | +1.00 / +0.82 / +0.78 / +0.77 |
| LC10 -> AOTU019 | 1 | 26,692 | 43.52% | 2.63e-02 | +1.00 / +0.58 |
| LC10 -> DNa02 | 2 | 0 | - | 5.96e-03 | +0.81 at h2 |
| JO -> descending pool | 1 | 48,225 | 1.05% | 1.56e-01 | +0.78 |
| gustatory -> GNG588 | 1 | 59 | 0.91% | 4.8e-05 | weak |

Structural flow is necessary, not sufficient: the odour route had some and still failed
dynamically. Every pivot re-runs the frozen neural-only probe.

## Environment facts established

* Offscreen MuJoCo renders under `MUJOCO_GL=osmesa` and `glfw`; **egl fails** (EGLError).
* `imageio_ffmpeg`, `flygym`, `PIL`, `matplotlib`, `scipy` present. No pyvista/trimesh/open3d.
* 140,024 of 165,122 in-graph bodies carry `somaLocation`, so a brain point cloud is possible.
* Runtime cost: 12.4 s build, 17.7 s wall per 5.25 s simulated (3.4x real time).

## S1 design decisions (2026-09-10)

Taken on computational-neuroscience grounds, recorded here so they are not silently
revisited.

**D1. The behaviour follows the circuit, not the reverse.** The strongest sensory ->
descending route in this connectome is looming visual -> escape descending neurons
(LC4/LPLC2 -> DNp01/DNp02/03/04/06). The canonical male approach route
(LC10a -> AOTU019 -> DNa02) exists but is 23x weaker, and ND-10 predicts the
AOTU019 -> DNa02 synapse (586 contacts) is **inhibitory**. Rather than force an
approach behaviour onto an avoidance circuit, the declared behaviour target becomes:

> a spatial visual cue produces lateralised descending activity, which produces
> locomotion with a consistent cue-side-dependent turn, which moves the cue in the
> visual field, closing the loop.

Whether the turn is *toward* or *away* is read off the frozen network, not chosen. Both
are acceptable outcomes and the sign is reported. This keeps the user's stated loop
structure (stationary -> cue -> neural -> locomotion/turn -> closed-loop update) while
refusing to pick a behaviour the anatomy does not support.

**Correction to D1, made 2026-09-10 after the first embodied run.** D1 said the turn
direction is "read off the frozen network, not chosen". That was an over-claim, and the
first closed-loop run made it obvious: the decoder carries an explicit `turn_sign` of -1 or
+1, so flipping one engineering number turns an approach into an avoidance. The direction
of the behaviour is therefore **not** a property of the network alone.

What *is* a property of the network, and what the operating-point search actually measured,
is narrower and still worth having: **which descending side is stronger for a given cue
side, and that this reverses when the cue moves.** The decoder then maps that asymmetry to
a turn under a declared sign convention -- turn toward the stronger side. With the pilot
operating point and that convention the fly approached the cue, walking 5.87 mm and turning
29.3 degrees toward it over 3 s, and the cue distance fell from 13.38 to 7.60 mm. Reporting
that as the network having chosen to approach would be wrong.

The acceptance contract encodes the corrected version: criterion A4 asks whether the
readout asymmetry tracks the cue side, not whether the fly went the "right" way, and the
declared limitations state that the turn direction is an engineering choice.

**D2. Entry populations.** LC4, LPLC2 (loom) and LC10a (small object), lateralised by the
released `somaSide` column. 586 bodies. All are `visual_projection` superclass, so they
cannot overlap the descending readout.

**D3. Readout populations, three tiers, all anatomically declared by type/superclass+side.**
* `dn-loom-{left,right}` = DNp02/DNp03/DNp04/DNp06, 4 bodies per side (strongest drive:
  19.95% of their input contacts come directly from LC4);
* `dn-steer-{left,right}` = DNa01/DNa02, 2 per side (the steering pair the odour route
  failed to reach);
* `dn-pool-{left,right}` = every `descending_neuron`, 656/648 per side (recorded; large
  enough that the spike quantum cannot manufacture a selectivity index).

**D4. A new searched axis: per-target synaptic normalisation.** The measured failure mode
was an antennal lobe at 181 Hz with 90% of the pool active while descending cells with
750-1200 inputs stayed silent under one uniform mV-per-contact. A single per-contact
weight cannot serve a neuron with 50 inputs and a neuron with 12,000. The new axis is

    scale[target] = (reference_in_contacts / in_contacts[target]) ** exponent

with `reference` the median incoming-contact count over neurons that have any input.
Exponent 0 reproduces the current behaviour bit for bit, so no recorded run regresses;
exponent 1 makes total synaptic drive size-invariant. Declared P/E, justified by input
resistance falling with membrane area, which is a real cable-theory argument and not a
measurement.

**D5. A declared visual receptive-field encoder (P/E).** Each eye's drive is a gaussian
on cue bearing centred at its preferred azimuth, times a Michaelis-Menten term in the
cue's angular size (the loom signal). This replaces the odour field, whose measured
bilateral contrast at the antennae was only 3.3% (0.374 vs 0.362).

**D6. The bar does not move.** C1-C4 keep the identical thresholds registered for the
failed odour contract (baseline<=5 Hz, saturation<=0.25, cue response>=2 Hz,
selectivity swing>=0.2 with reversal, recovery<=0.5, active fraction in [0.02, 0.9]) and
the identical scoring function. One criterion is **added**, which tightens rather than
loosens: C5 requires a minimum raw readout spike count per cue epoch, so the 1-spike-vs-0
signature that produced the spurious +-1.000 indices in the odour search cannot pass.

## S1 measurements that changed the design (2026-09-10)

Two of my own earlier statements this session were wrong and are corrected here.

**Wrong: "photoreceptors carry zero outgoing edges."** They carry 66,533 outgoing edges
over 4,045 of 4,114 bodies. The flow was zero for a different reason.

**Right, and decisive: every one of those 66,533 edges is zeroed by the frozen ND-10 sign
policy** -- 100.0% of edges and 100.0% of contacts, for R1-R6, R7 and R8 alike. Fly
photoreceptors are histaminergic and histamine is not in the transmitter model, so the
consensus prediction is unresolved and the `zero` policy removes them. The retina-to-
lamina synapse is therefore the one link this demo cannot execute, and inventing a sign
for 66,533 edges to enable a demo would be a larger fabrication than entering one synapse
downstream. Recorded as a limitation, not worked around.

Outgoing sign composition, measured:

| type | out-edges | exc | inh | zeroed |
|------|-----------|-----|-----|--------|
| R1-R6 / R7 / R8 | 66,533 | 0% | 0% | **100%** |
| L1 | 27,860 | 0% | **100%** | 0% |
| L2 / L3 / L4 / L5 | 425,092 | 100% | 0% | 0% |
| Mi1 / Tm1 / Tm2 / Tm9 / T4 / T5 | 1,735,557 | 100% | 0% | 0% |
| LC4 / LPLC2 / LC10a | 106,854 | 100% | 0% | 0% |

**D7 (supersedes D2). Entry is the lamina monopolar cells L1-L5, driven retinotopically.**
8,883 bodies, 69.8% carrying `assignedOlHex1`/`assignedOlHex2` (L1, L2, L5 at ~99%, L3 at
50%, L4 at 0%), hex1 spanning 1..36 and hex2 1..39 over 877 distinct left-eye columns.
Measured consequences:

* **retinotopy survives to the lobula.** Two disjoint hex patches of the left lamina
  produce LC4 response vectors with cosine similarity **+0.000** -- fully orthogonal, so
  different parts of the visual field drive different LC4 cells. Participation ratio 15-23
  of 126 LC4 cells per patch.
* **laterality is near perfect.** A left-eye patch reaches descending neurons at hop 3
  with L/R flow +2.5e-03 / -2.0e-05, index **+1.000**. Compare the odour route's -0.835
  at hop 1 and +0.140 at hop 3.
* **the whole optic lobe participates functionally, not decoratively.** 59,799 of 99,154
  optic-lobe neurons are reached at hop 1 and 99,128 at hop 2; all 1,304 descending
  neurons by hop 3.
* L1 output is inhibitory and L2-L5 excitatory, which matches the ON/OFF split of the
  lamina, so the relative L1 drive becomes a searched axis rather than an assumption.

This is what "use all the data" means here: a spatially localised visual cue lands on the
retinotopic lamina, the 99,154-neuron optic lobe computes the response, and the descending
readout is whatever that computation produces.

**D8. Normalisation attenuates only.** `scale[t] = (reference / max(in_contacts[t],
reference)) ** exponent`, so neurons with fewer than the median incoming contacts are
untouched and only the heavily converged ones are attenuated. Bounded in (0, 1], exactly
1.0 at exponent 0, and it cannot amplify a sparsely connected neuron into instability.

## S1 implementation, committed 2026-09-10

New code: `src/flysim/demo01_visual.py` (declared populations, retinal map, retinotopic
encoder, five-criterion scorer), `src/flysim/demo01_visual_probe.py` (the search),
`scripts/run_demo01_visual_search.py`, `tests/test_demo01_visual.py` (30 tests).

Engine changes, all defaulting to the pre-existing behaviour and all omitted from the model
identity while neutral, so no recorded run's identity or numbers change:

* `inhibitory_weight_gain`, default 1.0
* `adaptation_increment_mv` / `adaptation_tau_ms`, default 0.0, byte-identical kernel when off
* `synaptic_target_normalisation_exponent`, default 0.0

A real bug was fixed on the way: the probe's cue-epoch active fraction was read from the
optional timeline, so it silently became 0.0 whenever the timeline was switched off, which
would have failed the stability criterion for reasons unrelated to the network.

A 5.8x speedup: `population_activity` rebuilt a dense index and gathered counts with a
Python loop over every monitored body on every 15 ms interval, about 150,000 operations per
interval with the visual pools. Both readers now gather from one concatenated
device-synchronised array through a cached flat index. Simulation cost fell from 38.6 s to
6.6 s per 1.05 s of biological time.

### The claim this stage can support, and what it cannot

It can support: on the exact 165,122-body graph, with all 25,563,197 edges built and a hard
all-edges assertion, a retinotopically encoded visual cue drives the 99,154-neuron optic
lobe and produces cue-side-dependent, reversing, recovering activity in the 318-body
posterior descending group, at a P/E operating point chosen without any behavioural
objective.

It cannot support: anything biological. The lamina rates, the retinal map, the E/I ratio,
the adaptation and the per-contact scale are all declared engineering values. The
retina-to-lamina synapse is not executed at all, because the frozen sign policy zeroes
every photoreceptor edge. Tier stays V0 Structural.

## S1 result: the registered search passed

Run from a clean tree at commit `31736d2`, evidence-grade, artifact
`evidence/demo01/demo01-visual-operating-point-v1.json`
sha256 `1f10b63d0bd3ab8c63c7b01d7d3994ca469624b210c323dfce95a1d3152bace5`.
**31 of 108 candidates met all five criteria.**

Selected by the rule declared before the run, the largest selectivity swing inside the
passing set:

| parameter | value |
|---|---|
| synaptic mV per contact | 0.5 |
| inhibitory weight gain | 1.5 |
| spike-frequency adaptation | 0.0 mV |
| lamina maximum rate | 400 Hz |
| ON/OFF balance | 1.0 |

What it measured, against the thresholds carried over from the failed odour contract:

| quantity | measured | threshold |
|---|---|---|
| baseline descending drive | 0.000 Hz | <= 5.0 |
| cue-evoked response | 2.435 Hz | >= 2.0 |
| selectivity, left cue | +0.607 | reversal required |
| selectivity, right cue | -0.340 | reversal required |
| selectivity swing | 0.947 | >= 0.2 |
| recovery residual | 0.004 | <= 0.5 |
| descending active fraction | 0.0208 | in [0.02, 0.9] |
| readout spikes per cue epoch | 665 and 713 | >= 20 |

Which criteria actually bind, counted over all 108 candidates:

| criterion | failures |
|---|---|
| C1 stability | 62 |
| C2 cue responsiveness | 51 |
| C3 selectivity reverses | 4 |
| C4 recovery | 13 |
| C5 spike floor | 0 |

Three things in that table are worth saying out loud.

**The stability-against-responsiveness tension is the whole problem**, exactly as the pilot
found: C1 and C2 account for 113 of the 130 failures, and they fail in opposite directions.

**C3 almost never fails, which vindicates the readout choice rather than the criterion.**
Once the decoded readout moved from the whole descending pool to the 318-body posterior
descending group, lateralisation stopped being the hard part. On the odour route C3 was
unreachable at any gain.

**C5 never binds, and adding it was still right.** It exists because the odour search
produced selectivity indices of exactly plus and minus 1.000 from a single spike. On this
route the readout emits 165 to 1,162 spikes per cue epoch, so the degenerate outcome simply
never arises -- which is what a guard against a known failure mode looks like when the
failure mode has been removed by other means.

**Adaptation was not needed at the selected point.** The winner uses 0.0 mV, though 12 of
the 31 passing candidates use 1.0 mV. I added spike-frequency adaptation in response to the
pilot's latching, and at an inhibitory gain of 1.5 the network does not need it. It stays in
the engine, defaulting to off, and the honest summary is that rebalancing excitation against
inhibition did the work that adaptation was introduced to do.

**One number is marginal and is reported as such.** The descending active fraction is 0.0208
against a floor of 0.02, so the selected point sits about one part in a hundred inside that
criterion. The pilot predicted this and the grid was built to bracket it; it is a fragile
margin and it is not hidden.

## S2 in progress: what the decoder sweep has already settled

Three rows in, two findings are already firm and both are worth recording before the
selection is made, so that neither can look like a post-hoc reading.

**The turn direction is entirely the decoder's, and this is now measured rather than
argued.** Flipping the decoder's sign with everything else identical:

| yaw gain | threshold | sign | walked | mean approach | cue-locked agreement | mean turn |
|---|---|---|---|---|---|---|
| 0.80 | 0.60 | **+1** | 3/3 | **+12.07 mm** | 0.691 | 54.1 deg |
| 0.80 | 0.60 | **-1** | 3/3 | **-5.86 mm** | 0.715 | 48.1 deg |

One engineering number turns a 12 mm approach into a 6 mm retreat, while the cue-locked
agreement -- the quantity that is a property of the network rather than of the decoder --
barely moves, 0.691 against 0.715. That is exactly the correction to D1: the network
determines which descending side is stronger for a given cue side, and the decoder's sign
determines what the body does about it.

**The forward-threshold axis is degenerate at this operating point.** Rows 1 and 3 differ
only in the threshold, 0.60 against 1.20 Hz, and are identical to the last decimal in every
reported quantity. The selected operating point's cue response is 2.435 Hz, well above both,
so the threshold never binds. Half the sweep is therefore duplicated work, which is a
finding about the grid rather than about the decoder, and the sweep is being run to
completion anyway because the selection rule was declared over the whole grid before any of
it ran.

## S2 closed: the decoder, and the whole sweep

All twelve settings walked in all three development scenarios, so the declared rule reduced
to the approach ranking.

| yaw gain | sign | mean approach | sign-agreement fraction | mean turn |
|---|---|---|---|---|
| **1.60** | **+1** | **+12.61 mm** | 0.718 | 89.8 deg |
| 0.80 | +1 | +12.07 mm | 0.691 | 54.1 deg |
| 3.20 | +1 | +5.00 mm | 0.729 | 52.8 deg |
| 3.20 | -1 | -5.40 mm | 0.421 | 85.1 deg |
| 0.80 | -1 | -5.86 mm | 0.715 | 48.1 deg |
| 1.60 | -1 | -8.05 mm | 0.854 | 85.4 deg |

Each row appears once here; the forward-threshold axis produced exact duplicates, so twelve
searched settings yielded six distinct outcomes.

**Approach is non-monotonic in the yaw gain, and this is the finding that mattered.** 0.8
gave +12.07 mm, 1.6 gave +12.61 mm, and 3.2 gave only +5.00 mm. Too much steering gain
makes the fly overshoot and oscillate rather than close on the cue, so picking the largest
gain available would have made the demonstration measurably worse. That is the same shape
Track A found in its station-keeping channel, where the response also reversed past a limit,
and it is a reminder that more gain is not more control.

**The threshold never binds.** Settings differing only in it were identical to the last
decimal, because the frozen operating point's 2.435 Hz cue response sits well above both
0.6 and 1.2 Hz. The scenario records that the value is arbitrary between the two searched
rather than implying it was discriminated.

**The sign result is the cleanest statement of the corrected D1.** At the winning gain, +1
approaches by 12.61 mm and -1 retreats by 8.05 mm, while the sign-agreement fraction moves
only from 0.718 to 0.854. The lateralisation is the network's; the direction is the
decoder's.

**And one row justifies the A4 fix on its own.** The 3.2 avoidance setting scores 0.421 on
the sign-agreement fraction, below the one-half threshold my earlier implementation used,
with the readout lateralisation intact. Had the mismatch with the frozen contract not been
caught, that metric would have been failing settings for a reason unrelated to what the
criterion is about.
