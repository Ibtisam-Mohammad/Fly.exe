# Eon showcase v2 repair result — 2026-09-13

Status: implementation repair complete; final showcase blocked

Scientific tier: V0 Structural, unchanged

Code commits:

- `fd1c67acc302916758d67b0ff417ff258b5a532a` — fail-closed v2 contract,
  evaluator, renderer, independent chapters, graph-free body controls, and feeding search
- `c7501b988b4a3be0e0b8162bd4bdef3b4b1736c4` — graph-free control summaries become
  scoreable
- `3a4f893` — the frozen feeding concentration matrix and F4–F7 evaluator become
  executable

## Audit disposition

| Audit finding | Resolution | Current result |
|---|---|---|
| The v1 hero used odour-gradient steering and central relays rather than the visual causal route. | v1 is retained only as a historical limited preview. `eon-showcase-v2` requires DEMO-01's visual route, forbids raw-world/odour/direct-drive navigation, and requires three frozen targets. | The corrected navigation matrix has not run, so no replacement navigation claim exists. |
| Feeding took a relay fallback without an operating-point search. | A 36-point neural-only tarsal-taste-to-MN9 search was preregistered and executed from clean commit `fd1c67a`. | Four points passed. The frozen winner is 800 Hz taste ceiling, 0.9 mV/contact, and 1.75 inhibitory gain. |
| Grooming travelled 8.477 mm against a 2.5 mm cap and the hero evaluator ignored it. | The v1 evaluator now fails closed on the recorded body criterion. The v2 showcase requires the independent grooming contract to pass before rendering. | The plant defect remains: Track A grooming is not accepted. No persuasive replacement video may be rendered. |
| The early serial-chain ablations produced zero transitions and were confounded. | v2 is an edit of independent navigation, grooming, and feeding experiments. Feeding's readout, stimulus, and taste-without-sucrose controls run without depending on navigation or grooming transitions. | Seed 1 controls behaved independently, but the exact feeding condition itself failed. |
| Command replay, controller-only, three target positions, and a 60–90 second comparison were absent. | Both DEMO-01 and DEMO-02 now implement command replay and graph-free controller-only paths. The v2 contract freezes three targets and the renderer produces a 66-second 1080p exact-versus-ablation cut only after component validation. | The renderer correctly remains blocked because the components have not passed. |

## Feeding search result

Artifact:
`/srv/flybrain-data/evidence/demo02/feeding-operating-point-v1.json`

SHA-256:
`84908bc501176aca44be8cf4ff4414ef02becd23c5a388705ab7f9dd7ae6e2a4`

The winner's scored MN9 counts across the search's sequential concentration epochs were
`[11, 26, 30, 34]`, with Spearman `1.0`, a silent baseline, and zero recovery activity.
This is engineering calibration only and awards no tier.

The first embodied run exposed a transfer defect in that search design. The search presents
baseline and four increasing concentrations to one continuing neural state and scores aggregate
spikes. The body starts from a fresh neural state at one concentration, while the decoder requires
at least one MN9 spike in ten consecutive 15 ms intervals. The search therefore did not test the
operating condition the body actually needs.

## Embodied feeding result

The exact seed-1 probe was rerun from clean commit `3a4f893` after the evaluator and summary
schema repairs. It did not enter `ACTING`. Peak achieved extension was `0.0017 rad` against the
frozen `0.70 rad` threshold, sustained for `0 us` against `200000 us`. F1 fails and the verdict is
`NO DEMONSTRATION`.

Artifacts:

- acceptance SHA-256:
  `b577655e27b46abc3ebd7222542ac9be4fb36fa63bb2295641c2590d575abf6a`
- exact summary SHA-256:
  `9eda7d2160cfac7fded15aeefc017314e13224be7ecdbe3659bf580eafda8221`
- exact trace SHA-256:
  `383d5d5033a4bad7c97d6a03e87280634e7bc233a2ce97f8a4253de0e7864eaf`

The repaired summary explicitly names `rostrum-mn9` as the only decoded population and the F6
audit passes: pump and unresolved haustellum candidate populations are recorded but not decoded.
The remaining controls and concentrations were not rerun after F1 failed, because they cannot
rescue the existence criterion and would spend GPU time without changing the verdict.

## Additional reproducibility warning

Two clean runs with the same seed, graph, parameters, and simulation code produced the same
high-level no-extension outcome but different trace hashes across the two post-processing repair
commits. A repeat within commit `c7501b9` was byte-identical. Until the cross-process GeNN/MuJoCo
source of this difference is isolated, fixed-seed determinism must not be claimed for this path.

## Next executable gate

Do not render or publish a v2 hero yet. The shortest honest path is:

1. preregister a fresh-state feeding calibration that exercises the unchanged decoder hold rule;
2. fix grooming station-keeping and pass the unchanged 2.5 mm displacement cap;
3. implement and run the visual navigation matrix at all three frozen targets;
4. run every component and required control from one clean commit;
5. investigate fixed-seed cross-process trace divergence;
6. only then build the 66-second exact-versus-ablation cut and run `validate-v2`.

## Software verification

At clean commit `3a4f893`, the full pytest suite, repository-wide Ruff check, and strict mypy
check over all 85 source files pass. This verifies software consistency, not biological validity
or showcase acceptance.
