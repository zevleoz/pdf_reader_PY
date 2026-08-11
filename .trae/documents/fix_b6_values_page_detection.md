# Fix B6 Values Page Detection (初中版 vs 高中版)

## Problem

B6 PDF comes in two versions — 初中版 (middle school) and 高中版 (high school). The 职业价值观 (career values) page is at:
- **初中版**: page 12 (index 11)
- **高中版**: page 15 (index 14)

The current code has **three places** that hardcode or detect the values page, and they're inconsistent or unreliable:

1. **`_vision_values_bar.py:find_values_page()` (L313-L325)** — Uses total page count (≤23 → 初中版, >23 → 高中版). This is the primary detection used by the vision API path.
2. **`extract.py` (L2500-L2513)** — Hardcodes `_doc[11]` (always page 12) for OCR fallback. **Does NOT adapt to 高中版.**
3. **`extract.py` (L2557-L2564)** — Hardcodes `_doc[13]` (always page 14) for image processing fallback. **Does NOT adapt to either version correctly.**

## Proposed Changes

### Change 1: Add `detect_b6_version()` to `_vision_values_bar.py`

Add a function that scans B6 PDF text pages for "初中版" or "高中版" keywords:

```python
def detect_b6_version(pdf_path: Path) -> str:
    """Detect B6 version by searching for 初中版/高中版 in PDF text.
    Returns '初中版' or '高中版'.
    """
    doc = fitz.open(str(pdf_path))
    for i in range(min(len(doc), 5)):  # check first 5 pages
        text = doc[i].get_text()
        if "高中版" in text:
            doc.close()
            return "高中版"
        if "初中版" in text:
            doc.close()
            return "初中版"
    doc.close()
    # Fallback: by page count
    doc = fitz.open(str(pdf_path))
    total = len(doc)
    doc.close()
    return "初中版" if total <= 23 else "高中版"
```

### Change 2: Update `find_values_page()` in `_vision_values_bar.py` (L313-L325)

Replace page-count-based detection with text-based detection:

```python
def find_values_page(pdf_path: Path) -> int:
    """Detect values page by B6 version.
    初中版 → page 12 (index 11)
    高中版 → page 15 (index 14)
    """
    version = detect_b6_version(pdf_path)
    if version == "初中版":
        return 11  # 第 12 页
    return 14  # 第 15 页
```

### Change 3: Fix hardcoded page index in `extract.py` (L2500-L2513)

The OCR fallback at L2504 hardcodes `_doc[11]`. Replace with dynamic detection:

```python
from _vision_values_bar import detect_b6_version
version = detect_b6_version(b6_pdf)
page_idx = 11 if version == "初中版" else 14
_page = _doc[page_idx]
```

### Change 4: Fix hardcoded page index in `extract.py` (L2557-L2564)

The image processing fallback at L2563 hardcodes `_doc[13]`. Replace with dynamic detection:

```python
from _vision_values_bar import detect_b6_version
version = detect_b6_version(b6_pdf)
page_idx = 11 if version == "初中版" else 14
_page = _doc[page_idx]
```

## Files to Modify

1. **`_vision_values_bar.py`** — Add `detect_b6_version()`, update `find_values_page()`
2. **`extract.py`** — Fix two hardcoded page indices (L2504, L2563) to use `detect_b6_version()`

## Verification

1. Upload 初中版 B6 → check server logs show "初中版" and page 12
2. Upload 高中版 B6 → check server logs show "高中版" and page 15
3. Confirm 价值观排名 (codes 110-124) are correct in generated PDF
