# DEMO-01 visual route: the exploratory pilot that shaped the registered search

Everything here is **exploratory**, run on short epochs before
`demo01-visual-operating-point-v1` was committed, and it is recorded because it determined
the registered grid and three changes to the dynamics layer. None of it is evidence, none
of it is scored for the record, and the registered search runs once on the committed
contract.

Piloting before preregistration is legitimate. Piloting and then quietly rewriting the
contract afterwards is not, which is why the numbers are here rather than paraphrased.

Graph: exact 165,122 bodies / 25,563,197 edges. Signs: ND-10 Shiu regression, `zero`
policy. Readout filter 150 ms. Coupling 15 ms. Seed 1.

## Pilot 1: gain against per-target normalisation

Epochs 300/450/450/300 ms, tonic 2.0 mV, lamina 150 Hz, ON/OFF balance 0.

| mV/contact | norm exponent | optic lobe Hz | visual proj Hz | central brain Hz | descending Hz | cue response |
|---|---|---|---|---|---|---|
| 0.075 | 0.0 / 0.5 / 1.0 | 0.26-0.29 | 0.00 | 0.00 | 0.00 | none |
| 0.275 | 0.0 | 0.46 | 0.10 | 0.62 | 1.16 | 2.33 |
| 0.275 | 0.5 / 1.0 | 0.45-0.48 | 0.00 | 0.00 | 0.00 | none |
| 0.600 | 0.0 | 1.98 | 1.17 | 33.09 | 11.12 | 12.89 |
| 0.600 | 0.5 | 0.71 | 0.05 | 0.01 | 0.05 | 0.11 |
| 0.600 | 1.0 | 0.95 | 0.19 | 0.00 | 0.00 | none |

**Finding 1, and it refutes my own D4/D8 hypothesis.** Per-target normalisation is
counterproductive at every gain: it silences the network. The reasoning behind it was that
descending cells integrating 750 to 1200 inputs were being swamped, so attenuating the
heavily converged ones would help. The measurement says the opposite -- those cells were
not being driven enough, and attenuating their input removed what little drive they had.
The parameter is kept in the engine, defaults to 0.0, and is **fixed at 0.0** in the
registered contract, with this table as the reason.

**Finding 2.** The network is silent at 0.275 mV and self-sustaining at 0.600, with no band
between. At 0.600 the central brain ran at 33 Hz and descending drive after cue removal was
13.00 Hz against 12.89 Hz during the cue: no recovery at all. That is a recurrent network
at a bifurcation with nothing to stabilise it, and this LIF has nothing -- no adaptation, no
synaptic depression, no conductance-based saturation.

## Pilot 2: does spike-frequency adaptation open a band?

Epochs 450/750/750/750 ms, tonic 2.0 mV, lamina 150 Hz, normalisation 0.

| mV | adapt mV | central brain Hz | descending Hz | recovery residual | swing | C1 C2 C3 C4 C5 |
|---|---|---|---|---|---|---|
| 0.40 | 0.0 | 28.00 | 7.87 | 0.97 | 0.042 | P P . . P |
| 0.40 | 1.0 | 11.76 | 4.34 | 0.98 | 0.080 | P P . . P |
| 0.40 | 4.0 | 0.98 | 1.29 | 0.50 | 0.051 | P P . . P |
| 0.60 | 0.0 | 33.92 | 11.85 | 0.98 | 0.030 | P P . . P |
| 0.60 | 1.0 | 15.79 | 6.76 | 0.90 | 0.089 | P P . . P |
| 0.60 | 4.0 | 3.51 | 3.56 | -31.84 | 0.026 | P . . P P |
| 0.90 | 1.0 | 27.18 | 11.17 | 0.47 | 0.034 | . P . P P |

**Finding 3.** Adaptation works as intended: it cuts the central-brain rate roughly
proportionally (33.92 to 3.51 at 0.6 mV) and lets the recovery criterion pass. It is added
to the engine as an opt-in adaptive LIF whose kernel is byte-identical to the original when
the increment is zero.

**Finding 4.** Selectivity never exceeded 0.089 against the 0.2 threshold, at any gain or
adaptation. Something else was wrong.

## Pilot 3: is the background coming from tonic drive?

Same sweep with tonic drive at 0.0 instead of 2.0. Central brain still 13.88 to 71.66 Hz;
selectivity still 0.011 to 0.064. **Finding 5: no.** The background is self-sustaining
recurrent activity, not injected bias. Tonic drive is therefore **fixed at 0.0** in the
registered contract: it was not buying anything.

At 0.60 mV the optic lobe sat at 1.17 Hz and the visual projection neurons at 1.05 Hz while
the central brain ran at 31.90 Hz. A densely recurrent, net-excitatory population amplifying
its own input 27-fold is a network whose excitation and inhibition are not balanced, and no
gain or adaptation setting repairs an imbalance -- only the ratio does.

## The measurement that explained the selectivity failure

Pure graph, whole LC/LPLC/LLPC family as driver, laterality averaged over left-driver and
right-driver so a fixed anatomical asymmetry cancels:

| descending group | L | R | LC share of input contacts | laterality h1 / h2 / h3 |
|---|---|---|---|---|
| all descending | 656 | 648 | 3.56% | +0.918 / +0.318 / +0.526 |
| DNp* | 160 | 158 | **8.83%** | +0.961 / +0.504 / +0.420 |
| DNa* | 26 | 26 | 2.71% | +0.721 / +0.241 / +1.000 |
| DNg* | 426 | 422 | **0.44%** | +0.727 / +0.098 / +0.312 |
| DNb* | 20 | 20 | 5.79% | +0.874 / -0.046 / -1.000 |
| DNp02/03/04/06 | 4 | 4 | **38.03%** | +0.994 / +0.894 / +1.000 |

