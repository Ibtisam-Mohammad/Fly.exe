# The shuffle control, regime-matched: topology buys selectivity, not responsiveness

The degree-preserving target shuffle is the topology control behind DEMO-01's `A5` and
DEMO-02's `E7`. It is unsound as used, and this measures what it can and cannot license.

## The problem

The shuffle is meant to remove structure and keep statistics. It does not keep the operating
regime. At the same synaptic gain the shuffled escape network runs at 56.05 Hz of descending
drive against the intact network's 9.32 Hz, a six-fold difference, and in the earlier DEMO-02
matrix it reached 14,025 active neurons per interval against 2,948.

A control that moves the network to a different excitability regime cannot separate the
contribution of topology from the contribution of gain. Passing or failing such a gate
licenses nothing.

## Regime matching is possible

Sweeping synaptic gain on the shuffled graph alone, holding everything else fixed:

    gain   descending Hz   active    vs intact
    0.05          1.368    0.0199       0.15x
    0.10          4.473    0.0624       0.48x
    0.15          9.013    0.1223       0.97x     <- matched
    0.20         15.123    0.1986       1.62x
    0.30         32.767    0.3845       3.52x
    0.40         56.048    0.5526       6.02x

At gain 0.15 the shuffled network sits at 0.97 times the intact network's descending rate.
The comparison can therefore be made at matched activity, which is what the qualifier in
DEMO-01's surviving claim -- "at this operating point" -- was always implying.

## The result, and it splits in two

    condition                      left object   right object   swing    reverses
    intact @ gain 0.40             (120, 0)      (0, 163)       +2.000   yes
    shuffled @ matched gain 0.15   (0, 104)      (4, 78)        -0.098   no
    shuffled @ gain 0.40           (23, 160)     (5, 117)       +0.169   no

All three clear 20 spikes in both epochs, so every selectivity index here is interpretable.

**The matched shuffle drives the giant fibre as hard as the real connectome.** 104 and 78
spikes against 120 and 163. Whatever makes this readout reachable from the lamina is not the
specific wiring: a random rewiring with the same degree sequence, at the same activity, gets
there too.

**The matched shuffle does not reproduce the lateralisation.** The intact network separates
the sides perfectly -- swing +2.000, the maximum the index can take -- which is what zero
cross-side edges from `LC4` and `LPLC2` predicts. The matched shuffle reaches -0.098 and does
not reverse sign. The hyperactive shuffle reaches +0.169 and does not reverse either.

## What this licenses and what it withdraws

**Withdrawn:** any claim of the form "the exact connectivity is why the readout responds at
all". It is not. That was never tested at matched regime, and at matched regime it is false.

**Earned, and now properly controlled:** the exact connectivity is why the response is
*side-selective*. A degree-matched random network at the same activity drives the same cell
just as hard with no side preference whatsoever.

That is a narrower claim than "topology-specific" and a better supported one. It also says
the gates as written are testing the wrong quantity: `A5` and `E7` both ask whether the
shuffled network produces the behaviour, when they should ask whether it reproduces the
selectivity, at matched activity.

## Consequences for what is already recorded

`DEMO-01`'s `A5` passed and its claim was FULL-GRAPH CAUSAL EMBODIMENT, TOPOLOGY-SPECIFIC.
That gate used the naive shuffle at the intact gain, so it compared a 9 Hz network against a
56 Hz one.

**Corrected on 2026-09-12: `A5` is suspended and the word "topology-specific" is withdrawn.**
This section previously declined to withdraw it, on the grounds that the verdict is a frozen
recorded result and this is a different experiment on a different route. Both of those facts
are true and neither is a reason to keep a live claim standing on a control that has been
shown to be confounded. A recorded verdict stays on the record; a claim citing it does not
stay in force once its instrument fails. `A1` to `A4` are untouched and the causal-embodiment
verdict stands. See the banner at the head of `DEMO01_FULL_GRAPH_EMBODIMENT.md`.

`DEMO-02`'s `E7` was already reported as uninterpretable rather than failed, and
`demo02-escape-legs-v1` has no topology gate at all. Both remain correct.

## Limits of this measurement

One shuffle seed. One route. One matching criterion -- descending-pool mean rate -- where
active fraction matched less exactly, 0.1223 against 0.0942. A future topology gate should
declare its matching quantity and tolerance in advance, require at least 20 spikes in both
epochs, and score reversal of the selectivity index rather than presence of a response.
