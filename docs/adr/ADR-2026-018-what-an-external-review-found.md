# ADR-2026-018: What an external review found, and the eleven things it was right about

Date: 2026-09-12
Status: accepted 2026-09-12. Assumption set `foundation-v0.9` → `foundation-v0.10`.

```yaml
decision_id: ADR-2026-018
date: 2026-09-12
changes_assumptions: [MOTOR-07, NUM-01]
supersedes_contracts: [demo02-feeding-v1, stage3-antennal-lobe-restricted-v1]
suspends_claims: [DEMO-01 A5 topology-specificity]
retires_terms: [V1-limited, V2-restricted]
old_decision: >-
  DEMO-02 was reported as three behaviour matrices with recorded verdicts, the
  short-term-plasticity module carried a V1-limited tier, DEMO-01 carried a
  TOPOLOGY-SPECIFIC verdict, and the Stage 3 antennal-lobe contract was prepared and
  sealed awaiting four preconditions.
new_decision: >-
  Every one of those is amended. The feeding readout was biologically reversed and is
  corrected under MOTOR-07 with demo02-feeding-v2. The DEMO-02 runner executed one seed of
  a three-seed contract and wrote every seed to one artifact path, so no multi-seed claim
  was ever supported and none is made. V1-limited and V2-restricted were never members of
  the formal ladder and are removed. DEMO-01's A5 is suspended. The Stage 3 contract is
  superseded by a v2 that matches its intervention to the mechanism and its hypotheses to
  the data that exist.
reason: >-
  An external review on 2026-09-12 read the repository at 3aff09d and found them. Twenty
  three of its twenty six specific claims were confirmed against the code, the recorded
  artifacts and the primary sources; three were overstated in detail and correct in
  substance. Not one of the critical findings was wrong.
```

## Why this ADR is written the way it is

Because the review was right and the repository's own guards were not enough. Every defect
below sat behind a clean worktree, a passing test suite, a validating evidence bundle and a
verified graph hash. None of those instruments can detect a population decoded under the
wrong name, a loop that runs one seed of three, or a tier that was never a tier.

This is the same lesson `fly-brain-verify-dont-infer` records for data, now demonstrated for
code and for biology. The guards check **provenance and identity**. They never check
**whether the quantity is the quantity**.

---

## 1. The feeding readout was reversed (MOTOR-07)

`demo02.py` decoded `MN10`, `MN11D`, `MN11V` and `MN12D` as proboscis extensors and recorded
`MN9` as the pharyngeal pump. That is backwards.

McKellar and colleagues (eLife 2020;9:e54978) partition the sixteen proboscis muscles into
eight positioning muscles — **1, 2D, 2V, 3, 4, 6, 7, 9** — and eight pharyngeal muscles —
**5, 8, 10, 11D, 11V, 12D, 12V, 13**; state that muscle 9 is a protractor of the rostrum
whose motor neuron elicits proboscis extension; and fix the convention that a motor neuron
is named after its muscle. Schwarz and colleagues (2017) independently place muscle groups
5, 10, 11 and 12 on the pharyngeal pump.

**The release could have refuted this and did not.** MaleCNS records `exitNerve` for motor
neurons. `MN9` exits by the **pharyngeal** nerve, which reads as pump evidence — and
McKellar's Table 1 puts the mn9 axon in that same nerve while its muscle positions the
rostrum. The nerve does not partition the two functions; the muscle list does. The check was
run before the correction was applied.

**What it cost.** In the recorded `demo02-feeding-v1` matrix the decoded pool produced
**zero** raw spikes in all 600 intervals of every variant. `MN9` produced **10** in exact,
**10** in readout-ablated — ablation zeroes only the decoded populations, and `MN9` was not
one, so that control was vacuous — **0** in stimulus-absent and **0** in shuffled-connectome.
The correct readout was firing, in a stimulus-gated and topology-gated way, and the artifact
called it the pump.

**What is not claimed.** Ten spikes in nine seconds from two cells is about 1.1 Hz and is not
a demonstration of anything. It establishes only that the readout is reachable from this
entry, that its activity needs the stimulus, and that it needs the wiring.

**ADR-2026-016 flagged this mapping as `UNVERIFIED-IN-REPO` and chose the readout on it
anyway.** Writing the words "not yet checked against a source in this repository" next to a
claim, and then building on the claim, is worse than not noticing: the doubt was recorded
and discarded in the same document.

`demo02-feeding-v1.json` is **not edited**, so its blob hash and the `experiment_sha256` in
every v1 run summary still agree. `demo02-feeding-v2.json` supersedes it, carries `F1`
character for character because a failed criterion may never be restated weakened, and
**declares itself unrunnable** until a registered operating-point search for this route
exists. There is none.

## 2. The three-seed evidence chain did not exist

