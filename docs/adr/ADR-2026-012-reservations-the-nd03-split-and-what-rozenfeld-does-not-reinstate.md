# ADR-2026-012 — Reserve before opening; split ND-03; and record that Rozenfeld does not reinstate the synaptic leg

Date: 2026-09-09
Status: accepted
Changes assumptions: `ND-03` (narrowed), `ND-10` (new), `VAL-02` (new), `MOTOR-04` (validation recorded)
Assumption set: `foundation-v0.6` → `foundation-v0.7`
Supersedes: nothing. It corrects three claims made earlier the same day and withdraws no verdict.

## Context

Three things arrived together and each of them invites the same mistake, which is letting
an appealing reading of new data stand in for what the data supports.

**A failed validation that must stay failed.** The Track A station-keeping controller was
frozen at `4c4a53f` and evaluated once on twelve poses it had never seen. B2 passed 12 of
12; B3-v5 passed 8 of 12 against 10 required, so validation failed. The temptation now is
to tune against those twelve poses, or to re-score them under a softer reading, both of
which would silently convert a holdout into training data.

**A staged corpus of unopened observations.** Five datasets were staged and classified in
prose. Prose is not a record: it does not pin a file by checksum, it does not say which
variable inside a file is the holdout, and nobody can check it later.

**Three claims of my own that were wrong.** They are corrected here rather than quietly
edited, because the pattern in each is the same and it is worth naming.

## Decision 1 — Reserve in a checksummed manifest before anything is opened

`configs/datasets/stage2-reservations-v1.json` declares every reserved file and, inside
it, every reserved variable or column. `flysim stage2 reservations` builds the manifest:
per file the checksum, the byte count and the structure, then an immutable snapshot named
by its own digest. Twenty files across four datasets.

**The readers cannot return a value, structurally rather than by promise.** The MATLAB
reader parses the version 5 element headers and stops at the first data subelement, so it
reads names, shapes and classes and has no code path to a numeric payload. A version 7.3
file is HDF5 and is refused rather than guessed at. The table reader decodes the header
line and counts newlines. The archive readers list entries.

**Two guards make the manifest more than paperwork.** Every reserved name must exist in
the file, so a renamed source is caught rather than silently unreserved; and every name
that exists must be either reserved or explicitly declared unreserved, so nothing escapes
by omission. Both are executable and both are tested.

**Join keys are deliberately unreserved.** A holdout is spent by seeing the measurement,
not by seeing which cells were measured. `cell_type`, `cell_type_mcns` and the
cross-matching table are readable, which is what made it possible to answer a feasibility
question — see Decision 3 — without spending anything.

**Reading analysis code is not reading a value, and it is recorded that it happened.** The
Rozenfeld MATLAB scripts were read in full. They are code, they decode no observation, and
they are what settled Decision 2.

## Decision 2 — The synaptic leg stays retired, and the gate stays at v4 and 0 of 3

ADR-2026-011 retired the synaptic leg with a written reinstatement condition: *"Raw
unitary EPSC traces become available from a preparation not used to fit the kernel."*

**The intake claimed Rozenfeld 2023 matched that condition. It does not.** The
determination, from the authors' own code and filenames:

- The Figure 3 arrays are **evoked** responses. `Figure_3.m` labels the latency panels
  "eEPSC latency", and the amplitudes "EPSC amp (pA)", from stimulation of the ORN axon
  bundle. An evoked compound EPSC recruits many ORNs at once; a unitary EPSC is one ORN.
- The Figure 1 raw traces, `IAA_IC` and `IAA_VC` at 22 by 70001 samples, are **odour**
  responses to isoamyl acetate. `Figure_1.m` plots the same preparation as firing rate in
  spikes per second. Odour-evoked whole-cell responses confound the synapse with the
  ORN drive that arrives at it.
- The Figure 5 minis are **quantal** events. A single-vesicle amplitude is not the unitary
  response of a connection.

So there is no unitary cohort here, the condition is unmet, and the leg is not reinstated.
`configs/experiments/stage2-exit-gate-v4.json` is **left unedited**. The Stage 2 exit gate
stays 0 of 3, and the v3 verdict of 0 of 4 stays as recorded.

**How the claim went wrong is the part worth keeping.** The intake paraphrased the
condition as "raw traces from a preparation not used to fit the kernel" and dropped the
word *unitary*, which is the entire content of the condition. A paraphrase of one's own
acceptance criterion is where criterion drift starts, and this is the second time in two
days that a paraphrase has done real damage here.

**What the dataset does test is registered separately.** The retired leg's own caveats
already said what it left untested: *"even a pass would leave release failure and
short-term plasticity untested."* That is ND-06, and
`configs/experiments/stage2-depression-external-test-v1.json` preregisters it.