**Finding 6, the decisive one.** The whole descending pool is 848 of 1,304 bodies DNg and
DNge, which take 0.44 per cent of their input from visual projection neurons. Averaging a
lateralised visual signal into a population that is two thirds visually blind is what held
the index at 0.03 to 0.09. The decoded readout becomes `DNp*`, 160 left and 158 right.

## Pilot 4: inhibitory weight gain, decoding on DNp

Epochs 450/750/750/750 ms, tonic 0, normalisation 0.

| mV | inh gain | adapt | central brain Hz | descending act | baseline | cue L / R | resid | swing | C1-C5 |
|---|---|---|---|---|---|---|---|---|---|
| 0.60 | 1.0 | 0.0 | 31.90 | 0.1154 | 0.00 | 15.50 / 18.40 | 1.01 | 0.077 | P P . . P |
| 0.60 | 2.0 | 0.0 | 0.21 | 0.0158 | 0.00 | 1.07 / 1.44 | 0.06 | 1.005 | . . P P P |
| 0.60 | 4.0 | 0.0 | 0.02 | 0.0034 | 0.00 | 0.43 / 0.60 | 0.04 | 1.508 | . . P P P |
| 0.60 | 8.0 | 0.0 | 0.01 | 0.0013 | 0.00 | 0.23 / 0.22 | 0.05 | 1.880 | . . P P P |
| 1.20 | 1.0 | 0.0 | 56.13 | 0.1632 | 23.08 | 29.15 / 29.97 | 1.21 | 0.010 | . P . . P |
| 1.20 | 2.0 | 0.0 | 6.59 | 0.0458 | 4.68 | 4.34 / 4.83 | 0.38 | 0.209 | P . P P P |
| 1.20 | 2.0 | 1.0 | 2.56 | 0.0296 | 3.13 | 2.60 / 3.85 | -0.33 | 0.307 | P . P P P |

**Finding 7.** An inhibitory gain of 2 or more stops the central brain self-sustaining
(31.90 Hz down to 0.21) and the DNp selectivity criterion starts passing with reversal.
The remaining conflict is C1 against C2: low gain gives a clean zero baseline but only
1.44 Hz of cue response, and raising the gain lifts the baseline instead of the response.

## Pilot 5: more stimulus rather than more gain

The conflict resolves by driving the input harder, which raises the cue response without
touching the recurrent background. Epochs 450/750/750/750 ms, adapt 1.0, inh and lamina
swept.

| mV | inh | lamina Hz | central Hz | desc act | baseline | cue L / R | resid | swing | C1-C5 |
|---|---|---|---|---|---|---|---|---|---|
| 0.60 | 2.0 | 150 | 0.16 | 0.0104 | 0.00 | 0.83 / 1.17 | 0.03 | 0.795 | . . P P P |
| **0.60** | **2.0** | **300** | **0.80** | **0.0202** | **0.00** | **2.80 / 1.70** | **0.02** | **0.513** | **P P P P P** |
| 0.80 | 2.0 | 300 | 1.15 | 0.0223 | 2.05 | 2.09 / 3.16 | -1.75 | 0.528 | P . P P P |
| 1.00 | 2.0 | 300 | 2.52 | 0.0273 | 1.65 | 2.95 / 2.40 | 1.49 | 0.340 | P . P . P |
| 1.00 | 3.0 | 300 | 0.33 | 0.0123 | 0.30 | 1.36 / 1.33 | 0.11 | 0.565 | . . P P P |

**Finding 8.** A point exists that meets all five criteria: 0.60 mV per contact,
inhibitory gain 2.0, adaptation 1.0 mV, lamina 300 Hz, tonic 0, normalisation 0. Its
descending active fraction is 0.0202 against a 0.02 floor, which is **marginal by one part
in a hundred**, so the registered grid brackets this point on every axis rather than
assuming it. If the registered run finds only this one candidate passing, that fragility is
part of the result and is reported.

## What the pilot changed

| change | driven by | default |
|---|---|---|
| per-target normalisation added, then **fixed at 0** | findings 1, kept for the record | 0.0, exactly the original weights |
| spike-frequency adaptation added | findings 2, 3 | 0.0, byte-identical kernel |
| inhibitory weight gain added | findings 5, 7 | 1.0, exactly the original weights |
| tonic drive **fixed at 0** | finding 5 | unchanged |
| decoded readout moved from the whole pool to `DNp*` | finding 6 | n/a |
| lamina rate range raised to 200-400 Hz | finding 8 | n/a |
| L3 and L4 dropped from the entry | released columns cover L3 on one side only and L4 on neither | n/a |

Three of these add a parameter to the dynamics layer. Every one defaults to the value that
reproduces the pre-existing behaviour exactly, and each is omitted from the model identity
while it holds that value, so no recorded run's identity changes.

The inhibitory weight gain deserves a note. It is not a fudge factor added to make a demo
work: the engine previously asserted that a predicted-inhibitory contact and a
predicted-excitatory contact deflect the membrane equally, which is an assumption with
nothing behind it, since the signs are transmitter predictions and the cholinergic and
GABAergic synapses being predicted differ in receptor conductance and reversal potential.
Making the ratio explicit and searched states the assumption rather than burying it.
