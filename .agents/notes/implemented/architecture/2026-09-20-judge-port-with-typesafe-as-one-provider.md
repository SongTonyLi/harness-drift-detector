# Agent Note: Judge port with TypeSafe as one provider

Status: implemented

## Problem

The detector needs semantic judgments (does this step address the request, does this claim match the tool output) that code cannot compute, and the first provider of those judgments is TypeSafe's System One model. Binding the detector to that SDK would make the scoring logic untestable without network access, would couple threshold and report code to one vendor's response types, and would block a second provider (a local model, a heuristic, a different vendor) from being compared on the same transcripts.

## Decision

The domain defines a `Judge` protocol in `domain/judgment.py`: `name`, `model`, and `async judge(state, probes) -> JudgeResult`, where a `JudgeResult` holds one `Judgment(probe_id, probability, confidence, raw)` per probe. `probability` always means P(drift) for a Noul probe and the normalized expected level for a Score probe, so policy and report code never see provider payloads. `TypeSafeJudge` in `adapters/typesafe_judge.py` is the only module that imports `typesafe_sdk`; `HeuristicJudge` is a second, offline provider; `CachingJudge` decorates any provider; `FakeJudge` scripts answers for tests. `cli.py` maps `--judge` names to adapters. `scripts/verify_layering.py` rejects `typesafe_sdk` imports elsewhere and any third-party import inside `domain/` or `application/`.

## Alternatives considered

**Call the SDK directly from the detect use case.** Fewer files, but every unit test of windowing, gating, and reporting would need a network stub shaped like the vendor response, and the threshold policy would be entangled with SDK types.

**A generic "LLM judge" port that returns free text.** Would admit chat models, but the domain would then parse text into probabilities, reintroducing the prompt-and-parse fragility System One models exist to remove. The port returns typed probabilities; a chat-model adapter can still implement it by parsing on its side.

**Provider-specific probe objects.** Letting each adapter define its own question types would let TypeSafe-specific features leak into the catalog. The catalog stays provider-neutral (`NoulProbe`, `ScoreProbe`) and adapters translate.

## Consequences

Domain and application tests run with no network. A new provider is one adapter file, one test, and one `cli.py` entry. Providers can be compared on identical windows. The cost is a translation layer per provider and the discipline of keeping `probability` semantics identical across them.
