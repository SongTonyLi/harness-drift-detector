---
name: hdd-code-review
description: Use when reviewing a pull request or a diff in the harness-drift-detector repo; orients the reviewer to the dependency rule, the probe design rules, the gate semantics, transcript-format fidelity, secret hygiene, and the review checks that the mechanical gates cannot make.
---

# Reviewing a harness-drift-detector change

Guidance, not a checklist. Read the diff and enough surrounding code to understand the design. Prioritize correctness, wrong judgments, and leaked data over style; one substantiated blocker beats a list of nits.

## Sources of truth

- [AGENTS.md](../../../AGENTS.md): standing rules.
- [docs/architecture.md](../../../docs/architecture.md): layers, data flow, canonical JSONL, extension points.
- [Agent Notes](../../notes/README.md): rationale for the judge port, the probe design, the data policy, and the gates. Treat disagreement with a note as a design discussion, not a veto.
- [TypeSafe SDE cascade cookbook](https://docs.typesafe.ai/cookbooks/sde_cascade) and [Jev jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13): what a good verifier signal looks like and what the model gets wrong.

## Blocking requirements

1. **Dependency rule holds.** `domain/` has no third-party or outer-layer imports; `typesafe_sdk` appears only in `adapters/typesafe_judge.py`. The gate checks imports; you check for provider concepts smuggled in as strings or dict keys.
2. **Probe semantics.** Every Noul reads named state fields, its `true_criteria` describes drift, its `false_criteria` describes the non-drift case, and the two are not a double negative of each other. A new probe has a precondition in `select_probes`, a domain test for that precondition, and a README row. Scores never fire hotspots.
3. **Gate is max-style.** No averaging of probe probabilities into a hotspot decision. Thresholds come from `DriftPolicy`, never literals in application or adapters.
4. **Probability semantics are uniform across judges.** A new or changed adapter returns P(drift) for Nouls and `score / (levels - 1)` for Scores, one `Judgment` per requested probe, and raises on transport failure rather than returning partial results.
5. **Transcript fidelity.** Converter changes keep turn numbers from `turn/start`, map tool results to their call ids, mark harness-injected messages `origin: "harness"`, drop replay blobs, and scrub credentials. Verify with the synthetic fixture, not a real session.
6. **No private data.** Nothing under `data/`, `reports/`, or `.hdd-cache/` is tracked; no transcript excerpts, home-directory paths beyond `~/.dsh/sessions`, or credentials in code, tests, docs, or messages.
7. **Docs match the code.** New CLI flags, probes, or format fields update README and `docs/architecture.md` in the same diff. A durable decision adds or updates an Agent Note.
8. **Evidence exists.** The author ran the checks that [hdd-pre-push-checks](../hdd-pre-push-checks/SKILL.md) selects for the diff; CI is green or its failure is explained.

## Manual checks

- **Window state minimality:** does the change add fields a probe never reads? Extra state costs accuracy.
- **Truncation:** head/tail boundaries and the omitted-chars marker; multibyte text; empty inputs.
- **Multi-step turns:** `previous_message` for step N is step N-1's results; `previous_assistant_text` is step N-1's text; `ends_turn` on the last turn without a `turn_end` event.
- **Concurrency:** the semaphore bounds judge calls; one failing window is recorded, never raises out of `DetectDrift`.
- **Cache key:** stable across dict ordering and float formatting; changes when probe wording changes; ignores thresholds.
- **Renderers:** empty report, report with only failed windows, hotspot with empty assistant text.
- **Tests describe behavior:** assertions fail on the intended regression and do not restate the implementation.

## Reporting

State the defect, location, impact, and evidence. Separate blockers from suggestions. Omit anything a green gate already enforces. When receiving review, verify each claim and fix or rebut it on technical grounds.
