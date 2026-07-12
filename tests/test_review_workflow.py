"""审阅工作流单元测试：结构化 DeepSeek 解析、审阅队列、可回滚移动。

运行：
    python -m unittest discover -s tests -v
或：
    python tests/test_review_workflow.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench import deepseek, mover, review_queue
from resource_workbench.move_log import MoveLog, count_tree


def _canonical_path(path: str | Path) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def _sample_card(source_path: str, name: str = "Sci Fi Robot Leg") -> dict:
    return {
        "name": name,
        "display_name": name,
        "source_path": source_path,
        "suggested_type": "model",
        "confidence": "low",
        "needs_human_review": True,
        "target_path_hints": [r"Z:\整合——资源管理\M 模型\K 科幻\W 物件"],
        "content_tags": ["科幻", "机甲"],
        "reasons": ["目录里有大量 fbx", "封面像机械腿"],
        "archive_entry_samples": ["leg.fbx", "preview.png"],
        "archive_count": 1,
    }


class DeepSeekParsingTests(unittest.TestCase):
    def test_selected_model_defaults_to_flash(self):
        settings = {
            "deepseek_flash_model": "flash-model",
            "deepseek_pro_model": "pro-model",
            "deepseek_default_tier": "flash",
        }
        self.assertEqual(deepseek.selected_model(settings), "flash-model")
        self.assertEqual(deepseek.selected_model(settings, "pro"), "pro-model")

    def test_plain_json(self):
        content = (
            '{"translated_name": "科幻机器人腿 Sci Fi Robot Leg", '
            '"target_path": "Z:/M 模型/K 科幻/W 物件", '
            '"new_folder_needed": false, "confidence": "high", '
            '"review_reason": "", "tags": ["科幻", "机甲"]}'
        )
        result = deepseek.parse_structured_suggestion(content)
        self.assertTrue(result["ok"])
        s = result["suggestion"]
        self.assertEqual(s["confidence"], "high")
        self.assertFalse(s["new_folder_needed"])
        self.assertIn("科幻", s["tags"])

    def test_fenced_json(self):
        content = "好的，建议如下：\n```json\n{\"translated_name\": \"测试\", \"confidence\": \"medium\"}\n```\n谢谢"
        result = deepseek.parse_structured_suggestion(content)
        self.assertTrue(result["ok"])
        self.assertEqual(result["suggestion"]["translated_name"], "测试")
        self.assertEqual(result["suggestion"]["confidence"], "medium")

    def test_numeric_confidence_and_chinese_keys(self):
        content = '{"中文名": "机甲腿", "目标分类": "M 模型", "置信度": 0.9, "新建目录": "是"}'
        result = deepseek.parse_structured_suggestion(content)
        self.assertTrue(result["ok"])
        s = result["suggestion"]
        self.assertEqual(s["translated_name"], "机甲腿")
        self.assertEqual(s["target_path"], "M 模型")
        self.assertEqual(s["confidence"], "high")
        self.assertTrue(s["new_folder_needed"])

    def test_no_json(self):
        result = deepseek.parse_structured_suggestion("抱歉我无法处理。")
        self.assertFalse(result["ok"])

    def test_structured_prompt_contains_disk_samples_batch_and_extensions(self):
        card = _sample_card(r"F:\测试\a", name="Cars Vol.3")
        card["samples"] = {"model": [r"Cars\Assets\CARS-set-03.blend1"]}
        card["top_extensions"] = {".blend": 1, ".jpg": 1}
        card["batch_source_path"] = r"Z:\待整理\废墟二期"
        prompt = deepseek._structured_card_prompt(card, {"translation_name_mode": "zh_en"})
        self.assertIn("CARS-set-03.blend1", prompt)
        self.assertIn("来源批次：废墟二期", prompt)
        self.assertIn(".blend", prompt)


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.queue = review_queue.ReviewQueue(Path(self.tmp.name) / "rq.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_enqueue_and_dedupe(self):
        card = _sample_card(r"F:\测试\a")
        cid1 = self.queue.enqueue_card(card)
        cid2 = self.queue.enqueue_card(card)
        self.assertEqual(cid1, cid2)
        self.assertEqual(len(self.queue.list_items()), 1)
        item = self.queue.get(cid1)
        self.assertEqual(item["status"], review_queue.STATUS_PENDING)

    def test_status_transitions_and_counts(self):
        a = self.queue.enqueue_card(_sample_card(r"F:\测试\a", "A"))
        b = self.queue.enqueue_card(_sample_card(r"F:\测试\b", "B"))
        self.queue.set_status(a, review_queue.STATUS_APPROVED)
        self.queue.set_status(b, review_queue.STATUS_REJECTED, note="重复资源")
        counts = self.queue.counts_by_status()
        self.assertEqual(counts[review_queue.STATUS_APPROVED], 1)
        self.assertEqual(counts[review_queue.STATUS_REJECTED], 1)
        self.assertEqual(counts[review_queue.STATUS_PENDING], 0)
        self.assertEqual(self.queue.get(b)["note"], "重复资源")

    def test_invalid_status(self):
        a = self.queue.enqueue_card(_sample_card(r"F:\测试\a"))
        with self.assertRaises(ValueError):
            self.queue.set_status(a, "banana")

    def test_apply_suggestion_preserves_manual_target(self):
        card = _sample_card(r"F:\测试\a")
        cid = self.queue.enqueue_card(card)
        self.queue.update_fields(cid, target_path=r"Z:\手动选的分类")
        # 重新入队（机器再次分析）不应覆盖人工目标。
        self.queue.enqueue_card(card)
        self.assertEqual(self.queue.get(cid)["target_path"], r"Z:\手动选的分类")
        # 应用结构化建议会更新译名与原因。
        self.queue.apply_suggestion(
            cid,
            {"translated_name": "科幻机器人腿", "confidence": "high", "review_reason": "ok"},
        )
        item = self.queue.get(cid)
        self.assertEqual(item["translated_name"], "科幻机器人腿")
        self.assertEqual(item["confidence"], "high")

    def test_reject_unknown_field(self):
        cid = self.queue.enqueue_card(_sample_card(r"F:\测试\a"))
        with self.assertRaises(ValueError):
            self.queue.update_fields(cid, status="approved")  # status 不在可编辑字段


class MoveAndUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source_root = root / "测试"
        self.test_move_root = root / "测试移动的位置"
        self.z_root = root / "Z"
        self.source_root.mkdir()
        self.test_move_root.mkdir()
        self.z_root.mkdir()
        self.move_log = MoveLog(root / "move_log.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def _make_resource(self, name: str) -> Path:
        res = self.source_root / name
        res.mkdir()
        (res / "a.fbx").write_text("hello", encoding="utf-8")
        (res / "preview.png").write_bytes(b"\x89PNG\r\n\x1a\n12345")
        return res

    def test_move_records_and_verifies(self):
        res = self._make_resource("RobotLeg")
        pre_files, pre_bytes = count_tree(res)
        card = {
            "source_path": str(res),
            "suggested_type": "model",
            "user_target_path": str(self.z_root / "M 模型" / "K 科幻"),
        }
        result = mover.execute_test_move(
            card, self.source_root, self.test_move_root, self.z_root, move_log=self.move_log
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["verified"])
        self.assertEqual(result["file_count"], pre_files)
        self.assertEqual(result["byte_count"], pre_bytes)
        self.assertFalse(res.exists())
        self.assertTrue(Path(result["destination"]).exists())
        rec = self.move_log.get(result["move_id"])
        self.assertEqual(rec["status"], "moved")
        self.assertTrue(rec["verified"])

    def test_rejects_outside_source_root(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "x.txt").write_text("x", encoding="utf-8")
        card = {"source_path": str(outside), "suggested_type": "model"}
        result = mover.execute_test_move(
            card, self.source_root, self.test_move_root, self.z_root, move_log=self.move_log
        )
        self.assertFalse(result["ok"])
        self.assertIn("安全限制", result["error"])
        self.assertTrue(outside.exists())  # 未被移动

    def test_undo_restores_source(self):
        res = self._make_resource("ToUndo")
        card = {"source_path": str(res), "suggested_type": "model"}
        result = mover.execute_test_move(
            card, self.source_root, self.test_move_root, self.z_root, move_log=self.move_log
        )
        self.assertTrue(result["ok"])
        undo = mover.undo_move(result["move_id"], self.move_log)
        self.assertTrue(undo["ok"], undo.get("error"))
        self.assertTrue(undo["verified"])
        self.assertTrue(res.exists())
        self.assertEqual(self.move_log.get(result["move_id"])["status"], "reverted")

    def test_double_undo_blocked(self):
        res = self._make_resource("Once")
        card = {"source_path": str(res), "suggested_type": "model"}
        result = mover.execute_test_move(
            card, self.source_root, self.test_move_root, self.z_root, move_log=self.move_log
        )
        mover.undo_move(result["move_id"], self.move_log)
        second = mover.undo_move(result["move_id"], self.move_log)
        self.assertFalse(second["ok"])

    def test_formal_move_can_dry_run_without_touching_source(self):
        res = self._make_resource("DryRun")
        target = self.z_root / "M Models"
        card = {"source_path": str(res), "user_target_path": str(target)}
        result = mover.execute_formal_move(
            card, [self.source_root], self.z_root, move_log=self.move_log, dry_run=True
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertTrue(result["dry_run"])
        self.assertTrue(res.exists())
        self.assertFalse(Path(result["destination"]).exists())
        self.assertEqual(_canonical_path(Path(result["destination"]).parent), _canonical_path(target))

    def test_formal_move_records_and_can_be_undone(self):
        res = self._make_resource("Formal")
        target = self.z_root / "M Models"
        card = {"source_path": str(res), "user_target_path": str(target)}
        result = mover.execute_formal_move(
            card, [self.source_root], self.z_root, move_log=self.move_log
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertFalse(res.exists())
        self.assertTrue(Path(result["destination"]).exists())
        destination = _canonical_path(Path(result["destination"]))
        z_root = _canonical_path(self.z_root)
        self.assertEqual(os.path.commonpath([destination, z_root]), z_root)
        rec = self.move_log.get(result["move_id"])
        self.assertIn("[formal]", rec["note"])
        undo = mover.undo_move(result["move_id"], self.move_log)
        self.assertTrue(undo["ok"], undo.get("error"))
        self.assertTrue(res.exists())

    def test_formal_move_rejects_target_outside_z_root(self):
        res = self._make_resource("BadTarget")
        outside_target = Path(self.tmp.name) / "other" / "target"
        card = {"source_path": str(res), "user_target_path": str(outside_target)}
        result = mover.execute_formal_move(
            card, [self.source_root], self.z_root, move_log=self.move_log
        )
        self.assertFalse(result["ok"])
        self.assertIn("正式移动目标", result["error"])
        self.assertTrue(res.exists())

    def test_formal_move_accepts_shortened_z_library_target(self):
        res = self._make_resource("ShortTarget")
        card = {"source_path": str(res), "user_target_path": r"Z:\M 模型\K 科幻"}
        result = mover.execute_formal_move(
            card, [self.source_root], self.z_root, move_log=self.move_log, dry_run=True
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(
            _canonical_path(result["target_dir"]),
            _canonical_path(self.z_root / "M 模型" / "K 科幻"),
        )

    def test_formal_move_rejects_same_target_directory(self):
        target = self.z_root / "M Models"
        res = target / "AlreadyThere"
        res.mkdir(parents=True)
        (res / "a.fbx").write_text("hello", encoding="utf-8")
        card = {"source_path": str(res), "user_target_path": str(target)}
        result = mover.execute_formal_move(
            card, [self.z_root], self.z_root, move_log=self.move_log
        )
        self.assertFalse(result["ok"])
        self.assertIn("无需正式移动", result["error"])
        self.assertTrue(res.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