`run_demo02_behaviour.py` loaded the contract's seed set and executed `seeds[0]`. Passing
`--seed N` shrank the set to one element, which selected the **unsuffixed** artifact path —
the name reserved for a single-seed contract — so each seed overwrote the last. The
surviving file carried no seed field at all.

Measured on the data root: `demo02-escape-legs-v1-acceptance.json` is one file with no seed,
no commit, no contract hash and no per-variant provenance; `demo02-escape-v2` has twelve run
directories and **no acceptance artifact at all**; the `demo02-escape` matrix spans four
commits (`ac5c024f`, `59101111`, `274921db`, `cd3e448d`); seed 1 of the legs matrix spans
two. The legs contract names `shuffled-connectome` and `command-replay` and neither was run,
and because no criterion consumes them their absence left `unscored_required` empty.

So **the statement that the contracts were evaluated on three seeds is withdrawn.** It was
read off console output, not off any artifact.

Repaired: the runner loops every seed; artifact names follow what the *contract* declares
rather than how many seeds an invocation runs; each verdict now carries its seed, commit,
contract hash, per-variant provenance and run directories; a `required_controls` list is
enforced; and a new **`EVIDENCE CHAIN BROKEN`** verdict fires when the variants disagree on
commit, seed or contract, when any was run dirty, or when a required control is missing. It
sits below the two failure branches, because a broken chain does not rescue a failed run.

## 3. The Stage 3 antennal-lobe contract could not be scored

Two independent faults, and the sealed data are untouched by both.

**The intervention does not match the mechanism.** The circuit is ORN→PN, ORN→LN, LN→PN and
LN→LN. `S2` deletes LN→PN edges and calls that the model's counterpart of GABA-A and GABA-B
blockade. Adult antennal-lobe gain control is substantially **presynaptic inhibition at ORN
terminals** (Olsen and Wilson 2008), which the edge list omits — and the contract's own
precondition `P2` records that Olsen and Wilson has never been read into the parameter
corpus.

**The observable does not match the data.** Takagi and colleagues 2024 is an OSN-expansion
and PN-**adaptation** paper. The intake manifest describes the blockade file as one figure
of VM5d PN pulse responses; the dose-response curves `S1` and `S2` need are listed
separately and this contract **seals them**. So the registered power-law exponent has no
source array behind it.

Superseded by `stage3-antennal-lobe-restricted-v2.json`. Nothing was opened and nothing is
spent.

## 4. A5 is suspended and TOPOLOGY-SPECIFIC is withdrawn

`SHUFFLE_CONTROL_REGIME_MATCHED.md` showed on 2026-09-11 that the degree-preserving shuffle
does not preserve the operating regime, and that at matched activity it drives the readout
just as hard while reproducing none of the lateralisation. That document then declined to
withdraw DEMO-01's claim, reasoning that a frozen recorded verdict is a different thing from
a live claim on a different route.

Both halves of that reasoning are true and the conclusion was wrong. A recorded verdict stays
on the record. A **claim** does not stay in force once its instrument has been shown to be
confounded. `A1` to `A4` are untouched and **FULL-GRAPH CAUSAL EMBODIMENT** stands.

## 5. `V1-limited` and `V2-restricted` were never tiers

