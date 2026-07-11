from __future__ import annotations
import json, os, sqlite3, sys, tempfile, time, unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path: sys.path.insert(0, str(SRC))
from resource_workbench import maintenance as mt
from resource_workbench import staging as st


class DedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.r = Path(self.tmp.name)
        (self.r/"a").mkdir(); (self.r/"b").mkdir()
        (self.r/"a"/"dup.png").write_bytes(b"x"*100)
        (self.r/"b"/"dup.png").write_bytes(b"x"*100)      # 同名同大小同内容 -> 重复
        (self.r/"b"/"other.png").write_bytes(b"y"*50)
        (self.r/"a"/"diff.png").write_bytes(b"z"*100)
        (self.r/"b"/"diff.png").write_bytes(b"w"*100)      # 同名同大小，内容不同
    def tearDown(self): self.tmp.cleanup()
    def test_namesize(self):
        groups = mt.find_duplicates(self.r)
        keys = {g["key"] for g in groups}
        self.assertIn("dup.png", keys); self.assertIn("diff.png", keys)
    def test_hash_confirms(self):
        groups = mt.find_duplicates(self.r, use_hash=True)
        keys = {g["key"] for g in groups}
        self.assertIn("dup.png", keys)        # 内容相同 -> 确认重复
        self.assertNotIn("diff.png", keys)    # 内容不同 -> 不算重复
        self.assertTrue(all(g["confirmed"] for g in groups))


class EmptyDirTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.r = Path(self.tmp.name)
        (self.r/"keep").mkdir(); (self.r/"keep"/"f.txt").write_text("x", encoding="utf-8")
        (self.r/"empty"/"deep").mkdir(parents=True)   # 全空链
    def tearDown(self): self.tmp.cleanup()
    def test_find_and_remove(self):
        empties = mt.find_empty_dirs(self.r)
        self.assertTrue(any(e.endswith("deep") for e in empties))
        res = mt.remove_empty_dirs(self.r)
        self.assertTrue(res["ok"])
        self.assertFalse((self.r/"empty").exists())
        self.assertTrue((self.r/"keep").exists())


