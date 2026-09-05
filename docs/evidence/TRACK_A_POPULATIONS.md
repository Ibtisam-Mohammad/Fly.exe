# Track A population resolution

Evidence date: 2026-09-05  
Validation tier: none; anatomical identity and engineering-readiness evidence only

The versioned Track A registry resolves the following MaleCNS v1.0 populations:

| Interface | MaleCNS body IDs | Evidence boundary |
|---|---|---|
| left steering DNa01/DNa02 | `10442`, `523769` | exact MaleCNS annotation |
| right steering DNa01/DNa02 | `10760`, `10360` | exact MaleCNS annotation |
| forward oDN1/DNg97 | `13805`, `230783` | MaleCNS DNg97 annotation plus cross-specimen type crosswalk |
| feeding-initiation MN9 | `10331`, `16949` | exact MaleCNS annotation; behavioral use remains a transferred prior |
| antennal grooming JO-F | 64 bodies | exact class/subclass/type query; downstream use remains a transferred prior |

The oDN1 crosswalk is supported by the peer-reviewed DNg97/oDN1 identity in
[Dallmann et al.](https://doi.org/10.1038/s41586-025-09554-2) and independently indexed by
[FlyBase FBbt:20007470](https://flybase.org/reports/FBbt:20007470.html). It does not imply that
DNg97 alone specifies forward walking.

Three required Track A interfaces remain unresolved and therefore keep `eon-malecns`
readiness-gated: the antennal-grooming descending population, ethyl-acetate sensory entry, and
sucrose sensory entry. No numeric IDs will be guessed for them.

- Registry: `configs/populations/eon-demo.json`, version `eon-demo-populations-v0.2`
- Resolution JSON: `/srv/flybrain-data/derived/male-cns-v1.0/population-resolution.json`
- Resolution SHA-256: `75f6bb4f0f73c1e68e78ec05a0890bcfeb18d2a41ca66a608e120dde72bd5c0f`