## Decision 3 — Split ND-03 into transmitter identity and receptor-dependent polarity

The old `ND-03` was named "functional edge polarity" and its policy was
"transmitter-plus-postsynaptic-receptor". One record therefore carried a quantity that can
be measured at scale and a quantity that cannot, and every contract that cited it for an
edge's sign was leaning on the half that cannot.

| record | what it is | provenance | can it be validated? |
|---|---|---|---|
| `ND-03` | presynaptic transmitter identity, per body, from the connectome annotation | `M/P` | **yes**, and a validation set is now reserved |
| `ND-10` | postsynaptic receptor identity and functional edge polarity | `P/F` | **no**, not at connectome scale |

**What the verified assignments can and cannot do.** (The count stated in this
paragraph is corrected by the third amendment below: the joinable set is about 205 rows
over roughly 181 MaleCNS cell types, not 6,107.) They pin the presynaptic
transmitter. They cannot measure an edge's sign, because a correct transmitter label still
leaves the sign unresolved wherever the postsynaptic receptor is unknown, and receptor
identity is partner- and dendritic-domain-specific rather than cell-specific. An agreement
rate on transmitter identity is an **upper bound** on sign correctness, not a measurement
of it. The intake said the dataset makes "ND-03 sign assignment testable"; it makes
transmitter identity testable, which is a real and smaller thing.

**A feasibility question closed while classifying.** The intake recorded an open question
about how MaleCNS types are reached, because `cell_type_cross_matching.csv` has columns for
FAFB, hemibrain, BANC and L1 and none for MaleCNS. The join does not go through that
table: `gt_sources/male_cns/202509-male_cns_gt_data.csv` carries a `cell_type_mcns` column
across 3,523 rows. Established from headers and row counts, so nothing was spent.
(Corrected by the third amendment: 158 of those 3,523 rows carry a MaleCNS cell type.
Establishing it from a row count rather than from the column is exactly the error.)

**Edge sign stays unresolved where receptor evidence is absent.** That is not a pending
action, it is a boundary: the measurement required exists for a handful of visual-system
neurons, the MaleCNS `receptorType` annotation has 752 non-null entries and all of them are
gustatory, and no bulk expression atlas can supply a partner-specific quantity. The
transmitter-only sign rule in `polarity.py` remains what it already was — a named
regression control, not the physiological default.

## Decision 4 — The Track A failure is preserved, in code as well as in prose

The twelve validation poses are spent. Seed 20260910 is listed in
`flysim.station_validation.SPENT_VALIDATION_SEEDS` with the outcome it produced, and the
draw refuses it both for development, which would make it training data, and for
validation, which would be a second attempt at the same poses. An explicit `reproduce`
purpose still redraws the poses for inspection and produces no artifact.

A successor controller is **MOTOR-05**, not an edit to MOTOR-04: a new development set and
a separately frozen validation set, drawn from two new registered seeds, both registered in
the same commit before tuning begins. MOTOR-04's registry record now carries the failed
validation, and it stays there whatever MOTOR-05 achieves. A later success does not
withdraw an earlier failure; it is a second result about a different controller.

## Decision 5 — Takagi 2024 is sealed until a circuit-level contract exists

No value in it may be opened. The seal lifts only on a committed contract that states the
circuit prediction, the observation model from calcium fluorescence to the quantity the
simulator produces, the species assignment of every calcium-imaging file, and the
acceptance limit. The stage-3 activity-prediction design is **not** that contract: it was
written when the target was believed not to exist, so its hypotheses aim at published
population summaries rather than at matched per-glomerulus responses, and scoring new files
against criteria written for different observables is how criteria come to be chosen after
the data is in hand.

## Decision 6 — The observation model is registered as an assumption, `VAL-02`

Scoring a resource-depletion model against a compound evoked EPSC requires four things to
be true that are all false in detail: linear summation, identical recruitment on both
pulses, no receptor desensitisation, and amplitude ratio equal to resource ratio. Leaving
them implicit would have hidden them inside a "measurement".

**Amended the same day, before any value was opened — see the amendment at the end of
this record.** The paragraph that stood here claimed the direction of every bias was known
and ran the same way, and concluded that a measured ratio above the prediction could not be
explained by observation error. It is withdrawn. Saturation raises a measured ratio, because
the transfer from released vesicles to current is concave and compresses the larger first
response more than the smaller second one; desensitisation lowers it; recruitment can do
either. No direction of disagreement is privileged.

What survives is weaker: every one of these effects shrinks as the interval grows, because
receptor occupancy recovers and the second response stops riding on the decay of the first.
That, and not a one-sided bias, is why the primary test sits at 100 ms.

## What is not decided here

- **No verdict moves.** V0 Structural remains the highest supported tier. The Stage 2 gate
  is 0 of 3. Track A is not an accepted milestone. B1 and B4 are still unmeasured and the
  renderer timing amendment still fails.
