# V0 Structural evidence

- Award date: 2026-09-08 (reissue); first awarded 2026-09-06
- Evidence bundle: `/srv/flybrain-data/evidence/male-cns-v1.0/V0-evidence-r2.json`
- Bundle ID: `20260908T060641Z_V0`
- Bundle SHA-256: `38366a8df86861501ca2fd4eff3e3c9329e0e089ec0e188b4af4f1a66c085958`
- Hashed artifacts: 9
- Highest validation tier: **V0 Structural**

## Reissue and the withdrawn first bundle

The first bundle, `20260906T065413Z_V0`
(SHA-256 `d8a95e151daf3e2bb70b13052f52a2b794e9bf6887121d64d34727f37cccf0b0`), is **withdrawn**
and still fails `flysim evidence validate`. It pinned `configs/assumptions.json`, the whole
mutable project assumption register, which a later unrelated Stage 2 edit grew from 23,560 to
25,853 bytes. It could not be rebuilt either, because the builder additionally required the
literal assumption set `foundation-v0.3` while the register had moved on. It is left on disk
in its failing state, which is what a withdrawn claim should look like.

The structural measurements below were never in dispute; the bundle attesting to them was. The
reissued bundle differs from the first in three ways:

1. It pins `v0-foundation-assumptions.json`, an immutable snapshot scoped to the `DATA-*`
   foundation records, instead of the whole register. A change to a scoped record still breaks
   it; an unrelated register edit no longer does. The observed register revision is kept in an
   unhashed provenance sidecar.
2. Its raw-profile review, `raw-profile-integrity-review-r2.json`, recomputes each of the seven
   raw artifacts' upstream MD5 from local bytes. All seven match. CRC32C is pinned but not
   recomputed, because no native CRC32C implementation is installed, and the review records
   that as unverified rather than implying the check ran.
3. It was built from a clean worktree at commit `e0bd1de`; the builder now refuses a dirty tree.

See [ADR-2026-006](../adr/ADR-2026-006-evidence-chain-repair.md).

## What passed

All twelve preregistered gates in the immutable evidence bundle are true:

1. raw-profile integrity;
2. schema and 8-nm coordinate-unit preservation;
3. exact presynaptic and postsynaptic endpoint joins;
4. polyadic-site preservation;
5. exact partner-to-aggregate reconciliation;
6. fixed morphology canaries;
7. body-universe sensitivity;
8. the accepted `status=Traced` universe decision;
9. independent batch-size reproducibility;
10. official counts and selected motifs;
11. confidence-threshold sensitivity; and
12. a bounded cross-connectome comparison.

When the bundle was built, the seven official flat-connectome artifacts were reread end to end:
their SHA-256 was recomputed and matched the lock, their upstream MD5 was recomputed and matched
the pinned value, their Feather schemas and footers were opened, and their byte counts matched.
The pinned GCS generation and ETag are recorded but cannot be recomputed from local bytes, and
the pinned CRC32C is recorded and **not** verified, because no native CRC32C implementation is
installed. The review artifact states that explicitly rather than listing CRC32C among the
checks that ran.

## Contact preservation

| Source relation | Rows | Structural result |
|---|---:|---|
| Synaptic points | 357,489,383 | Packed point IDs are bijective; point IDs are unique. |
| Partner contacts | 311,833,243 | Every pre/post endpoint resolves exactly with matching body, kind, and confidence. |
| Aggregate body pairs | 151,856,684 | Grouped partner rows reproduce the official aggregate table exactly. |
| T-bar transmitter rows | 45,656,140 | Every row resolves to a presynaptic point; probabilities are finite and bounded. |

There are 45,417,969 polyadic presynaptic sites and the observed maximum fan-out is 28. No
confidence or weak-edge threshold was applied to the canonical derivative.

## Independent rebuilds

The canonical derivative was compared with clean 262,144-row-group and 131,072-row-group
rebuilds. All four artifact families had identical layout-independent logical digests both against
the canonical derivative and against one another.

| Artifact | Rows | 262,144 peak RSS | 131,072 peak RSS |
|---|---:|---:|---:|
| Aggregate body pairs | 151,856,684 | 0.94 GiB | 0.80 GiB |
| Synaptic points | 357,489,383 | 1.65 GiB | 1.48 GiB |
| Partner contacts | 311,833,243 | 1.34 GiB | 1.21 GiB |
| T-bar transmitters | 45,656,140 | 2.15 GiB | 2.11 GiB |

Every clean import remained below the 3-GiB ingestion limit.

## Structural reference boundary

The accepted runtime universe contains 165,122 `Traced` bodies and 25,563,197 directed
traced-to-traced aggregate edges. Extending it through `Assign+Anchor` adds 2,443 bodies (1.48%),
60,281 edges (0.24%), and 149,409 contacts (0.12%); these alternatives remain available for
sensitivity analyses.

The paper-reference checks compare the v1.0 observations with the source authors' rounded or
v0.9-definition counts under declared tolerances. The cross-connectome input contains 3,761,792
paper-author aligned type-edge rows and 281,656 mappings, pinned to supplement commit
`67767d2233657983993ff6c2be48e836a935863c`. It is a cross-sex, cross-specimen central-brain
comparison that excludes MaleCNS VNC connections; it is not evidence of physiological
conservation.

## Claim boundary

V0 proves that the registered MaleCNS structural foundation is identifiable, reproducible, and
losslessly auditable under the declared transforms. It does **not** validate membrane dynamics,
synaptic sign or strength, neural activity, sensory transduction, motor physiology, embodiment,
behavior, or recovery of the source fly. No tier from V1 through V8 is awarded by this bundle.
