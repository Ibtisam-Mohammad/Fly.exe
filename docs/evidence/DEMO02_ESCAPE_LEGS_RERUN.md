# The escape-legs matrix, re-run from one commit with every control present

The first evidence produced under the repaired orchestration (`ADR-2026-018`). Twenty one
runs: three seeds, seven variants each, one variant per process, all at commit `50a64be`.
Tier unchanged at V0 Structural.

## What it establishes about the orchestration, which is the point of it

| property | before | now |
|---|---|---|
| seeds executed | 1 of 3 | 3 of 3 |
| acceptance artifacts | one unsuffixed file, no seed field | one per seed, plus a combined file |
| commits per matrix | up to 4 | 1 |
| required controls present | 5 of 7 | 7 of 7 |
| `chain_is_sound` | not recorded | `true` on all three seeds |

Each seed carries two build keys and two compiled kernels, one for the intact wiring and one
for the shuffle, and all six differ. That is the `GeNN bakes seed and wiring into the code`
property behaving as it should.

**Command replay now matches the run it replays exactly: 400 of 400 intervals at zero lag,
first nonzero command at row 234 in both.** Before the fix it was 398 at zero lag and 399 at
lag +1, with the first nonzero command at row 234 in the exact run and 235 in the replay.

## The verdicts

**NO DEMONSTRATION on all three seeds.** `E1` fails on every one, and the reasons differ:

    seed   airborne      z rise    roll     E1     E2   E3   E4     E5     E6    E8
      1     17,000 us   1.617 mm   --      FAIL   PASS PASS FAIL   PASS   FAIL  PASS
      2  3,276,000 us   2.065 mm   180.0   FAIL   PASS PASS FAIL   FAIL   FAIL  PASS
      3  1,735,500 us   1.796 mm   179.4   FAIL   PASS PASS FAIL   FAIL   FAIL  PASS

Seed 1 hops for 17 ms against a 20 ms threshold. Seeds 2 and 3 invert, and their enormous
airborne counts are time spent on the fly's back, which the contract's roll clause catches --
that clause is the reason those two read as failures rather than as spectacular successes.

`E2` and `E3` pass on every seed: the readout-ablated and stimulus-absent runs never reach
ACTING and rise 0.204 mm against a 0.35 mm limit. `E8` passes on every seed at exactly 0.0
peak wing command. `E4` fails on every seed, which the contract predicted before the run,
because the encoder computes angular size and not expansion rate.

`E5` passes on seed 1 (60,000 us gap against a 75,000 limit, 1 of 250 spikes before the
window) and fails on seeds 2 and 3 -- on seed 2 at a 90,000 us gap, and on seed 3 because no
giant-fibre spike falls inside the approach window at all.

## A correction to what was said on 2026-09-11

On 2026-09-11 this experiment was reported as "seeds 1 and 3 land upright; seed 2 still
tumbles", and `E5` as "passing on two seeds". **Both statements were wrong.** Seeds 2 and 3
invert and `E5` passes on one seed.

They were wrong for precisely the reason the review identified: they were read off console
output at a time when three seeds were overwriting a single unsuffixed acceptance file, so no
artifact ever held the per-seed picture and nothing could be checked afterwards. The one
surviving artifact described seed 1.

## The repairs did not move the plant, and here is the check

New seed 1 reports **17,000 us airborne and 1.617 mm of rise**, which reproduces the
surviving 2026-09-11 `demo02-escape-legs-v1` artifact exactly, at the same build key and the
same compiled kernel.

A first comparison appeared to show the plant had moved, against the recorded
`demo02-escape-v2` runs. That comparison was invalid and is recorded rather than deleted:
`demo02-escape-v2` carries no `adr` key and therefore **commands the wings**, while
`demo02-escape-legs-v1` carries `ADR-2026-017` and withholds them. The two contracts were
never comparable, and the difference between them -- a long airborne count with an inverted
body against a 17 ms hop -- is exactly the effect `ADR-2026-017` exists to record.

The only body change between those runs and these is this session's own commit, which adds an
inert dataclass field, an early return reached only by the grooming replay control, and a
read-only finiteness check that raises or does nothing.

## What this does not establish

That the fly escapes. `E1` fails on three seeds of three. The 20 ms airborne threshold was
frozen before anyone measured a hop, and 17 ms against it is a miss and is recorded as one;
it is not evidence that the threshold is wrong, and the threshold is not moving.

Nothing here bears on grooming or feeding. The feeding contract cannot run until its route
has an operating-point search, and `demo02-grooming-v1` names an `entry-swapped` control that
is now refused rather than silently executed as a copy of the exact run.