- **No value is opened.** The depression contract is preregistered and unexecuted.
- **No parameter is refitted.** The registered ND-06 values stand, including through a
  second external test, for the reason the first failure was recorded under: refitting to
  an external test converts the only external check into a training set.

## Consequences

- `configs/scenarios/eon-malecns.json` requires `ND-10` alongside `ND-03`, so any run that
  asserts edge signs records the boundary it asserts them under.
- Gate contracts and neural configs that cite `ND-03` are **not** edited. They inherit the
  narrowed meaning, and where they assert a sign the boundary is `ND-10`. Editing pinned
  contracts to add an id would change checksums for no gain.
- `configs/neural/short-term-plasticity-v0.1.json` gains a machine-readable
  `published_fits` list. It adds no information — the same three fits already appear in the
  range derivations as prose — but it makes the prediction band computable without mixing a
  utilisation from one pharmacological component with a recovery constant from another.
- The V0 evidence bundle is unaffected: it is gated on `DATA-*` record content and never on
  the set identifier, which is exactly the case ADR-2026-006 designed for.

## Amendment, 2026-09-09 — the observation bias is not one-directional

Recorded before any reserved value was opened, so no measurement was interpreted under the
withdrawn reasoning.

**Withdrawn text, preserved verbatim:** *"Receptor saturation, receptor desensitisation and
presynaptic recruitment failure all deepen a measured ratio relative to vesicle depletion
alone, so all three bias the measurement downward against the prediction. A measured ratio
ABOVE the prediction therefore cannot be explained by any of them."*

**Why it was wrong.** Postsynaptic receptor saturation biases a measured paired-pulse ratio
*upward*, not downward. The transfer from released vesicles to measured current is concave,
so the larger first response is compressed more than the smaller second one and the measured
amplitude ratio exceeds the underlying release ratio. Desensitisation biases it downward.
Recruitment has no safe direction: failure of stimulated axons to fire again lowers the
ratio, stimulus-dependent changes in axonal excitability can raise it, and variable
recruitment adds variance with no sign at all.

**Why it mattered.** The withdrawn claim was a one-directional escape hatch. It would have
licensed reading a high measured ratio as agreement with the model while attributing a low
one to the apparatus, which is the same shape as the criterion drift this project has had to
repair before.

**What changed and what did not.** No numeric prediction, no criterion and no threshold
moved. The 0.7700 floor is unchanged and the 100 ms interval is still primary — its
justification is now reduced response overlap, since at 10 and 30 ms the second response
rises from the decay of the first and its amplitude depends on a baseline convention the
source code does not state. What narrowed is the inference: a failure against these
recordings establishes that the registered **single-resource rule as parameterised** does not
predict compound evoked ORN-to-PN paired-pulse and train ratios under `VAL-02`. It is **not**
a falsification of presynaptic vesicle depletion, which has independent support this test
does not touch in Kazama and Wilson's 1/CV² correlation at r = 0.79.

`VAL-02` also gained an explicit `postsynaptic_saturation_contributes_nothing` clause, so the
assumption is listed rather than hidden inside "linear summation", and its validation field
now names the control that would bound it: a low-affinity competitive antagonist that
relieves receptor occupancy without changing release.

## Second amendment, 2026-09-09 — the recordings are minimal stimulation, and the leg's reason changes

Recorded after the wild-type paired-pulse arrays were opened and scored, and it changes no
verdict: the leg stays retired and the gate stays 0 of 3.

**Withdrawn factual claim, preserved verbatim from Decision 2:** *"The Figure 3 arrays are
evoked responses. `Figure_3.m` labels the latency panels 'eEPSC latency', and the amplitudes
'EPSC amp (pA)', from stimulation of the ORN axon bundle. An evoked compound EPSC recruits
many ORNs at once; a unitary EPSC is one ORN."*

**What the paper says.** *"eEPSCs were evoked by stimulating ORN axons with a minimal
stimulation protocol via a suction electrode."* Minimal stimulation is the standard method
for isolating a single-fibre response, so these are unitary, not compound. Decision 2 read
the authors' plotting code and inferred the preparation from a label; the methods section was
in the local corpus and says it outright.

**Why the leg still stays retired, restated.** The condition is raw unitary EPSC **traces**
from a preparation not used to fit the kernel. The staged repository ships per-animal
*scalars* — paired-pulse ratios — and per-animal *averaged amplitudes* across a 32-pulse
train. The only raw traces in it, Figure 1's `IAA_IC` and `IAA_VC`, are odour-evoked
whole-cell recordings rather than minimal-stimulation eEPSCs. A kinetics holdout that scores
peak time and decay without peak alignment cannot be built from scalars. This is a sharper
statement than the withdrawn one and it names what would satisfy the condition: the authors'
minimal-stimulation waveforms, which the repository does not contain.

