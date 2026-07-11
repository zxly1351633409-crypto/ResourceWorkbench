from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from resource_workbench.move_log import STATUS_REVERTED, MoveLog, build_card_learning_features
from resource_workbench.target_recommender import (
    apply_history_target_suggestions,
    prepare_history_records,
    recommend_target_folders,
)


class MoveLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        self.learned = self.root / "M 模型" / "K 科幻" / "J 机甲"
        self.other = self.root / "M 模型" / "K 科幻" / "W 物件"
        self.learned.mkdir(parents=True)
        self.other.mkdir(parents=True)
        self.log = MoveLog(Path(self.temp.name) / "move.sqlite")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_successful_moves_boost_matching_target(self) -> None:
        previous = {
            "name": "Sci Fi Robot Leg",
            "suggested_type": "model",
            "content_tags": ["机器人", "机甲", "科幻"],
            "extension_counts": {".fbx": 2, ".png": 5},
        }
        self.log.record_move(
            source=str(Path(self.temp.name) / "old"),
            destination=str(self.learned / "Sci Fi Robot Leg"),
            file_count=7,
            byte_count=100,
            dest_file_count=7,
            dest_byte_count=100,
            verified=True,
            card=previous,
            target_directory=str(self.learned),
            move_kind="formal",
        )
        current = {
            "name": "Mechanical Robot Arm",
            "suggested_type": "model",
            "content_tags": ["机器人", "机甲", "科幻"],
            "extension_counts": {".fbx": 1, ".png": 3},
            "target_path_hints": [str(self.root / "M 模型" / "K 科幻")],
        }
        result = recommend_target_folders(current, self.root, move_log=self.log)
        self.assertTrue(result["ok"])
        self.assertEqual(Path(result["candidates"][0]["path"]), self.learned)
        self.assertTrue(result["candidates"][0]["is_history_match"])
        self.assertGreaterEqual(result["history_examples_used"], 1)

    def test_record_limit_and_manual_vacuum_keep_log_bounded(self) -> None:
        log = MoveLog(Path(self.temp.name) / "bounded.sqlite", max_records=3, max_age_days=None)
        for index in range(6):
            move_id = log.record_move(
                source=str(Path(self.temp.name) / f"source-{index}"),
                destination=str(self.learned / f"asset-{index}"),
                file_count=1,
                byte_count=index,
                dest_file_count=1,
                dest_byte_count=index,
                verified=True,
                card={"name": f"Robot {index}", "suggested_type": "model"},
                target_directory=str(self.learned),
            )
            # Only completed/reverted history is eligible for automatic
            # retention.  A still-moved row must keep its undo information.
            log.set_status(move_id, STATUS_REVERTED)
        self.assertEqual(len(log.list_records()), 3)
        result = log.prune(max_records=2, max_age_days=None, vacuum=True)
        self.assertTrue(result["vacuumed"])
        self.assertEqual(result["after"], 2)

    def test_active_move_undo_records_are_never_pruned_by_default(self) -> None:
        log = MoveLog(Path(self.temp.name) / "active.sqlite", max_records=1, max_age_days=0)
        for index in range(3):
            log.record_move(
                source=str(Path(self.temp.name) / f"active-source-{index}"),
                destination=str(self.learned / f"active-asset-{index}"),
                file_count=1,
                byte_count=index,
                dest_file_count=1,
                dest_byte_count=index,
                verified=True,
            )
        result = log.prune(max_records=1, max_age_days=0)
        self.assertEqual(result["protected"], 3)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(log.list_records()), 3)

    def test_unknown_status_and_invalid_terminal_timestamp_are_preserved(self) -> None:
        log = MoveLog(Path(self.temp.name) / "future.sqlite", max_records=None, max_age_days=None)
        reverted = log.record_move(
            source=str(Path(self.temp.name) / "terminal"),
            destination=str(self.learned / "terminal"),
            file_count=1,
            byte_count=1,
            dest_file_count=1,
            dest_byte_count=1,
            verified=True,
        )
        future = log.record_move(
            source=str(Path(self.temp.name) / "future"),
            destination=str(self.learned / "future"),
            file_count=1,
            byte_count=1,
            dest_file_count=1,
            dest_byte_count=1,
            verified=True,
        )
        malformed = log.record_move(
            source=str(Path(self.temp.name) / "malformed"),
            destination=str(self.learned / "malformed"),
            file_count=1,
            byte_count=1,
            dest_file_count=1,
            dest_byte_count=1,
            verified=True,
        )
        log.set_status(reverted, STATUS_REVERTED)
        log.set_status(future, "future_active_state")
        log.set_status(malformed, STATUS_REVERTED)
        with log._connect() as conn:
            conn.execute(
                "UPDATE move_records SET moved_at = '' WHERE move_id = ?",
                (malformed,),
            )

        result = log.prune(max_records=0, max_age_days=0, preserve_statuses=())
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["protected"], 2)
        self.assertIsNone(log.get(reverted))
        self.assertIsNotNone(log.get(future))
        self.assertIsNotNone(log.get(malformed))

    def test_analysis_card_receives_learned_target_without_unc_duplicate(self) -> None:
        previous = {
            "name": "Urban Grocery Props",
            "suggested_type": "model",
            "content_tags": ["道具/残骸", "城市/场景"],
            "top_extensions": {".blend": 1, ".zip": 1},
        }
        unc_target = rf"\\server\share\{self.root.name}\M 模型\K 科幻\W 物件"
        records = [
            {
                "target_directory": unc_target,
                "card_features": build_card_learning_features(previous),
            }
        ]
        prepared = prepare_history_records(records, self.root)
        self.assertEqual(len(prepared), 1)
        self.assertEqual(Path(prepared[0]["target_directory"]), self.other)

        current = {
            "name": "Urban Grocery Props Vol.2",
            "suggested_type": "model",
            "content_tags": ["道具/残骸", "城市/场景"],
            "top_extensions": {".blend": 1, ".zip": 1},
            "target_suggestions": [
                {"path": str(self.root / "M 模型"), "score": 45, "reason": "broad fallback"}
            ],
            "target_path_hints": [str(self.root / "M 模型")],
        }
        added = apply_history_target_suggestions(current, self.root, prepared)
        self.assertEqual(added, 1)
        self.assertEqual(Path(current["target_path_hints"][0]), self.other)
        self.assertEqual(len({Path(path) for path in current["target_path_hints"]}), len(current["target_path_hints"]))

    def test_learning_features_use_production_extension_fields(self) -> None:
        features = build_card_learning_features(
            {
                "name": "Cars Vol.3",
                "display_name": "汽车 第3卷",
                "top_extensions": {".blend": 1, ".jpg": 1},
                "top_archive_extensions": {".fbx": 3},
                "samples": {"model": ["Assets/CARS-set-03.blend"]},
            }
        )
        self.assertEqual(set(features["extensions"]), {"blend", "fbx", "jpg"})
        self.assertIn("cars", features["keywords"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