class RuntimeRetentionTests(unittest.TestCase):
    def test_staging_manifest_records_completion_and_activity_marker_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch"
            marker = st._mark_staging_active(batch)
            self.assertTrue(marker.is_file())
            self.assertFalse(st._has_extracted_content(batch))
            (batch / "payload.bin").write_bytes(b"derived")
            self.assertTrue(st._has_extracted_content(batch))
            manifest = st._write_manifest(
                batch,
                {
                    "kind": "single_archive",
                    "source": "D:/source.zip",
                    "source_archives_kept": True,
                    "delete_source_allowed": False,
                    "status": "ok",
                },
            )
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["manifest_schema"], 2)
            self.assertTrue(payload["complete"])
            self.assertTrue(payload["created_at"])
            self.assertTrue(payload["completed_at"])
            st._clear_staging_active(batch)
            self.assertFalse(marker.exists())

    def test_cache_is_pruned_by_age_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "previews"
            root.mkdir()
            old = root / "old.png"
            middle = root / "middle.png"
            newest = root / "new.png"
            old.write_bytes(b"a" * 20)
            middle.write_bytes(b"b" * 20)
            newest.write_bytes(b"c" * 20)
            now = time.time()
            os.utime(old, (now - 10 * 86400, now - 10 * 86400))
            os.utime(middle, (now - 100, now - 100))
            os.utime(newest, (now, now))
            result = mt.prune_cache_directory(root, max_bytes=20, max_age_days=5)
            self.assertEqual(result["deleted_files"], 2)
            self.assertFalse(old.exists())
            self.assertFalse(middle.exists())
            self.assertTrue(newest.exists())

    def test_cache_dry_run_does_not_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / "preview.png"
            item.write_bytes(b"x" * 50)
            result = mt.prune_cache_directory(root, max_bytes=0, max_age_days=None, dry_run=True)
            self.assertEqual(result["candidate_files"], 1)
            self.assertEqual(result["deleted_files"], 0)
            self.assertTrue(item.exists())

    def test_staging_prunes_only_complete_inactive_expired_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "staging"
            root.mkdir()
            old_time = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
            retained_source = Path(tmp) / "source.zip"
            retained_source.write_bytes(b"source archive")

            expired = root / "expired"
            expired.mkdir()
            (expired / "payload.bin").write_bytes(b"derived")
            (expired / mt.STAGING_MANIFEST).write_text(
                json.dumps(
                    {
                        "kind": "single_archive",
                        "manifest_schema": 2,
                        "source": str(retained_source),
                        "source_archives_kept": True,
                        "delete_source_allowed": False,
                        "status": "ok",
                        "complete": True,
                        "completed_at": old_time,
                    }
                ),
                encoding="utf-8",
            )

            active = root / "active"
            active.mkdir()
            (active / mt.STAGING_MANIFEST).write_text(
                json.dumps(
                    {
                        "kind": "single_archive",
                        "manifest_schema": 2,
                        "source": str(retained_source),
                        "source_archives_kept": True,
                        "delete_source_allowed": False,
                        "status": "ok",
                        "complete": True,
                        "completed_at": old_time,
                    }
                ),
                encoding="utf-8",
            )
            (active / mt.STAGING_ACTIVITY_MARKER).write_text("active", encoding="utf-8")

            unknown = root / "unknown"
            unknown.mkdir()
            (unknown / "payload.bin").write_bytes(b"must stay")

            plan = mt.prune_staging_batches(
                root, max_age_days=60, min_inactive_hours=24, dry_run=True
            )
            self.assertEqual(plan["candidates"], 1)
            self.assertTrue(expired.exists())
            result = mt.prune_staging_batches(root, max_age_days=60, min_inactive_hours=24)
            self.assertEqual(result["deleted"], 1)
            self.assertFalse(expired.exists())
            self.assertTrue(active.exists())
            self.assertTrue(unknown.exists())
            self.assertEqual(result["preserved_reasons"]["active_marker"], 1)
            self.assertEqual(result["preserved_reasons"]["missing_manifest"], 1)

    def test_staging_preserves_incomplete_manifest_and_missing_source_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "staging"
            root.mkdir()
            old_time = (datetime.now() - timedelta(days=90)).isoformat(timespec="seconds")
            common = {
                "manifest_schema": 2,
                "kind": "single_archive",
                "source_archives_kept": True,
                "delete_source_allowed": False,
                "status": "ok",
                "completed_at": old_time,
            }
            incomplete = root / "incomplete"
            incomplete.mkdir()
            (incomplete / mt.STAGING_MANIFEST).write_text(
                json.dumps({**common, "source": str(Path(tmp) / "source.zip")}),
                encoding="utf-8",
            )
            missing_source = root / "missing-source"
            missing_source.mkdir()
            (missing_source / mt.STAGING_MANIFEST).write_text(
                json.dumps(
                    {
                        **common,
                        "complete": True,
                        "source": str(Path(tmp) / "does-not-exist.zip"),
                    }
                ),
                encoding="utf-8",
            )

            result = mt.prune_staging_batches(root, max_age_days=60, min_inactive_hours=24)
            self.assertEqual(result["deleted"], 0)
            self.assertTrue(incomplete.exists())
            self.assertTrue(missing_source.exists())
            self.assertEqual(result["preserved_reasons"]["incomplete_manifest"], 1)
            self.assertEqual(result["preserved_reasons"]["source_archive_missing"], 1)

    def test_sqlite_history_never_deletes_non_terminal_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "review.sqlite"
            old = (datetime.now() - timedelta(days=800)).isoformat(timespec="seconds")
            recent = datetime.now().isoformat(timespec="seconds")
            with closing(sqlite3.connect(db_path)) as conn:
                conn.execute(
                    "CREATE TABLE review_items (card_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)"
                )
                conn.executemany(
                    "INSERT INTO review_items VALUES (?, ?, ?)",
                    [
                        ("done-old", "done", old),
                        ("done-new", "done", recent),
                        ("done-unknown-time", "done", ""),
                        ("pending-old", "pending", old),
                        ("failed-old", "move_failed", old),
                    ],
                )
                conn.commit()
            result = mt.prune_sqlite_history(
                db_path,
                table="review_items",
                timestamp_column="updated_at",
                status_column="status",
                terminal_statuses=("done",),
                max_records=1,
                max_age_days=730,
            )
            self.assertEqual(result["deleted"], 1)
            self.assertEqual(result["protected"], 3)
            with closing(sqlite3.connect(db_path)) as conn:
                remaining = {
                    row[0] for row in conn.execute("SELECT card_id FROM review_items").fetchall()
                }
            self.assertNotIn("done-old", remaining)
            self.assertIn("done-new", remaining)
            self.assertIn("done-unknown-time", remaining)
            self.assertIn("pending-old", remaining)
            self.assertIn("failed-old", remaining)

    def test_runtime_maintenance_covers_all_stores_without_deleting_manual_or_active_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_root = Path(tmp)
            runtime = data_root / "workbench_data"
            runtime.mkdir()
            old_iso = (datetime.now() - timedelta(days=800)).isoformat(timespec="seconds")
            old_epoch = time.time() - 800 * 86_400

            databases = {
                "resource_index.sqlite": (
                    "CREATE TABLE resources (path TEXT PRIMARY KEY, indexed_at REAL)",
                    "INSERT INTO resources VALUES (?, ?)",
                    [("D:/derived", old_epoch)],
                ),
                "review_queue.sqlite": (
                    "CREATE TABLE review_items (card_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)",
                    "INSERT INTO review_items VALUES (?, ?, ?)",
                    [("done", "done", old_iso), ("pending", "pending", old_iso)],
                ),
                "card_metadata.sqlite": (
                    "CREATE TABLE card_metadata (card_id TEXT PRIMARY KEY, tags_json TEXT, note TEXT, updated_at TEXT)",
                    "INSERT INTO card_metadata VALUES (?, ?, ?, ?)",
                    [("manual", '[\"keep\"]', "user note", old_iso)],
                ),
                "rename_log.sqlite": (
                    "CREATE TABLE rename_records (rename_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)",
                    "INSERT INTO rename_records VALUES (?, ?, ?)",
                    [("reverted", "reverted", old_iso), ("active", "renamed", old_iso)],
                ),
                "upload_log.sqlite": (
                    "CREATE TABLE upload_records (upload_id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)",
                    "INSERT INTO upload_records VALUES (?, ?, ?)",
                    [("uploaded", "uploaded", old_iso), ("pending", "pending", old_iso)],
                ),
            }
            for filename, (schema, insert_sql, rows) in databases.items():
                with closing(sqlite3.connect(runtime / filename)) as conn:
                    conn.execute(schema)
                    conn.executemany(insert_sql, rows)
                    conn.commit()

            settings = {
                "preview_cache_max_mb": 128,
                "preview_cache_max_age_days": 180,
                "move_log_max_records": 10000,
                "move_log_max_age_days": 730,
                "staging_max_age_days": 60,
                "staging_min_inactive_hours": 24,
                "resource_index_max_records": 250000,
                "resource_index_max_age_days": 365,
                "review_history_max_records": 20000,
                "review_history_max_age_days": 730,
                "rename_log_max_records": 20000,
                "rename_log_max_age_days": 730,
                "upload_log_max_records": 20000,
                "upload_log_max_age_days": 730,
                "sqlite_vacuum_min_reclaim_mb": 1024,
            }
            result = mt.maintain_workbench_runtime(data_root, settings)
            self.assertEqual(result["resource_index"]["deleted"], 1)
            self.assertEqual(result["review_queue"]["deleted"], 1)
            self.assertEqual(result["rename_log"]["deleted"], 1)
            self.assertEqual(result["upload_log"]["deleted"], 1)
            self.assertTrue(result["card_metadata"]["manual_data_preserved"])

            checks = {
                "review_queue.sqlite": ("review_items", "card_id", {"pending"}),
                "card_metadata.sqlite": ("card_metadata", "card_id", {"manual"}),
                "rename_log.sqlite": ("rename_records", "rename_id", {"active"}),
                "upload_log.sqlite": ("upload_records", "upload_id", {"pending"}),
            }
            for filename, (table, column, expected) in checks.items():
                with closing(sqlite3.connect(runtime / filename)) as conn:
                    actual = {
                        row[0] for row in conn.execute(f"SELECT {column} FROM {table}").fetchall()
                    }
                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
