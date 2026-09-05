# MaleCNS v1.0 morphology canaries

Audit date: 2026-09-05  
Source: official 8-nm SWC objects under `skeletons-malecns/skeletons-swc/`  
Local manifest: `/srv/flybrain-data/derived/male-cns-v1.0/morphology-canaries/manifest.json`  
Manifest SHA-256: `e033336551a4d8793f820261ace9592d4adb7813b167b095bf9f747b77c2f74f`  
Validation tier: none; this supplies only the morphology-canary component of the V0 bundle

| Body ID | Identity | Side/role | Nodes | SHA-256 |
|---:|---|---|---:|---|
| 10442 | DNa01_L | left brain-to-VNC descending | 11,295 | `a43c35e4967bb0da8ce19b19a29857e3aee700e18d70a30ecec4d8a5248bf3d3` |
| 10760 | DNa01_R | right brain-to-VNC descending | 11,047 | `73bb36fe84a5f1aae381aab44394706d50f6295e8359b4cb12e4d83d6396da8a` |
| 523769 | DNa02_L | left brain-to-VNC descending | 12,835 | `2b605a73b6a015e3b2eb7b6eccf089be6c087374914f7d4c9a7f70983e9036f1` |
| 10360 | DNa02_R | right brain-to-VNC descending | 13,170 | `50d9a19db9987ce8ac0dc94078def9aa74f9b35e25305003c5e440bf91874a10` |
| 127912 | JO-FV_L | left antennal sensory | 503 | `f2ef12bdec7559a68592f570995d5da40dfbbf420377803a1619f1ddff71872d` |
| 26519 | JO-FV_R | right antennal sensory | 583 | `0c58c29696e383f765065a11e4e89c6d4c3ae38dfa11acd5974b5f36c948e90b` |
| 38160 | JO-FD1_L | antennal grooming sensory | 379 | `17eb43ca700616c90d1eb481411cc29bca3cb6743945cedfdecff2adaa245dde` |
| 92767 | JO-FD1_L | antennal grooming sensory replicate | 414 | `76911665ed79ec8850fb7b83588c4f40abb4d462eb0de55476d5aad9e98ab57f` |
| 10331 | MN9_L | left feeding motor | 5,815 | `c1ca69d25f69143a463d206d3f8e52329c68998e5754f6a9aa13ece51406c9f4` |
| 16949 | MN9_R | right feeding motor | 1,578 | `229357f5e5ae3bbf563df47eee22eaf3b177b1235cc15e2d5b35cd18ea675b31` |

The cache validates SWC field counts, finite coordinates/radii, unique node IDs, at least one
root, complete parent references, byte counts, SHA-256, GCS generation, and ETag. Multiple roots
are retained as source morphology rather than silently repaired. Full morphology bulk acquisition
remains deferred.
