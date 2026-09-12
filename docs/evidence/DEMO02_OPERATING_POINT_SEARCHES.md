# Two operating-point searches, and a criterion I weakened while claiming I had not

Both searches ran on the full 165,122-neuron graph, neural criteria only, with the behaviour
contracts sealed and unreadable by either probe. Tier unchanged at V0 Structural.

| search | candidates | passed as scored | usable |
|---|---|---|---|
| `demo02-escape-operating-point-v1` | 36 | 11 | **yes** |
| `demo02-grooming-operating-point-v1` | 36 | 1 | **no, the pass is degenerate** |

## Escape: the route carries, and one boundary value was the whole earlier negative

Selected `lamina_max_rate_hz 800, synaptic_mv_per_contact 0.40, inhibitory_weight_gain 1.0`.

    baseline    left object (L,R)   right object (L,R)   recovery   descending active
         0           78, 0               0, 115              0          10.6%

Perfect ipsilateral separation, which is what zero cross-side edges from `LC4` and `LPLC2`
predicts. Every `lamina_max_rate_hz = 400` candidate produces exactly zero -- and 400 is the
value DEMO-01 selected, at the top of its own searched grid. A search that selects a boundary
value has told you its range was too narrow.

## Grooming: the route carries drive and is not lateralised

The measurement that motivated the search: 30.2 per cent of the grooming readout's input
contacts were active while it produced zero spikes. The measurement that explained it: the
readout has **474 net excitatory contacts per cell** against the giant fibre's 5,177 and the
DNp loom pool's 5,875, at a similar E/I ratio, with only 1.5 per cent of its input unsigned --
below the 2.6 per cent network average. Starved of drive, not of sign. `ND-10` is not the
cause.

Raise the drive far enough and it does respond. At `antennal_max_rate_hz 2000` the readout
reaches 100+ spikes. It never becomes side-selective:

    1500  0.70  1.50   left (38,35)    right (0,0)    swing  0.041
    2000  0.90  1.75   left (89,80)    right (0,0)    swing  0.053
    2000  0.90  2.00   left (100,106)  right (0,0)    swing -0.029

A left deflection drives both readout sides nearly equally and a right deflection drives
almost nothing. That is a fixed anatomical asymmetry, not stimulus-side selectivity, and the
contract predicted it before the run: the grooming subclass supplies eleven direct edges in
total and the largest bundle runs contralateral.

## The one passing candidate is the degenerate case, and my own criterion let it through

Selected `antennal_max_rate_hz 2000, synaptic 0.70, inhibitory 1.50`, swing -1.015.

    left-cue epoch    groom-dn-left 32   groom-dn-right 33   total 65
    right-cue epoch   groom-dn-left  1   groom-dn-right  0   total  1

`index_right` is **+1.000 from one spike against zero**. That is precisely the outcome
DEMO-01's C5 was written to make unreachable, in its own words: "the odour search's plus and
minus 1.000 indices came from one spike against zero, and neither the magnitude nor the
reversal test means anything at that count."

It got through because I weakened the criterion while stating that I had not.

    DEMO-01 C5:  "Each cue epoch's scored intervals must contain at least 20 raw spikes
                  across the two decoded readout populations."

    my N2:       "The better side produces at least 20 raw readout spikes in its scored
                  epoch. DEMO-01's C5 floor, carried over unchanged."

Per-epoch became best-of, and "carried over unchanged" is false. The weakening admits exactly
the failure mode the original exists to block, and the contract's own summary line -- "the bar
did not move" -- is wrong.

**Under DEMO-01's actual C5, one grooming candidate of 36 has at least 20 spikes in both cue
epochs, and its selectivity swing is 0.036 against a 0.2 threshold. Zero candidates pass.**

## What follows

**The grooming operating point is not used.** The search selected a point and that selection
is void, because it rests on a selectivity index computed from one spike against zero. The
grooming behaviour contract is not re-run against it. The honest result is that this route can
be driven to threshold at roughly ten times the escape entry rate, and that no candidate
showed side selectivity on an adequate spike count.

**The escape selection stands.** Its N2 carries the identical wording defect, but 9 of its 11
passing candidates satisfy the strict per-epoch reading and the selected point is one of them,
with 78 and 115 spikes. The defect did not change its outcome. That is luck, not design, and
it is recorded as luck.

**Both contracts are frozen and neither is being rescored.** The correct fix is that any
future search states the floor per epoch, and does not describe a weakened criterion as
carried over unchanged.

## A number declared rather than buried

The grooming entry rates that produce any response, 1500 to 2000 Hz, are far above any
afferent rate measured in a fly. They are realisable here only because of a defect `DEMO-03`
already records: the kernel zeroes `RefracTime` for any neuron with a nonzero `InputRateHz`,
lifting its ceiling from about 455 Hz to 10,000 Hz. The rate is a statement about how much
drive this route needs in this model, and it is not a claim about Johnston's organ.
