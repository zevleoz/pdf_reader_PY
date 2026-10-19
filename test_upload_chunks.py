"""分片上传传输层测试（unittest；项目环境没有 pytest）。

覆盖生产修复的关键不变量：
- 同一 chunk_index 重发（模拟响应丢失后的重试）必须幂等，不能写重复字节；
- 乱序分片按 index 合并；
- 缺片 / total 不一致 / 新旧格式混用必须拒绝，且不能清空上一份 input/；
- 旧版 <KEY>.part 仍可读取；
- B6 高中/初中目标名保持不变。
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from flask import Flask

import blueprints.reports as reports


class UploadChunkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.upload_dir = root / "uploads"
        self.input_dir = root / "input"
        self.data_dir = root / "data"
        self.input_dir.mkdir(parents=True)
        self.data_dir.mkdir(parents=True)

        self._saved = {
            name: getattr(reports, name)
            for name in ("UPLOAD_DIR", "INPUT_DIR", "DATA_DIR", "JOB_FILE", "JOB_LOG_FILE")
        }
        reports.UPLOAD_DIR = self.upload_dir
        reports.INPUT_DIR = self.input_dir
        reports.DATA_DIR = self.data_dir
        reports.JOB_FILE = self.data_dir / "_job.json"
        reports.JOB_LOG_FILE = self.data_dir / "_job.log"

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True

        # 不让 start 里的 0.3s sleep 拖慢测试；Popen 用 mock，避免真的起子进程。
        self._sleep = mock.patch.object(reports.time, "sleep", return_value=None)
        self._sleep.start()
        self.addCleanup(self._sleep.stop)

        self._popen = mock.patch("subprocess.Popen")
        popen = self._popen.start()
        self.addCleanup(self._popen.stop)
        proc = mock.MagicMock()
        proc.poll.return_value = None
        popen.return_value = proc

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            setattr(reports, name, value)
        self._tmp.cleanup()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _upload(self, upload_id: str, key: str, index: int, total,
                data: bytes):
        form = {
            "key": key,
            "upload_id": upload_id,
            "chunk_index": str(index),
            "chunk": (io.BytesIO(data), f"{key}.part"),
        }
        if total is not None:
            form["total_chunks"] = str(total)
        with self.app.test_request_context(
                "/api/upload/chunk", method="POST", data=form,
                content_type="multipart/form-data"):
            return self._unpack(reports.api_upload_chunk.__wrapped__())

    def _start(self, upload_id: str, manifest=None, **extra):
        form = {"upload_id": upload_id,
                "manifest": json.dumps(manifest or {}, ensure_ascii=False)}
        form.update(extra)
        with self.app.test_request_context(
                "/api/generate/start", method="POST", data=form):
            return self._unpack(reports.api_generate_start.__wrapped__())

    @staticmethod
    def _unpack(result):
        """Flask 视图直接 call 时，成功返回 Response，错误返回 (Response, status)。"""
        if isinstance(result, tuple):
            resp, status = result[0], result[1]
            return status, resp.get_json()
        return result.status_code, result.get_json()

    def _upload_chunks(self, upload_id: str, chunks, key: str = "A2",
                       total=None):
        total = len(chunks) if total is None else total
        for index, chunk in enumerate(chunks):
            status, body = self._upload(upload_id, key, index, total, chunk)
            self.assertEqual(status, 200, body)

    def _seed_input(self, name: str, data: bytes) -> Path:
        path = self.input_dir / name
        path.write_bytes(data)
        return path

    # ------------------------------------------------------------------
    # 正常 / 幂等 / 乱序
    # ------------------------------------------------------------------
    def test_upload_and_start_assembles_in_order(self):
        chunks = [b"A" * 1000, b"B" * 500, b"C" * 250]
        self._upload_chunks("u-normal", chunks)

        status, body = self._start("u-normal", {"A2": {"filename": "a2.pdf"}})

        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])
        self.assertEqual(body["keys"], ["A2"])
        self.assertEqual((self.input_dir / "report_A2.pdf").read_bytes(),
                         b"".join(chunks))
        self.assertFalse((self.upload_dir / "u-normal").exists())

    def test_duplicate_chunk_is_idempotent(self):
        """模拟“服务端已写入但响应在隧道上丢失，客户端重发同一片”。"""
        chunks = [b"zero" * 100, b"one" * 100, b"two" * 100]
        self._upload_chunks("u-dup", chunks)
        # 重发第 2 片（index=1），内容相同
        status, body = self._upload("u-dup", "A2", 1, 3, chunks[1])
        self.assertEqual(status, 200, body)

        status, body = self._start("u-dup", {"A2": {"filename": "a2.pdf"}})
        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_A2.pdf").read_bytes(),
                         b"".join(chunks))

    def test_out_of_order_chunks_are_sorted(self):
        chunks = [b"first", b"second", b"third"]
        for index in (2, 0, 1):
            status, body = self._upload("u-order", "A2", index, 3, chunks[index])
            self.assertEqual(status, 200, body)

        status, body = self._start("u-order", {"A2": {"filename": "a2.pdf"}})
        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_A2.pdf").read_bytes(),
                         b"".join(chunks))

    def test_legacy_client_without_total_chunks(self):
        chunks = [b"legacy-a", b"legacy-b"]
        for index, chunk in enumerate(chunks):
            status, body = self._upload("u-nototal", "A2", index, None, chunk)
            self.assertEqual(status, 200, body)

        status, body = self._start("u-nototal", {"A2": {"filename": "a2.pdf"}})
        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_A2.pdf").read_bytes(),
                         b"".join(chunks))

    # ------------------------------------------------------------------
    # 不完整 / 冲突 / 保护旧 input
    # ------------------------------------------------------------------
    def test_missing_chunk_rejected_and_input_preserved(self):
        old = self._seed_input("report_A2.pdf", b"previous-good-input")
        self._upload("u-missing", "A2", 0, 3, b"zero")
        self._upload("u-missing", "A2", 2, 3, b"two")

        status, body = self._start("u-missing", {"A2": {"filename": "a2.pdf"}})

        self.assertEqual(status, 400, body)
        self.assertIn("A2", body["error"])
        self.assertTrue(old.exists())
        self.assertEqual(old.read_bytes(), b"previous-good-input")
        self.assertTrue((self.upload_dir / "u-missing").exists())

    def test_total_mismatch_rejected(self):
        status, body = self._upload("u-total", "A2", 0, 3, b"zero")
        self.assertEqual(status, 200, body)
        status, body = self._upload("u-total", "A2", 1, 4, b"one")
        self.assertEqual(status, 400, body)
        self.assertIn("总数", body["error"])

    def test_mixed_legacy_and_indexed_rejected(self):
        old = self._seed_input("report_A2.pdf", b"previous-good-input")
        dest = self.upload_dir / "u-mixed"
        dest.mkdir(parents=True)
        (dest / "A2.part").write_bytes(b"legacy")
        (dest / "A2.000000.part").write_bytes(b"indexed")

        status, body = self._start("u-mixed", {"A2": {"filename": "a2.pdf"}})

        self.assertEqual(status, 400, body)
        self.assertIn("混用", body["error"])
        self.assertEqual(old.read_bytes(), b"previous-good-input")

    def test_empty_upload_dir_rejected(self):
        old = self._seed_input("report_A2.pdf", b"previous-good-input")
        (self.upload_dir / "u-empty").mkdir(parents=True)

        status, body = self._start("u-empty", {})

        self.assertEqual(status, 400, body)
        self.assertIn("至少上传一份", body["error"])
        self.assertEqual(old.read_bytes(), b"previous-good-input")

    # ------------------------------------------------------------------
    # 旧格式 / B6 版本 / 参数校验 / 任务运行中
    # ------------------------------------------------------------------
    def test_legacy_part_file_still_supported(self):
        dest = self.upload_dir / "u-legacy"
        dest.mkdir(parents=True)
        (dest / "A2.part").write_bytes(b"legacy-append-file")

        status, body = self._start("u-legacy", {"A2": {"filename": "a2.pdf"}})

        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_A2.pdf").read_bytes(),
                         b"legacy-append-file")

    def test_b6_high_school_suffix_preserved(self):
        status, body = self._upload("u-b6", "B6", 0, 1, b"b6-high")
        self.assertEqual(status, 200, body)

        status, body = self._start(
            "u-b6", {"B6": {"filename": "B6_高中_张三.pdf"}})

        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_B6_高中.pdf").read_bytes(),
                         b"b6-high")
        self.assertFalse((self.input_dir / "report_B6.pdf").exists())

    def test_b6_junior_high_school_suffix_preserved(self):
        status, body = self._upload("u-b6j", "B6", 0, 1, b"b6-junior")
        self.assertEqual(status, 200, body)

        status, body = self._start(
            "u-b6j", {"B6": {"filename": "B6_初中_李四.pdf"}})

        self.assertEqual(status, 200, body)
        self.assertEqual((self.input_dir / "report_B6_初中.pdf").read_bytes(),
                         b"b6-junior")

    def test_invalid_upload_params_rejected(self):
        cases = [
            ("Z9", "u", 0, 1, b"x", 400),
            ("A2", "../evil", 0, 1, b"x", 400),
            ("A2", "u", -1, 3, b"x", 400),
            ("A2", "u", 0, 0, b"x", 400),
            ("A2", "u", 3, 3, b"x", 400),
            ("A2", "u", 0, 1, b"", 400),
        ]
        for key, upload_id, index, total, data, expected in cases:
            status, _ = self._upload(upload_id, key, index, total, data)
            self.assertEqual(status, expected,
                             f"{key=} {upload_id=} {index=} {total=} {data=!r}")

    def test_running_job_returns_409_before_touching_input(self):
        old = self._seed_input("report_A2.pdf", b"previous-good-input")
        reports.JOB_FILE.write_text(
            json.dumps({"status": "running", "updated_at": time.time()}),
            encoding="utf-8")
        (self.upload_dir / "u-running").mkdir(parents=True)

        status, body = self._start("u-running", {})

        self.assertEqual(status, 409, body)
        self.assertTrue(old.exists())
        self.assertEqual(old.read_bytes(), b"previous-good-input")

    def test_chunk_storage_layout_and_total_metadata(self):
        status, body = self._upload("u-layout", "A2", 0, 2, b"zero")
        self.assertEqual(status, 200, body)
        dest = self.upload_dir / "u-layout"
        self.assertTrue((dest / "A2.000000.part").exists())
        self.assertEqual((dest / "A2.total").read_text(encoding="utf-8"), "2")


if __name__ == "__main__":
    unittest.main()
