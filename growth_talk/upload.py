"""Growth Talk 素材解析（移植自 first-touch lib/upload.ts、lib/pdf-text.ts）。"""
from __future__ import annotations

import io
import os

import fitz  # PyMuPDF

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_TEXT_EXTENSIONS = {".txt", ".md", ".json"}


class UploadError(Exception):
    """带 HTTP 状态与中文用户文案的上传解析错误。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def extract_upload(filename: str, data: bytes) -> str:
    """按扩展名提取文本；错误分类逐字对齐 first-touch。"""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(400, "文件不能为空且不能超过 25 MB")

    extension = os.path.splitext(filename or "")[1].lower()
    if extension in _TEXT_EXTENSIONS:
        text = data.decode("utf-8", errors="replace").strip()
    elif extension == ".docx":
        text = _extract_docx(data)
    elif extension == ".pdf":
        text = _extract_pdf(data)
    else:
        raise UploadError(400, "仅支持 PDF / DOCX / TXT / MD / JSON")

    if not text:
        raise UploadError(422, "没有读取到正文，请上传可复制文字的文件")
    return text


def _extract_docx(data: bytes) -> str:
    try:
        from docx import Document

        document = Document(io.BytesIO(data))
        text = "\n".join(p.text for p in document.paragraphs if p.text.strip()).strip()
    except Exception as exc:
        print("[first-touch] DOCX extraction failed", exc, flush=True)
        raise UploadError(422, "DOCX 无法读取，请确认文件未损坏且格式正确后重新上传")
    if not text:
        raise UploadError(422, "没有读取到正文，请上传可复制文字的文件")
    return text


def _extract_pdf(data: bytes) -> str:
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        if _is_password_error(exc):
            raise UploadError(422, "PDF 有密码保护，请解除密码后重新上传")
        print("[first-touch] PDF extraction failed", exc, flush=True)
        raise UploadError(422, "PDF 无法读取，请确认文件未损坏且格式正确后重新上传")

    try:
        if getattr(document, "needs_pass", False) or getattr(document, "is_encrypted", False):
            raise UploadError(422, "PDF 有密码保护，请解除密码后重新上传")
        text = "".join(page.get_text() for page in document).strip()
    except UploadError:
        raise
    except Exception as exc:
        print("[first-touch] PDF extraction failed", exc, flush=True)
        raise UploadError(422, "PDF 读取失败，请确认文件可正常打开且包含可复制文字后重新上传")
    finally:
        try:
            document.close()
        except Exception:
            pass

    if not text:
        raise UploadError(422, "PDF 中没有可提取的文字，请上传可复制文字的 PDF、DOCX，或直接粘贴文字")
    return text


def _is_password_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    return "password" in name or "encrypt" in name
