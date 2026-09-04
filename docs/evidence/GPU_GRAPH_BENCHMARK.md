# GeNN structural graph-load benchmark

Benchmark date: 2026-09-04  
Validation tier: none; allocation/performance evidence only

## Configuration

- Ubuntu 24.04 WSL2 distribution `FlyBrain`
- NVIDIA GeForce RTX 3060, 12,288 MiB; Windows driver 591.86
- CUDA compiler 12.0.140
- GeNN/PyGeNN 5.4.0, CUDA backend, device 0, float32
- 165,122-neuron provisional `DATA-04` graph
- source aggregate SHA-256 `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1`
- 0.1 ms GeNN timestep
- zero functional synaptic weight (`E` allocation scaffold)

Sub-100% conditions uniformly sample aggregate-edge rows. They are load tests, not biological subgraphs.

| Scale | Edges | Configure | Compile | Load | GPU delta | One step |
|---:|---:|---:|---:|---:|---:|---:|
| 1% | 255,632 | 0.040 s | 19.799 s | 0.242 s | 205 MiB | 0.171 ms |
| 10% | 2,556,320 | 0.541 s | 11.885 s | 0.972 s | 788 MiB | 0.180 ms |
| 100% | 25,563,197 | 7.558 s | 11.976 s | 12.466 s | 7,165 MiB | 0.483 ms |

At 100%, `nvidia-smi` reported 8,339 MiB total GPU use and 3,775 MiB free. The model therefore passes the current allocation and 1.5 GB headroom gates for structural zero-weight execution.

It does not establish biological-time throughput for receptor-aware dynamics, delays, stochastic release, observation buffers, or recording. Those additions require fresh measurements; this result must not be described as a neural validation tier.
