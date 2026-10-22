"""Growth Talk 上传解析契约测试。"""
import fitz
import pytest

from growth_talk.upload import MAX_UPLOAD_BYTES, UploadError, extract_upload


def test_txt_passthrough():
    assert extract_upload("a.txt", "你好".encode()) == "你好"


def test_md_and_json_passthrough():
    assert extract_upload("a.md", b"# title") == "# title"
    assert extract_upload("a.json", b'{"a":1}') == '{"a":1}'


def test_oversize_rejected():
    with pytest.raises(UploadError) as error:
        extract_upload("a.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))
    assert error.value.status == 400
    assert "25 MB" in error.value.message


def test_empty_rejected():
    with pytest.raises(UploadError) as error:
        extract_upload("a.txt", b"")
    assert error.value.status == 400


def test_bad_extension():
    with pytest.raises(UploadError) as error:
        extract_upload("a.exe", b"x")
    assert error.value.message == "仅支持 PDF / DOCX / TXT / MD / JSON"


def test_pdf_without_text_layer():
    doc = fitz.open()
    doc.new_page()
    data = doc.tobytes()
    with pytest.raises(UploadError) as error:
        extract_upload("scan.pdf", data)
    assert error.value.status == 422
    assert "没有可提取的文字" in error.value.message


def test_damaged_docx():
    with pytest.raises(UploadError) as error:
        extract_upload("a.docx", b"not a zip")
    assert error.value.status == 422
    assert "DOCX 无法读取" in error.value.message


def test_pdf_with_text_roundtrip():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello PDF text")
    data = doc.tobytes()
    assert "Hello PDF text" in extract_upload("note.pdf", data)


def test_encrypted_pdf():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="x")
    with pytest.raises(UploadError) as error:
        extract_upload("locked.pdf", data)
    assert error.value.status == 422
    assert "密码保护" in error.value.message


def test_corrupt_pdf():
    with pytest.raises(UploadError) as error:
        extract_upload("broken.pdf", b"%PDF-1.4 definitely not a pdf")
    assert error.value.status == 422
    assert "PDF 无法读取" in error.value.message or "PDF 读取失败" in error.value.message


def test_empty_txt_body():
    with pytest.raises(UploadError) as error:
        extract_upload("empty.txt", b"   \n")
    assert error.value.message == "没有读取到正文，请上传可复制文字的文件"
