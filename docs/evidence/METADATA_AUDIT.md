# MaleCNS v1.0 metadata audit

Audit date: 2026-09-04  
Source: official `male-cns:v1.0` bulk artifacts  
Validation tier: not yet V0; starter artifacts and provisional runtime derivative only

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
| oDN1 | unresolved; no exact v1.0 type match |
| Or42b | unresolved; no exact type or receptorType match |
| Gr5a / Gr64f | unresolved; no exact type or receptorType match |
| antennal-grooming descending readout | unresolved from current exact annotation queries |

An unresolved annotation is not evidence that the biological neuron or pathway is absent. It means the proposed interface cannot currently be assigned a MaleCNS body ID without a sourced crosswalk. Engineering demos retain semantic placeholders and report them as `E`; scientific runs are blocked.

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
