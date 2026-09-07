# Track A population resolution

Evidence date: 2026-09-07
Validation tier: none; anatomical identity and engineering-readiness evidence only

The versioned Track A registry resolves the following MaleCNS v1.0 populations:

| Interface | MaleCNS body IDs | Evidence boundary |
|---|---|---|
| left steering DNa01/DNa02 | `10442`, `523769` | exact MaleCNS annotation |
| right steering DNa01/DNa02 | `10760`, `10360` | exact MaleCNS annotation |
| forward oDN1/DNg97 | `13805`, `230783` | MaleCNS DNg97 annotation plus cross-specimen type crosswalk |
| feeding-initiation MN9 | `10331`, `16949` | exact MaleCNS annotation; behavioral use remains a transferred prior |
| antennal grooming JO-F | 64 bodies | exact class/subclass/type query; downstream use remains a transferred prior |
| antennal-grooming aDN1/aDN2/aDN3 candidates | `13624`, `15148`, `14537`, `36541`, `15825`, `16221` | exact MaleCNS `DNg62`, `DNge078`, and `DNg21` annotations reached through the paper's six FlyWire IDs and the paper-author MaleCNS crosswalk |
| ethyl-acetate central relay | `10176`, `10208`, `10613`, `10670`, `71476`, `73492` | exact bilateral MaleCNS `DM1_lPN`, `DM4_adPN`, and `DM4_vPN`; explicit bypass of Or42b/Or59b peripheral neurons and antennal-lobe local processing |
| sucrose central relay | `12617`, `14321` | exact bilateral MaleCNS `GNG588`; transferred `Fdg`/`CB0038` identity and explicit bypass of peripheral Gr5a/Gr64f neurons |

The oDN1 crosswalk is supported by the peer-reviewed DNg97/oDN1 identity in
[Dallmann et al.](https://doi.org/10.1038/s41586-025-09554-2) and independently indexed by
[FlyBase FBbt:20007470](https://flybase.org/reports/FBbt:20007470.html). It does not imply that
DNg97 alone specifies forward walking.

The grooming candidates come from the six aDN1/aDN2/aDN3 FlyWire IDs in
[Ozdil et al.](https://doi.org/10.1038/s41467-026-72152-x), mapped through the paper-author
MaleCNS/FlyWire crosswalk to three exact bilateral MaleCNS types. This is cross-specimen identity
evidence (`P`), not proof that activating those six bodies biologically executes grooming.

MaleCNS does not contain exact `Or42b`, `Gr5a`, or `Gr64f` annotation matches. Track A therefore
uses two visible central-relay bypasses allowed by the accepted plan:

- Ethyl acetate drives bilateral `DM1_lPN`, `DM4_adPN`, and `DM4_vPN`. DoOR reports the
  Or42b/ab1A-to-DM1 mapping, while adult experiments report ethyl-acetate responses in DM1 and
  DM4. The procedural plume, receptor omission, and relay transfer remain `P/E`.
- Sucrose contact drives bilateral `GNG588`, transferred from FlyWire `Fdg`/`CB0038`. The local
  preregistered Stage 1 screen found this mapped pair sufficient to recruit bilateral MN9 in the
  Shiu-style model, but the exact graph did not beat all structural controls and earned no V3.

All required Track A interfaces now resolve to numeric MaleCNS bodies. The full-graph adapter,
FlyGym body, controls, and acceptance ensemble have executed; see
[Track A full-graph evidence](TRACK_A_EON_MALECNS.md).

- Registry: `configs/populations/eon-demo.json`, version `eon-demo-populations-v0.3`
- Resolution JSON: `/srv/flybrain-data/derived/male-cns-v1.0/population-resolution.json`
- Resolution SHA-256: `3b0c53a38230be21e2e23ec5268a7a6ea96e1e1e404e58e1e40db6b78b813eef`
