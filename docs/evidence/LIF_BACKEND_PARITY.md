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

## GeNN delay correction, 2026-09-08

The one-step GeNN offset recorded in this report was a defect, not a property of the backend.
GeNN presents synaptic input to the postsynaptic neuron on the step after the presynaptic spike
even with `axonal_delay_steps = 0`, and the adapters assigned the full registered `delay_steps`
on top of that, so the registered 0.1 ms delay executed as 0.2 ms. The adapters now assign
`delay_steps - 1`, and `tests/test_repairs.py` pins the semantics with a one-synapse impulse
probe at one, two and three steps on the CPU backend. Every measurement in this report predates
that fix, so a rerun would move the GeNN spike times one step earlier and remove the offset.
