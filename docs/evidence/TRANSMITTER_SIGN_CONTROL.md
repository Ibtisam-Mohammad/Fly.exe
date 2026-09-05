# Transmitter-only edge-sign control

Evidence date: 2026-09-05  
Validation tier: none; regression-control construction only

The provisional 165,122-neuron `DATA-04` graph now has a reproducible implementation of the
transmitter-only sign rule used by Shiu et al.: GABA and glutamate are inhibitory; acetylcholine,
dopamine, octopamine, and serotonin are excitatory. Histamine, `unclear`, and missing values stay
unresolved. The caller must explicitly select zero, excitatory, inhibitory, or seeded-balanced
handling for those unresolved neurons.

With the conservative zero policy, official MaleCNS consensus annotations resolve 155,610 of
165,122 graph neurons (94.239%) and leave 9,512 at zero. The resulting 25,563,197-edge float32
array has SHA-256 `d095bd8698c3746632df4b763cd34bff332616c43f4b7dd531dc9076551d0cc0`.

This is a named `P/E` regression and control, not the `ND-03` physiological default. Transmitter
identity does not determine postsynaptic receptor identity or edge sign. Receptor-aware competing
models remain required.

- Command: `flysim data build-edge-signs --unresolved-policy zero ...`
- Implementation commit: `bec68c6f173bfc58ec8ee7fa80f7509b14b3a2b2`
- Manifest: `/srv/flybrain-data/derived/male-cns-v1.0/neural-variants/shiu-unresolved-zero-v1.npy.json`
- Source method: [Shiu et al. 2024](https://doi.org/10.1038/s41586-024-07763-9)