**What it changes for `VAL-02`.** Nothing in the record itself; its two-directional bias
account stands and is general. What changes is its weight for these particular data.
Minimal stimulation produces small responses precisely to stay off the saturating part of the
postsynaptic curve, so the upward bias that would otherwise be the leading alternative
explanation of a measured ratio above the prediction is weak here, and the failure is
correspondingly **more** attributable to the model. The 10 ms overlap concern is also
answered by the methods, which measure the second response *"from the peak to the point of
interception with the extrapolated first response"*.

**The lesson worth keeping.** Both errors came from inferring a preparation from analysis
code and variable labels while a methods section sat unread in the local corpus. Published
prose is not a reserved observation and reading it costs nothing. The reservation discipline
protects values; it was never a reason not to read the paper.

## Third amendment, 2026-09-10 — the transmitter validation set is about seventeen times smaller than recorded

Decision 3 split `ND-03` and claimed a validation set for the half that is testable. The
claim about that set's size was wrong, in the flattering direction, twice over.

**What was written.** Above, under Decision 3: "the MaleCNS-specific ground-truth slice
resolves it: MaleCNS cell types are reached through that file's `cell_type_mcns` column
… across 3,523 rows." And: "the 6,107 verified assignments … pin the presynaptic
transmitter." The registry record repeated both numbers.

**What is actually there.** Measured on 2026-09-10 from unreserved columns only —
`species`, `region`, `hemilineage`, `cell_type_source`, `gt_celltype`, `cell_type_mcns`
and `cell_type`, every one of them declared unreserved by the reservation contract on the
recorded ground that a holdout is spent by seeing the measurement and not by seeing which
cells were measured. No transmitter column was opened.

| file | rows | joinable on a MaleCNS cell type | distinct types |
|---|---|---|---|
| `gt_sources/male_cns/202509-male_cns_gt_data.csv` | 3,523 | **158** | 135 |
| `gt_sources/male_cns/malecns_extra.csv` | 47 | 47 | 46 |
| `gt_data.csv` (parent) | 6,107 | **0** — no MaleCNS column | — |

The 158 joinable rows are 134 optic lobe and 24 central brain. The older file's 47 are 30
midbrain and 17 optic lobe. The parent table's 6,107 rows include 804 larval rows, which
cannot validate an adult connectome under any join.

**So the two errors were.** First, 3,523 is that file's *total* row count, not the number
carrying a MaleCNS cell type; the header said the column existed and the row count was
read off the file rather than off the column. Second, 6,107 is the parent table's row
count and it is not joinable by MaleCNS cell type at all, so it was never a validation set
for this connectome in the first place.

**What it changes.** The joinable set is about 205 rows over **169** distinct MaleCNS
cell types — 135 from the current slice and 46 from the older file, twelve of which appear
in both, which is why the first arithmetic here said 181. Of those 169, 89 match an
optic-lobe naming pattern and **exactly zero** match any antennal-lobe pattern: no `ORN_`,
no `HRN_`, no uniglomerular or multiglomerular projection neuron, no antennal-lobe local
neuron. The remainder is largely central complex. That was measured against the naming
conventions rather than estimated, and cell type names are unreserved so it spent nothing.

It is still a real validation set and worth scoring: an agreement rate over 169 types with
a Wilson interval is a measurement where the project currently has none. What it is not,
and not by a narrow margin, is a validation of the transmitter labels in the circuits this
project models. `ND-03` will remain unvalidated precisely where stage 2 and stage 3 use
it. That is why the contract this amendment accompanies,
`stage2-nd03-transmitter-validation-v1`, requires the coverage to be reported
neuron-weighted and edge-weighted as well as type-weighted, and makes the coverage report
a hypothesis of its own with no pass condition so it cannot be dropped from a write-up.

**What it does not change.** The split itself, which was the substance of Decision 3 and
which this makes more rather than less necessary. `ND-10` is untouched: it claimed no
validation set and the test suite asserts it still claims none. The reservation regime is
untouched and did its job here — the error was in a prose count, and it was caught by
measuring the column rather than by trusting the header.

**The general lesson, recorded because it has now happened twice.** A row count is not a
column count. The first Rozenfeld error was inferring the preparation from a plotting
label instead of reading the methods; this one is inferring a join size from a file size
instead of reading the column. Both were cheap to check and neither was checked, and in
both cases the unchecked version was the one that made the project's position look better.

The assumption set moves `foundation-v0.7` → `foundation-v0.8`. `VAL-03` is added in the
same revision as a named, deliberately unspecified record, so that the restricted stage-3
contract's dependence on a calcium observation model is visible in the registry rather
than only inside that contract.
