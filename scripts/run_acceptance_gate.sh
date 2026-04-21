#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="outputs/_acceptance_gate"

echo "[gate] running stdlib test scripts"
for t in tests/test_*.py; do
  echo "[gate] python3 $t"
  python3 "$t" >/dev/null
done

echo "[gate] running pipeline smoke on samples/demo.md"
python3 app.py samples/demo.md --output-dir "$OUT_DIR" --quiet >/dev/null

echo "[gate] checking result contract"
python3 - <<'PY'
import json
from pathlib import Path

result_path = Path("outputs/_acceptance_gate/result.json")
if not result_path.exists():
    raise SystemExit(f"missing result file: {result_path}")

result = json.loads(result_path.read_text(encoding="utf-8"))
required_keys = {
    "overview",
    "source_documents",
    "topic_classification",
    "categorized_notes",
    "stage_summaries",
    "key_points",
    "web_resources",
    "semantic_conflicts",
    "review_needed",
    "pipeline_notes",
    "validation",
}
missing = sorted(required_keys - set(result.keys()))
if missing:
    raise SystemExit("missing required keys: " + ",".join(missing))

validation = result.get("validation") or {}
if validation.get("is_valid") is not True:
    raise SystemExit("demo acceptance failed: validation.is_valid != True")
print("[gate] acceptance pass")
PY

echo "[gate] done"
