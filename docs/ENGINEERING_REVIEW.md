# ENGINEERING REVIEW

Last Updated: 2026-04-21

## 1) Scope and Goal

This review is the project-level truth snapshot for:

- current implemented capabilities
- current quality/acceptance status
- known defects and engineering constraints
- prioritized optimization roadmap

It is written in Harness Engineering style: state first, then gaps, then executable next steps.

## 2) Capability Coverage (Current Truth)

| Layer | Status | Notes |
|------|--------|------|
| Input parsing (`txt/md/pdf/docx`) | Implemented | with structured failure semantics |
| Image ingestion (`png/jpg/jpeg`) | Implemented (opt-in OCR) | true OCR requires `pytesseract + Pillow + tesseract` |
| Chunking | Implemented | paragraph -> sentence -> char fallback |
| Topic coarse classification | Implemented | document-level, constrained taxonomy, optional API assist |
| Content-type classification | Implemented | chunk-level rules + tie-break priority + review queue |
| Stage summarize (1/2/3) | Implemented | fixed three-stage output contract |
| Key points extraction | Implemented | category priority + confidence threshold + max cap |
| Web enrichment | Implemented | `off/local/api/auto`, failure-tolerant fallback |
| Semantic conflict detection | Implemented (heuristic) | rule-based, not NLI/embedding |
| Validation | Implemented | warning-based, strict by default |
| Export (`json/md/docx`) | Implemented | final-notes mode + full-report mode |
| Local Web UI | Implemented | stdlib-only, upload pool, settings console, safety checks |
| FastAPI/Flask service entry | Implemented | minimal wrappers, same core pipeline |
| Desktop package build | Implemented | PyInstaller-based |

## 3) Verified Quality Snapshot

Audit commands executed on 2026-04-21:

```bash
for t in tests/test_*.py; do python3 "$t"; done
python3 app.py samples/demo.md --output-dir outputs/audit_demo --quiet
python3 app.py samples/ingest_demo.docx --output-dir outputs/audit_docx --quiet --export-docx
python3 app.py samples/ingest_demo.png --output-dir outputs/audit_png --quiet --export-docx
python3 app.py samples/ --output-dir outputs/audit_mix --quiet
```

Test baseline:

- `tests/test_*.py`: 7 scripts, 82 passed (including optional-dependency SKIP semantics)

Observed results:

| Scenario | `validation.is_valid` | Warnings |
|----------|------------------------|----------|
| `samples/demo.md` | `True` | `[]` |
| `samples/` (mixed) | `True` | `[]` |
| `samples/ingest_demo.docx` | `False` | `["too_many_unclassified_chunks"]` |
| `samples/ingest_demo.png` | `False` | `["too_many_unclassified_chunks", "empty_major_categories:..."]` |

Interpretation:

- pipeline stability is good (no crashes, outputs complete)
- strict validation can mark sparse inputs as invalid even when extraction and summarization succeed

## 4) Known Defects and Constraints

| ID | Item | Type | Impact | Suggested Direction |
|----|------|------|--------|---------------------|
| D-01 | Validation strictness for sparse/OCR documents | behavior gap | raises false-negative validity for small but useful notes | add `validation_profile` (`strict/lenient`) and context-aware thresholds |
| D-02 | UI download endpoint only serves `outputs/` root files | UX constraint | subdirectory outputs require manual file browsing | add optional safe subpath tokenized download flow |
| D-03 | UI HTTP layer lacks automated tests | test gap | regressions may slip in UI request parsing/safety checks | add `tests/test_simple_ui.py` (multipart, limits, download guard, settings masking) |
| D-04 | Rule dictionaries/taxonomy coverage is manual | quality ceiling | more `unclassified` / `unknown_topic` on domain-shifted notes | build iterative tuning workflow from real corpora stats |
| D-05 | Binary package in repo history | repo hygiene risk | repo growth and slower clone history | move artifacts to GitHub Releases in a future delivery policy |

## 5) Optimization Roadmap

### P0 (next hardening cycle)

1. Validation profile and threshold policy.
2. UI HTTP automation for safety-critical routes.
3. Real API integration acceptance (external endpoint ready).

### P1 (quality and maintainability)

1. Topic taxonomy tuning workflow (`unknown_topic` rate monitoring).
2. Content keyword dictionary governance (domain packs).
3. Subdirectory-safe download UX improvement.

### P2 (capability upgrades)

1. NLI/embedding semantic conflict engine (keep heuristic as fast pre-filter).
2. Topic-based secondary reorganization (notes per topic bundle).
3. Release artifact policy (CI build + signed checksums + release assets).

## 6) Harness Engineering Governance Actions

For every future significant change:

1. Update `docs/PROJECT_STATE.md` with implementation truth.
2. Update `docs/TODO.md` with priority and ownership.
3. Update `docs/HANDOFF.md` with next-step decisions.
4. If rule contracts changed, update `docs/ACCEPTANCE.md`.
5. Refresh this file (`docs/ENGINEERING_REVIEW.md`) for release-level snapshots.

## 7) Non-Implemented (Still True)

- advanced semantic conflict resolution (NLI/vector)
- production-grade service concerns (auth/rate-limit/queue/audit)
- full pytest/httpx infrastructure
- true API联调 completion (blocked by external production endpoint contract)