The ladder is `V0` to `V8` in `flysim.evidence.ValidationTier`. Neither name is a member, no
evidence bundle awards either, and the short-term-plasticity registry argued itself out of
V2 on the grounds that "nothing here is a circuit-level activity prediction" — a misreading
of AGENTS.md, which defines **V2 Synaptic** by observable class ("sign, unitary amplitude,
kinetics, failure and short-term plasticity for mapped pairs") and not by circuit scale.

Both names are removed from the registry, four contracts, three documents and four test
assertions. The STP work is recorded as what it is: a frozen phenomenological candidate that
passed one out-of-sample consistency test against a refuted null, whose criteria a
zero-parameter cohort mean also clears, which misses the external 7 Hz check by roughly
threefold, and which **is implemented in none of the three simulation engines**. No tier.

## 6. Command replay ran one interval behind

The replay loaded row *k* of the exact trace into `pending`, which the body applies at step
*k+1*. Measured on the recorded escape pair: the first nonzero command is row 234 in exact
and row 235 in the replay. No recorded verdict consumed it, so nothing is withdrawn — the
control was simply never sound. It now overwrites the applied command at the top of the
interval it belongs to.

## 7. Trace rows mixed biological times

One row carried start-of-interval sensors beside end-of-interval neural output and body
state, under a single end-of-interval stamp. `E5` is unaffected because both its anchors are
end-stamped; a sensor-anchored latency would not have been. Rows now carry `t_start_us`,
`t_sensors_us`, `t_neural_us` and `t_body_us` beside `t_us`.

## 8. Acceptance could score a stale summary against a partial trace

The recorder truncates `trace.jsonl` on open; `summary.json` is replaced only on success. A
killed run leaves a short trace beside the previous summary and nothing compared them. The
summary now records `trace_rows` and `trace_sha256`, and `read_variant` refuses the pair.

## 9. Two controls were silent no-ops

`entry-swapped` and `suppress-groom-replay` sat in the variant list with no branch anywhere,
so running either executed the **exact run under a control's name**. `suppress-groom-replay`
is now implemented — the command is still decoded and the published trajectory never reaches
the actuators, which is what makes it a paired control. `entry-swapped` needs a matched input
rate nobody has measured, so it is **refused loudly**, like `controller-only`.

## 10. The registered sensory delay was never realised

`NUM-01` registers a 2000 µs sensory delay quantised to one coupling interval. DEMO-02 bound
every channel at **zero** and reported a single `sensorimotor_delay_us` without saying which
leg supplied it. The sensory delay is now declared per contract, must be a whole number of
intervals, and every summary records both legs plus a `deviates_from_num01` flag. Contracts
frozen before today carry no key, keep zero, and their own text stays true of the runs that
scored them.

## 11. Four smaller defects with the same shape

- `read_outputs` cached its flat index on the **number** of ids, so two equal-length readout
  sets collided and the second returned the first one's spikes under its own names.
- The NumPy LIF initialised every neuron at the **global** resting potential before binding
  per-neuron `resting_mv`, leaving an unregistered transient at the head of every
  heterogeneous run — invisible in a homogeneous one, which is why the parity fixtures
  passed.
- **MuJoCo does not stop on non-finite acceleration.** It logs, resets the offending state
  and continues, so a diverged integrator produces a finite trace, a clean commit and a
  passing provenance chain. One such warning is in this repository, at 0.0545 s of a run
  nobody can now identify. The body raises instead.
- `flysim stage2 exit-gate` defaulted to the unversioned contract whose id is
  `stage2-exit-gate-v1`, so the public command reported a different project status from
  AGENTS.md and from every recorded artifact. It defaults to v4.

`MUJOCO_LOG.TXT` was committed by accident and is untracked. CI gains a coverage floor at 56
per cent, set just under the 56.4 measured today rather than at an aspirational number,
because a floor nobody can meet gets deleted.

---

## What the review got wrong, recorded so it is not repeated as fact

- **"The Stage 2 exit gate does not execute the simulator."** One of its three legs does: the
  circuit leg runs the 41-neuron Shiu transfer. The criticism of the gate's *composition* is
  fair; this sentence is not.
- **"Row-time mixing directly affects the 30 ms and 75 ms latency gates."** It does not. Both
  `E5` anchors are end-stamped. The defect is real and this consequence is not.
- **"Command replay being one step late breaks the claimed evidence."** No recorded verdict
  consumes `command-replay`.

## What the review missed

- `MUJOCO_LOG.TXT` is **committed**, not merely present.
- The missing finiteness check is **fail-open**, not merely absent, because MuJoCo silently
  repairs and continues.
- `--seed N` selecting the unsuffixed artifact path is the specific mechanism by which three
  seeds overwrote one file; the review saw the symptom.
- The `readout-ablated` control for feeding was **vacuous**, not merely mismapped.

## Validation effect

**None.** No tier moves. `V0 Structural` stands and remains the only supported stage tier.
The Stage 2 exit gate stays `v4` at 0 of 3. Stage 3 stays sealed and unspent. DEMO-01 keeps
its causal-embodiment verdict and loses its topology qualifier. DEMO-02's escape and grooming
verdicts stand as recorded; its feeding **interpretation** is withdrawn and its multi-seed
claim is withdrawn.

Two of these repairs **remove** a claim the project had been making. That is the point.

## What must happen before DEMO-02 evidence is quoted again

1. A registered operating-point search for the tarsal-taste to `MN9` route. None exists.
2. Every behaviour matrix re-run from **one** commit, one seed at a time through the fixed
   orchestration, with every required control present. **Done for `demo02-escape-legs-v1`**
   at `50a64be`: 21 runs, three seeds, seven variants, `chain_is_sound` true on all three,
   NO DEMONSTRATION on all three. It corrected a 2026-09-11 statement in the process -- seeds
   2 and 3 both invert and `E5` passes on one seed, not two -- and seed 1 reproduced the
   surviving artifact exactly, so the repairs did not move the plant. See
   `docs/evidence/DEMO02_ESCAPE_LEGS_RERUN.md`. Grooming and feeding are NOT re-run: feeding
   has no operating point and grooming names a control that is now refused.
3. `entry-swapped` implemented or struck from `demo02-grooming-v1`'s control list in a
   superseding contract.

Until then the honest statement is that DEMO-02 has one route-level negative it can defend
(grooming, not side-selective at any of 36 searched points), one demonstration that fails on
a threshold frozen before anyone measured the hop (escape), and one behaviour whose readout
was wrong and whose replacement has not been run.

Last reviewed: 2026-09-12
