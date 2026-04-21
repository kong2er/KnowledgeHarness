# ENGINEERING REVIEW

Last Updated: 2026-04-22

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
| Image ingestion (`png/jpg/jpeg`) | Implemented (opt-in OCR + optional API OCR assist) | local OCR preferred; API OCR supports `fallback_only/auto/prefer_api` and can auto-select better result |
| Chunking | Implemented | paragraph -> sentence -> char fallback |
| Topic coarse classification | Implemented | document-level, constrained taxonomy, optional API assist |
| Content-type classification | Implemented | chunk-level rules + tie-break priority + review queue |
| Stage summarize (1/2/3) | Implemented | fixed three-stage output contract |
| Key points extraction | Implemented | category priority + confidence threshold + max cap |
| Web enrichment | Implemented | `off/local/api/auto`, failure-tolerant fallback |
| Semantic conflict detection | Implemented (heuristic) | rule-based, not NLI/embedding |
| Validation | Implemented | warning-based; supports `strict/lenient` profile |
| Export (`json/md/docx`) | Implemented | final-notes mode + full-report mode |
| Local Web UI | Implemented | stdlib-only, upload pool, settings console, safety checks |
| FastAPI/Flask service entry | Implemented | minimal wrappers, same core pipeline |
| Desktop package build | Implemented | PyInstaller-based |

## 3) Verified Quality Snapshot

Audit commands executed on 2026-04-22:

```bash
for t in tests/test_*.py; do python3 "$t"; done
python3 app.py samples/demo.md --output-dir outputs/audit_demo --quiet
python3 app.py samples/ingest_demo.docx --output-dir outputs/audit_docx --quiet --export-docx
python3 app.py samples/ingest_demo.png --output-dir outputs/audit_png --quiet --export-docx
python3 app.py samples/ --output-dir outputs/audit_mix --quiet
```

Test baseline:

- `tests/test_*.py`: 9 scripts（含 `test_simple_ui.py`；可选依赖/受限环境按 SKIP 语义）

Observed results:

| Scenario | `validation.is_valid` | Warnings |
|----------|------------------------|----------|
| `samples/demo.md` | `True` | `[]` |
| `samples/` (mixed) | `True` | `[]` |
| `samples/ingest_demo.docx` | `False` | `["too_many_unclassified_chunks"]` |
| `samples/ingest_demo.png` | `False` | `["too_many_unclassified_chunks", "empty_major_categories:..."]` |

Interpretation:

- pipeline stability is good (no crashes, outputs complete)
- sparse/OCR 场景可通过 `validation_profile=lenient` 降低误报

## 4) Known Defects and Constraints

| ID | Item | Type | Impact | Suggested Direction |
|----|------|------|--------|---------------------|
| D-02 | UI download endpoint only serves `outputs/` root files | UX constraint | subdirectory outputs require manual file browsing | add optional safe subpath tokenized download flow |
| D-04 | Rule dictionaries/taxonomy coverage is manual | quality ceiling | more `unclassified` / `unknown_topic` on domain-shifted notes | build iterative tuning workflow from real corpora stats |
| D-05 | Binary package in repo history | repo hygiene risk | repo growth and slower clone history | move artifacts to GitHub Releases in a future delivery policy |

## 5) Optimization Roadmap

### P0 (next hardening cycle)

1. Real API integration acceptance (external endpoint ready).

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
