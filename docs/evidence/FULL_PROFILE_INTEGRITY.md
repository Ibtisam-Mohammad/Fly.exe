# MaleCNS v1.0 seven-artifact integrity record

Audit date: 2026-09-06
Dataset: `male-cns:v1.0`  
Scope: seven registered flat-connectome Feather tables only  
Validation tier: V0 Structural; this supplies the raw-profile-integrity gate within bundle `20260906T065413Z_V0`

The Windows-host supervisor completed local SHA-256 validation at
`2026-09-05T12:17:37+05:30`. A separate `flysim data validate --profile full --remote --deep`
run then confirmed the same local hashes, exact byte counts, readable Arrow/Feather footers,
and live GCS object generation, ETag, and size.

| Artifact | Bytes | GCS generation | ETag | Local SHA-256 |
|---|---:|---|---|---|
| body annotations | 14,483,314 | `1780494878811468` | `50a7718770c57220f160ba4f431ab89e` | `2177e246113e4cfbf1e7772ec37c6da1955ff22e8063d0b1f833101f99a9a3b2` |
| body neurotransmitters | 43,282,834 | `1780894899156750` | `3d842b12fe5c49eefade528d7dd24a1f` | `95c9289220663abeb3409f3ad9e5a7f8a53f8093f5139d15502cd08da8879621` |
| body statistics | 778,062,826 | `1780494888472305` | `404c3349c28580148e16815eb99f382a` | `ca5dc83a26382ae70c8d8f42fc09ce2dbc1af7c03f3a001a1936b5e142540647` |
| connectome weights | 1,051,241,946 | `1780494887545976` | `f30e9dcca25cfd021bf1e7b3d975599e` | `e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1` |
| synapse points | 13,061,489,098 | `1780494991007477` | `c69d08758de07582035cc8843574493a` | `c16b1b63186c4d4f28939decea7444451f0f5f6f7ef1bb5dab5b2a7058f8f284` |
| synapse partners | 6,777,179,098 | `1780494942562468` | `58efcf712f8c4d4de5f2ad51e97def76` | `959d8ef4173b35382a3e6acfaf5167c795b6d10b877572d146af04e1b487bc07` |
| T-bar neurotransmitters | 2,651,680,218 | `1780894927871192` | `51b02c11690662aedef28f86d394ff0d` | `bade84c9eab431dd537ff644aaf3d203d639a819c739ecedb338e7d109064f4d` |

Pinned upstream MD5 and CRC32C values are machine-readable in
`configs/datasets/malecns-v1.0.json`. The local SHA-256 lock remains the derivative provenance
root. This record excludes skeleton collections, image/segmentation volumes, and the neuPrint
database. It does not establish contact joins, polyadic preservation, aggregate reconciliation,
body-universe choice, or any neural/biological validity.
