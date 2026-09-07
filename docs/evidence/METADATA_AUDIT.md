# MaleCNS v1.0 metadata audit

Audit date: 2026-09-07

Source: official `male-cns:v1.0` bulk artifacts

Validation tier: V0 Structural; population mappings below are Track A readiness evidence only

## Locked artifacts

| Artifact | Rows | Observed SHA-256 |
|---|---:|---|
| body annotations | 211,577 | `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` |
| body neurotransmitters | 1,835,518 | `95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621` |
| body statistics | 88,384,522 | `ca5dc83a26382ae70c8d8f42fc09ce2dbc1af7c03f3a001a1936b5e142540647` |
| all-segment aggregate weights | 151,856,684 | `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1` |

These are locally observed hashes because the official page does not publish SHA-256 values. The immutable dataset lock under `/srv/flybrain-data` is the verification root for subsequent runs.

## Exact annotation results

| Interface | Resolution |
|---|---|
| DNa01 left/right | `10442` left, `10760` right |
| DNa02 left/right | `523769` left, `10360` right |
| MN9 left/right | `10331` left, `16949` right |
| JO-F grooming sensory population | 64 exact `JO-F*` rows: 60 JO-FV and 4 JO-FD1; one additional `JO-unclear` row has grooming subclass but is deliberately excluded |
| oDN1 | no exact name match; sourced oDN1-to-DNg97 crosswalk resolves `13805`, `230783` |
| Or42b / Or59b | no exact type or receptorType match; Track A explicitly bypasses to bilateral `DM1_lPN`, `DM4_adPN`, and `DM4_vPN` (`10176`, `10208`, `10613`, `10670`, `71476`, `73492`) |
| Gr5a / Gr64f | no exact type or receptorType match; Track A explicitly bypasses to bilateral `GNG588/Fdg` (`12617`, `14321`) |
| antennal-grooming descending readout | aDN1/aDN2/aDN3 crosswalk resolves bilateral `DNg62`, `DNge078`, and `DNg21`: `13624`, `14537`, `15148`, `15825`, `16221`, `36541` |

An absent exact receptor annotation is not evidence that the biological neuron or pathway is
absent. Track A uses sourced cross-specimen central-relay mappings and labels the omitted
peripheral layers as `P/E`; it does not treat those relays as measured receptors.

## Body-universe finding

The official download page describes the aggregate weights as segment-to-segment strengths for all segments, not as a curated-neuron-only table. Annotation status counts observed locally are:

| Status | Bodies |
|---|---:|
| Traced | 165,122 |
| Assign | 1,832 |
| Anchor | 611 |
| Orphan | 15,925 |
| Glia | 11,864 |
| Unimportant | 10,751 |
| missing | 5,472 |

The accepted runtime derivative uses `status=Traced`, retains all 165,122 IDs including any isolated bodies, and retains 25,563,197 edges whose two endpoints are traced. It records 126,293,487 excluded all-segment rows and 187,808,197 excluded contacts. No contact-count or weak-edge threshold is applied. Assign/Anchor remain explicit sensitivity alternatives. See [ADR-2026-002](../adr/ADR-2026-002-traced-neuron-universe.md).
