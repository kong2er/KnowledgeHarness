"""Input parsing utilities for KnowledgeHarness.

Supported input matrix (see docs/PROJECT_STATE.md §2):

- txt / md           : stdlib only
- pdf                : requires `pypdf` (declared in requirements.txt)
- docx               : requires `python-docx` (declared in requirements.txt)
- png / jpg / jpeg   : opt-in OCR via `pytesseract` + `Pillow` + tesseract
                       binary. When any of those is missing the parser
                       degrades gracefully with reason=ocr_backend_unavailable
                       rather than silently pretending success.

Failure semantics (see docs/ACCEPTANCE.md §4 `parse_inputs`):

    failed_sources entry = {
        "source": str(path),
        "source_name": basename,
        "source_type": ext without leading dot,
        "reason": one of UNSUPPORTED_FILE_TYPE | FILE_NOT_FOUND
                       | PARSE_ERROR | OCR_BACKEND_UNAVAILABLE,
        "error": human-readable detail,
    }

A per-file ``notifier`` callback is available so the CLI layer can surface
real-time ingestion progress without coupling this module to stdout.
"""

from __future__ import annotations

import shutil
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

# --- Extension sets -----------------------------------------------------

TEXT_EXTENSIONS: frozenset = frozenset({".txt", ".md"})
PDF_EXTENSIONS: frozenset = frozenset({".pdf"})
DOCX_EXTENSIONS: frozenset = frozenset({".docx"})
IMAGE_EXTENSIONS: frozenset = frozenset({".png", ".jpg", ".jpeg"})

# Full declared support surface (what app.py should glob for in dir mode).
SUPPORTED_EXTENSIONS: frozenset = (
    TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | IMAGE_EXTENSIONS
)

# --- Failure reason constants ------------------------------------------

UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
FILE_NOT_FOUND = "file_not_found"
PARSE_ERROR = "parse_error"
OCR_BACKEND_UNAVAILABLE = "ocr_backend_unavailable"

# --- Notifier callback type --------------------------------------------

Notifier = Callable[[str, Dict[str, Any]], None]


def _emit(notifier: Optional[Notifier], event: str, payload: Dict[str, Any]) -> None:
    if notifier is None:
        return
    try:
        notifier(event, payload)
    except Exception:
        # Notifier must never break the pipeline.
        pass


# --- Custom exceptions --------------------------------------------------


class UnsupportedFileType(ValueError):
    """Raised when the file extension is not in SUPPORTED_EXTENSIONS."""


class OCRBackendUnavailable(RuntimeError):
    """Raised when pytesseract / Pillow / tesseract binary is missing."""


