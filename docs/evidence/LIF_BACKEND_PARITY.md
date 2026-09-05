# Deterministic LIF backend parity

Evidence date: 2026-09-05  
Validation tier: none; numerical implementation evidence only

## Result

The same explicit three-neuron feed-forward LIF fixture ran in the local NumPy oracle,
Brian2, and a direct custom float32 PyGeNN CUDA model. Each backend emitted 14 spikes with
the same ordered neuron identities. The maximum reported timestamp difference against the
NumPy reference was `2.842170943040401e-14 ms`, below the preregistered one-step tolerance
of `0.1 ms`.

This establishes one deterministic integration and static-pulse schedule. It does not validate
MaleCNS membrane parameters, functional sign, synaptic strength, tonic drive, receptor kinetics,
or whole-graph dynamics. The fixture values are explicit engineering constants under
`ND-LIF-01`, `ND-01`, `ND-04`, and `NUM-01`.

## Reproduction identity

- Command: `flysim benchmark neural --parity`
- Code commit: `9f491786a7a2be1497fddba68cf1f652d8e3c916`
- NumPy: 2.5.2
- Brian2: 2.10.1 using its NumPy runtime and forward Euler
- PyGeNN: 5.4.0, direct custom model, CUDA backend, float32
- Circuit SHA-256: `3c49f84377d9a056c62a5e030842851d08569f81d785d013ca54eb6474de8552`
- Evidence JSON: `/srv/flybrain-data/evidence/male-cns-v1.0/lif-backend-parity.json`
- Evidence JSON SHA-256: `8a5546ea79bdf3106293a7551000823cb00ff4eb9c87e88a8ac4835fbd579edd`

The custom model follows the current
[PyGeNN custom-model interface](https://genn-team.github.io/genn/documentation/5/userproject/superspike_demo.html).
