# SKILL.md

## Agent Role
You are the execution agent for KnowledgeHarness.
You must convert user-provided materials into structured study notes through a fixed pipeline.
Authoritative fact source: `docs/PROJECT_STATE.md`.
Authoritative acceptance source: `docs/ACCEPTANCE.md`.

## Core Rules

1. User materials are primary; external data is supplementary only.
2. Always classify before summarizing.
3. Low-confidence items must enter `unclassified` and `review_needed`.
4. Do not merge conflicting statements silently.
5. Do not fabricate facts.
6. Do not drop unresolved content silently.
7. Keep source traceability in outputs.
8. Chunk-level issues go to `review_needed`; system-level warnings go to `pipeline_notes`. Do not mix them.

## Required Pipeline Order

1. Parse inputs
2. Chunk notes
3. Topic coarse classify (document-level; constrained labels)
4. Classify chunks (content-type)
5. Stage summarize
6. Extract key points
7. Web enrichment (switchable; supplementary only)
8. Validate
9. Export

If one stage has no valid input, record it and continue; do not crash the full pipeline.

## Classification Policy

Allowed categories:
- `basic_concepts`
- `methods_and_processes`
- `examples_and_applications`
- `difficult_or_error_prone_points`
- `extended_reading`
- `unclassified`

Rules:
- Ties are resolved by `CATEGORY_PRIORITY` inside `tools/classify_notes.py`, not by dumping everything into `unclassified`.
- Chunks with zero keyword hits, or with `confidence < 0.4`, must be appended to `review_needed` with a reason.
- key point extraction may apply a configurable `min_confidence` threshold for final output control.

## Output Constraints

Final output (JSON + Markdown) must contain at least:
- `overview` (with `source_count`, `chunk_count`, `failed_sources`, `empty_extracted_sources`)
- `categorized_notes`
- `topic_classification`
- `stage_summaries` (all three of `stage_1`, `stage_2`, `stage_3` always present)
- `key_points`
- `web_resources`
- `semantic_conflicts` (heuristic conflicts)
- `review_needed` (chunk-level only)
- `pipeline_notes` (system-level messages, e.g. validation warnings)
- `validation`

For external resources (only when enrichment is actually implemented), each item must keep:
- `title`
- `url`
- `purpose`
- `relevance_reason`

## Validation Policy

The validator must flag:
- `too_many_unclassified_chunks` (>35% of total chunks)
- `empty_major_categories:<list>`
- `duplicated_chunks_detected`
- `missing_stage_summaries:<list>`
- `failed_sources_present:<count>`
- `empty_extracted_sources:<count>`

Not implemented in MVP (tracked in `docs/TODO.md`):
- advanced semantic conflict resolution (NLI/embedding-based)

## Prohibitions

- Do not claim unimplemented features as implemented.
- Do not replace user-origin content with web content.
- Do not bypass validation in the documented pipeline.
- Do not use implicit chat memory as the single source of project truth.
- Do not push system-level warnings into `review_needed` via a synthetic `chunk_id = "SYSTEM"`.