# --- Readers ------------------------------------------------------------


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf_file(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency probe
        raise RuntimeError(
            "PDF parsing requires 'pypdf'. Run: pip install -r requirements.txt"
        ) from exc

    reader = PdfReader(str(path))
    pages: List[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n\n".join(pages).strip()


def _read_docx_file(path: Path) -> str:
    try:
        from docx import Document  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency probe
        raise RuntimeError(
            "DOCX parsing requires 'python-docx'. "
            "Run: pip install -r requirements.txt"
        ) from exc

    document = Document(str(path))
    parts: List[str] = []
    heading_stack: Dict[int, str] = {}

    def _heading_level(style_name: str) -> Optional[int]:
        raw = (style_name or "").strip()
        s = raw.lower()
        # English style variants: Heading 1 / Heading1 / heading 2 ...
        m = re.match(r"heading\s*(\d*)", s)
        if m:
            num = m.group(1)
            return int(num) if num else 1
        # Chinese localized style variants, e.g. 标题 1 / 标题1
        if "标题" in raw:
            m = re.search(r"标题\s*(\d*)", raw)
            if m:
                num = m.group(1)
                return int(num) if num else 1
        return None

    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue

        level = _heading_level(getattr(getattr(para, "style", None), "name", ""))
        if level is not None:
            heading_stack[level] = text
            for k in list(heading_stack.keys()):
                if k > level:
                    del heading_stack[k]
            parts.append(text)
            continue

        if heading_stack:
            path_text = " > ".join(heading_stack[k] for k in sorted(heading_stack.keys()))
            parts.append(f"{text} [heading_path: {path_text}]")
        else:
            parts.append(text)

    for table in document.tables:
        for row in table.rows:
            cells = [(cell.text or "").strip() for cell in row.cells]
            joined = " | ".join(c for c in cells if c)
            if joined:
                parts.append(joined)

    return "\n\n".join(parts).strip()


# OCR backend probe result is cached per-process; the check is cheap but
# doing it once avoids repeating the same warning for every image file.
_OCR_PROBE_CACHE: Optional[Tuple[bool, str]] = None


def _probe_ocr_backend() -> Tuple[bool, str]:
    """Return (available, detail_message)."""
    global _OCR_PROBE_CACHE
    if _OCR_PROBE_CACHE is not None:
        return _OCR_PROBE_CACHE

    try:
        import pytesseract  # type: ignore  # noqa: F401
        from PIL import Image  # type: ignore  # noqa: F401
    except Exception as exc:
        _OCR_PROBE_CACHE = (
            False,
            f"python packages missing (pytesseract/Pillow): {exc}",
        )
        return _OCR_PROBE_CACHE

    if not shutil.which("tesseract"):
        _OCR_PROBE_CACHE = (
            False,
            "tesseract system binary not found on PATH; "
            "install it via your OS package manager "
            "(e.g. `apt-get install tesseract-ocr`).",
        )
        return _OCR_PROBE_CACHE

    try:
        import pytesseract  # type: ignore

        pytesseract.get_tesseract_version()
    except Exception as exc:
        _OCR_PROBE_CACHE = (False, f"tesseract invocation failed: {exc}")
        return _OCR_PROBE_CACHE

    _OCR_PROBE_CACHE = (True, "pytesseract")
    return _OCR_PROBE_CACHE


def _read_image_file(
    path: Path,
    ocr_languages: str = "chi_sim+eng",
    ocr_fallback_language: str = "eng",
) -> str:
    available, detail = _probe_ocr_backend()
    if not available:
        raise OCRBackendUnavailable(detail)

    from PIL import Image  # type: ignore
    import pytesseract  # type: ignore

    with Image.open(str(path)) as img:
        # Prefer Chinese+English joint OCR; fall back to English-only when
        # the chi_sim language pack is unavailable.
        try:
            text = pytesseract.image_to_string(img, lang=ocr_languages)
        except pytesseract.TesseractError:
            text = pytesseract.image_to_string(img, lang=ocr_fallback_language)

    return (text or "").strip()


# --- Per-file dispatch --------------------------------------------------


def parse_single_file(
    path: str | Path,
    ocr_languages: str = "chi_sim+eng",
    ocr_fallback_language: str = "eng",
) -> Dict[str, Any]:
    """Parse one file into a normalized document object.

    Raises:
        FileNotFoundError: path does not point to an existing file.
        UnsupportedFileType: extension not in SUPPORTED_EXTENSIONS.
        OCRBackendUnavailable: image file, but OCR backend missing.
        Exception: any other parse-level failure from the underlying reader.
    """
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    ext = file_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(f"Unsupported file type: {file_path.name}")

    if ext in TEXT_EXTENSIONS:
        extracted = _read_text_file(file_path)
    elif ext in PDF_EXTENSIONS:
        extracted = _read_pdf_file(file_path)
    elif ext in DOCX_EXTENSIONS:
        extracted = _read_docx_file(file_path)
    elif ext in IMAGE_EXTENSIONS:
        extracted = _read_image_file(
            file_path,
            ocr_languages=ocr_languages,
            ocr_fallback_language=ocr_fallback_language,
        )
    else:  # pragma: no cover - SUPPORTED_EXTENSIONS covers all branches
        raise UnsupportedFileType(f"Unsupported file type: {file_path.name}")

    return {
        "source_name": file_path.name,
        "source_path": str(file_path.resolve()),
        "source_type": ext.lstrip("."),
        "chunk_id": None,
        "raw_text": extracted,
        "extracted_text": extracted,
    }


# --- Batch driver -------------------------------------------------------


def _effective_supported_extensions() -> List[str]:
    """Return extensions we can actually fulfil in the current environment.

    - txt/md : always
    - pdf    : always (pypdf is in requirements.txt)
    - docx   : only when python-docx is importable
    - images : only when OCR backend probe passes
    """
    eff = sorted(TEXT_EXTENSIONS | PDF_EXTENSIONS)
    try:
        import docx  # type: ignore  # noqa: F401

        eff.extend(sorted(DOCX_EXTENSIONS))
    except Exception:
        pass
    if _probe_ocr_backend()[0]:
        eff.extend(sorted(IMAGE_EXTENSIONS))
    return sorted(set(eff))


def _build_failed_entry(
    path: str,
    ext: str,
    reason: str,
    error: str,
) -> Dict[str, Any]:
    name = Path(path).name
    return {
        "source": str(path),
        "source_name": name,
        "source_type": ext.lstrip(".") if ext else "",
        "reason": reason,
        "error": error,
    }


def parse_inputs(
    paths: Iterable[str | Path],
    notifier: Optional[Notifier] = None,
    ocr_languages: str = "chi_sim+eng",
    ocr_fallback_language: str = "eng",
) -> Dict[str, Any]:
    """Parse multiple input files with optional progress notification.

    Returns:
        {
          "documents": [ ... ],
          "logs": {
            "failed_sources": [ ... ],
            "empty_extracted_sources": [ ... ],
          },
          "ingestion_summary": {
            "detected": N,
            "supported": N,
            "unsupported": N,
            "succeeded": N,
            "empty_extracted": N,
            "failed": N,
            "breakdown_by_type": {"md": 1, "docx": 1, ...},
            "supported_extensions_effective": [".txt", ".md", ...],
            "image_extensions_opt_in": [".png", ".jpg", ".jpeg"],
            "ocr_backend": "pytesseract" | "unavailable",
          }
        }
    """
    path_list: List[str] = [str(p) for p in paths]
    documents: List[Dict[str, Any]] = []
    failed_sources: List[Dict[str, Any]] = []
    empty_extracted_sources: List[str] = []
    breakdown: Dict[str, int] = {}

    ocr_available, _ = _probe_ocr_backend()
    effective_exts = _effective_supported_extensions()

    _emit(
        notifier,
        "detected",
        {
            "count": len(path_list),
            "supported_extensions_effective": effective_exts,
            "ocr_backend": "pytesseract" if ocr_available else "unavailable",
        },
    )

    supported_count = 0
    unsupported_count = 0

    for path in path_list:
        ext = Path(path).suffix.lower()
        name = Path(path).name
        is_supported = ext in SUPPORTED_EXTENSIONS
        if is_supported:
            supported_count += 1
        else:
            unsupported_count += 1

        breakdown[ext.lstrip(".") or "(noext)"] = (
            breakdown.get(ext.lstrip(".") or "(noext)", 0) + 1
        )

        _emit(
            notifier,
            "start",
            {
                "source_name": name,
                "source_path": path,
                "source_type": ext.lstrip("."),
                "supported": is_supported,
            },
        )

        try:
            doc = parse_single_file(
                path,
                ocr_languages=ocr_languages,
                ocr_fallback_language=ocr_fallback_language,
            )
        except UnsupportedFileType as exc:
            failed_sources.append(
                _build_failed_entry(path, ext, UNSUPPORTED_FILE_TYPE, str(exc))
            )
            _emit(
                notifier,
                "failed",
                {
                    "source_name": name,
                    "reason": UNSUPPORTED_FILE_TYPE,
                    "error": str(exc),
                },
            )
            continue
        except FileNotFoundError as exc:
            failed_sources.append(
                _build_failed_entry(path, ext, FILE_NOT_FOUND, str(exc))
            )
            _emit(
                notifier,
                "failed",
                {
                    "source_name": name,
                    "reason": FILE_NOT_FOUND,
                    "error": str(exc),
                },
            )
            continue
        except OCRBackendUnavailable as exc:
            failed_sources.append(
                _build_failed_entry(
                    path, ext, OCR_BACKEND_UNAVAILABLE, str(exc)
                )
            )
            _emit(
                notifier,
                "failed",
                {
                    "source_name": name,
                    "reason": OCR_BACKEND_UNAVAILABLE,
                    "error": str(exc),
                },
            )
            continue
        except Exception as exc:  # any other parse-level failure
            failed_sources.append(
                _build_failed_entry(path, ext, PARSE_ERROR, str(exc))
            )
            _emit(
                notifier,
                "failed",
                {
                    "source_name": name,
                    "reason": PARSE_ERROR,
                    "error": str(exc),
                },
            )
            continue

        extracted = (doc.get("extracted_text") or "").strip()
        is_empty = not extracted
        if is_empty:
            empty_extracted_sources.append(doc.get("source_name") or path)

        documents.append(doc)
        _emit(
            notifier,
            "success",
            {
                "source_name": doc.get("source_name"),
                "chars": len(extracted),
                "empty": is_empty,
            },
        )

    ingestion_summary = {
        "detected": len(path_list),
        "supported": supported_count,
        "unsupported": unsupported_count,
        "succeeded": len(documents) - len(empty_extracted_sources),
        "empty_extracted": len(empty_extracted_sources),
        "failed": len(failed_sources),
        "breakdown_by_type": breakdown,
        "supported_extensions_effective": effective_exts,
        "image_extensions_opt_in": sorted(IMAGE_EXTENSIONS),
        "ocr_backend": "pytesseract" if ocr_available else "unavailable",
    }

    _emit(notifier, "summary", dict(ingestion_summary))

    return {
        "documents": documents,
        "logs": {
            "failed_sources": failed_sources,
            "empty_extracted_sources": empty_extracted_sources,
        },
        "ingestion_summary": ingestion_summary,
    }


if __name__ == "__main__":
    import json
    import sys

    parsed = parse_inputs(sys.argv[1:])
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
