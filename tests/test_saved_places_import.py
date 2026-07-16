import importlib.util
import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from placeintel import saved_places


FIXTURES = Path(__file__).parent / "fixtures" / "saved_takeout"


class SavedPlacesImportTest(unittest.TestCase):
    def test_saved_places_domain_module_exists(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("placeintel.saved_places"))

    def test_saved_places_import_interfaces_exist(self) -> None:
        for name in (
            "SavedRow",
            "ImportLimits",
            "ImportResult",
            "ensure_schema",
            "iter_takeout_rows",
            "import_takeout",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(saved_places, name), name)

    def test_saved_csv_parses_description_unicode_and_tags(self) -> None:
        rows = list(saved_places.iter_takeout_rows(FIXTURES / "Saved" / "Date Places.csv"))

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].source_product, "saved")
        self.assertEqual(rows[0].collection_name, "Date Places")
        self.assertEqual(rows[0].collection_description, "A calm shortlist for dates in Đà Nẵng")
        self.assertEqual(rows[0].title, "Lantern Café")
        self.assertEqual(rows[0].tags, ("coffee", "date night"))
        self.assertEqual(rows[0].row_number, 4)
        self.assertEqual(len(rows[0].source_file_sha256), 64)

    def test_saved_csv_accepts_bom_case_insensitive_headers_and_missing_optional_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Cafés.csv"
            source.write_bytes(
                "\ufeffTITLE,Item_Content_URL\nMột quán,https://example.com/cafe\n".encode("utf-8")
            )

            row = next(saved_places.iter_takeout_rows(source))

            self.assertEqual(row.title, "Một quán")
            self.assertEqual(row.url, "https://example.com/cafe")
            self.assertIsNone(row.note)
            self.assertEqual(row.tags, ())

    def test_saved_row_contract_keeps_exported_location_fields(self) -> None:
        field_names = set(saved_places.SavedRow.__dataclass_fields__)

        self.assertTrue({"address", "lat", "lng", "saved_at"} <= field_names)

    def test_takeout_directory_parses_saved_csv_and_starred_geojson(self) -> None:
        rows = list(saved_places.iter_takeout_rows(FIXTURES))

        self.assertEqual(len(rows), 4)
        starred = next(row for row in rows if row.source_product == "local_actions")
        self.assertEqual(starred.collection_name, "Starred places")
        self.assertEqual(starred.title, "River Café")
        self.assertEqual(starred.address, "Đà Nẵng")
        self.assertEqual((starred.lat, starred.lng), (16.0678, 108.224))
        self.assertEqual(starred.saved_at, "2026-06-30T12:00:00Z")
        self.assertEqual(
            starred.source_member,
            "Maps (your places)/Starred places.json",
        )

    def test_starred_geojson_accepts_official_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Maps (your places)" / "Starred places.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [108.2, 16.1]},
                                "date": "2026-07-01T00:00:00Z",
                                "google_maps_url": "https://www.google.com/maps/place/Top+Level",
                                "location": [
                                    {"name": "Top Level Café", "address": "Da Nang"}
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            row = next(saved_places.iter_takeout_rows(root))

            self.assertEqual(row.title, "Top Level Café")
            self.assertEqual(row.address, "Da Nang")
            self.assertEqual(row.saved_at, "2026-07-01T00:00:00Z")
            self.assertIn("Top+Level", row.url)

    def test_saved_places_geojson_is_imported_from_current_takeout_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Maps (your places)" / "Saved Places.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [108.22, 16.06],
                                },
                                "properties": {
                                    "date": "2026-07-16T00:00:00Z",
                                    "google_maps_url": "https://www.google.com/maps/place/Current+Export",
                                    "location": {
                                        "name": "Current Export Café",
                                        "address": "Da Nang",
                                    },
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rows = list(saved_places.iter_takeout_rows(root))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].collection_name, "Saved Places")
            self.assertEqual(rows[0].title, "Current Export Café")
            self.assertEqual((rows[0].lat, rows[0].lng), (16.06, 108.22))

    def test_localized_saved_geojson_is_detected_by_strict_schema_not_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "localized" / "unknown-name.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [108.22, 16.06],
                                },
                                "properties": {
                                    "date": "2026-07-16T00:00:00Z",
                                    "google_maps_url": "https://www.google.com/maps/place/Scoped",
                                    "Comment": "private saved-place comment",
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rows = list(saved_places.iter_takeout_rows(root))

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].collection_name, "Saved Places")
            self.assertEqual(rows[0].comment, "private saved-place comment")
            self.assertEqual((rows[0].lat, rows[0].lng), (16.06, 108.22))

    def test_localized_review_geojson_is_not_mistaken_for_saved_places(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "localized" / "review-export.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [108.22, 16.06],
                                },
                                "properties": {
                                    "google_maps_url": "https://www.google.com/maps/place/Review",
                                    "review_text_published": "private review",
                                    "five_star_rating_published": 5,
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(list(saved_places.iter_takeout_rows(root)), [])

    def test_zero_zero_geojson_coordinates_use_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Maps (your places)" / "Starred places.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [0, 0]},
                                "location": [{"name": "First unknown place"}],
                            },
                            {
                                "type": "Feature",
                                "geometry": {"type": "Point", "coordinates": [0, 0]},
                                "location": [{"name": "Second unknown place"}],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            result = saved_places.import_takeout(conn, source.parent.parent)

            self.assertEqual(result.created_items, 2)
            rows = conn.execute(
                "SELECT source_title, source_lat, source_lng FROM saved_items ORDER BY source_title"
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    ("First unknown place", None, None),
                    ("Second unknown place", None, None),
                ],
            )
            conn.close()

    def test_ensure_schema_creates_saved_corpus_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            saved_places.ensure_schema(conn)

            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertTrue(
                {
                    "saved_import_runs",
                    "saved_collections",
                    "saved_items",
                    "saved_memberships",
                }
                <= tables
            )
            conn.close()

    def test_import_is_idempotent_and_keeps_many_list_memberships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            first = saved_places.import_takeout(conn, FIXTURES)
            second = saved_places.import_takeout(conn, FIXTURES)

            self.assertEqual(first.file_count, 3)
            self.assertEqual(first.row_count, 4)
            self.assertEqual(
                (
                    first.created_collections,
                    first.created_items,
                    first.created_memberships,
                ),
                (3, 3, 4),
            )
            self.assertEqual(
                (
                    second.created_collections,
                    second.created_items,
                    second.created_memberships,
                ),
                (0, 0, 0),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_import_runs").fetchone()[0],
                2,
            )
            lantern_memberships = conn.execute(
                """
                SELECT COUNT(*)
                FROM saved_memberships m
                JOIN saved_items i ON i.saved_item_id = m.saved_item_id
                WHERE i.source_title = ?
                """,
                ("Lantern Café",),
            ).fetchone()[0]
            self.assertEqual(lantern_memberships, 2)
            conn.close()

    def test_opt_in_import_events_are_safe_and_cover_start_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            with self.assertLogs("placeintel.saved_places", level="INFO") as captured:
                saved_places.import_takeout(conn, FIXTURES, emit_events=True)

            output = "\n".join(captured.output)
            self.assertIn("saved_import_started", output)
            self.assertIn("saved_import_completed", output)
            self.assertNotIn("Lantern Café", output)
            self.assertNotIn(str(FIXTURES), output)
            conn.close()

    def test_takeout_zip_parses_without_extracting_private_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "takeout.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                for source in sorted(path for path in FIXTURES.rglob("*") if path.is_file()):
                    bundle.write(source, source.relative_to(FIXTURES).as_posix())

            rows = list(saved_places.iter_takeout_rows(archive))

            self.assertEqual(len(rows), 4)
            self.assertEqual(
                {row.source_member for row in rows},
                {
                    "Saved/Date Places.csv",
                    "Saved/Favorites.csv",
                    "Maps (your places)/Starred places.json",
                },
            )

    def test_csv_and_zip_import_do_not_use_eager_read_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "takeout.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                for source in sorted(path for path in FIXTURES.rglob("*") if path.is_file()):
                    bundle.write(source, source.relative_to(FIXTURES).as_posix())

            with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("eager path read")):
                directory_rows = list(saved_places.iter_takeout_rows(FIXTURES))
            with mock.patch.object(
                zipfile.ZipFile,
                "read",
                side_effect=AssertionError("eager zip read"),
            ):
                archive_rows = list(saved_places.iter_takeout_rows(archive))

            self.assertEqual(len(directory_rows), 4)
            self.assertEqual(len(archive_rows), 4)

    def test_unsafe_zip_member_is_rejected_before_database_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")
            saved_places.import_takeout(conn, FIXTURES)
            items_before = conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0]
            runs_before = conn.execute("SELECT COUNT(*) FROM saved_import_runs").fetchone()[0]
            archive = Path(tmp) / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr(
                    "../Saved/Evil.csv",
                    "title,item_content_url\nUnsafe,https://example.com/unsafe\n",
                )

            with self.assertRaisesRegex(ValueError, "saved_import_unsafe_archive_member"):
                saved_places.import_takeout(conn, archive)

            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0],
                items_before,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_import_runs").fetchone()[0],
                runs_before + 1,
            )
            status, error_code = conn.execute(
                "SELECT status, error_code FROM saved_import_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(status, "failed")
            self.assertEqual(error_code, "saved_import_unsafe_archive_member")
            conn.close()

    def test_malformed_geojson_fails_with_safe_code_before_database_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")
            saved_places.import_takeout(conn, FIXTURES)
            items_before = conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0]
            source = Path(tmp) / "bad" / "Maps (your places)" / "Starred places.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"features": [', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "saved_import_invalid_geojson"):
                saved_places.import_takeout(conn, source.parents[1])

            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0],
                items_before,
            )
            status, error_code = conn.execute(
                "SELECT status, error_code FROM saved_import_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            self.assertEqual(status, "failed")
            self.assertEqual(error_code, "saved_import_invalid_geojson")
            conn.close()

    def test_structurally_invalid_geojson_is_recoverable_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Maps (your places)" / "Starred places.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"type":"FeatureCollection","features":{"not":"a list"}}')
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            with self.assertRaisesRegex(ValueError, "saved_import_invalid_geojson"):
                saved_places.import_takeout(conn, source.parent.parent)

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0], 0)
            receipt = conn.execute(
                "SELECT status, error_code FROM saved_import_runs"
            ).fetchone()
            self.assertEqual(receipt, ("failed", "saved_import_invalid_geojson"))
            conn.close()

    def test_directory_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "takeout"
            saved_dir = root / "Saved"
            saved_dir.mkdir(parents=True)
            outside = Path(tmp) / "outside.csv"
            outside.write_text(
                "title,item_content_url\nOutside,https://example.com/outside\n",
                encoding="utf-8",
            )
            (saved_dir / "Leaked.csv").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "saved_import_unsafe_source_member"):
                list(saved_places.iter_takeout_rows(root))

    def test_directory_does_not_treat_parent_folder_name_as_saved_product(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Saved" / "takeout"
            root.mkdir(parents=True)
            (root / "Unrelated.csv").write_text(
                "title,item_content_url\nOutside,https://example.com/outside\n",
                encoding="utf-8",
            )

            self.assertEqual(list(saved_places.iter_takeout_rows(root)), [])

    def test_single_csv_enforces_row_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "saved_import_too_many_rows"):
            list(
                saved_places.iter_takeout_rows(
                    FIXTURES / "Saved" / "Date Places.csv",
                    saved_places.ImportLimits(max_rows=1),
                )
            )

    def test_single_csv_enforces_file_size_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "saved_import_file_too_large"):
            list(
                saved_places.iter_takeout_rows(
                    FIXTURES / "Saved" / "Date Places.csv",
                    saved_places.ImportLimits(max_file_bytes=10),
                )
            )

    def test_tag_only_saved_rows_are_skipped_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Saved" / "Mixed.csv"
            source.parent.mkdir(parents=True)
            source.write_text(
                "title,item_content_url,note,tags,comment\n"
                ",,,orphan-tag,\n"
                "Valid place,https://example.com/valid,,,\n",
                encoding="utf-8",
            )
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            result = saved_places.import_takeout(conn, source.parent.parent)

            self.assertEqual(result.row_count, 2)
            self.assertEqual(result.skipped_rows, 1)
            self.assertEqual(result.created_items, 1)
            self.assertEqual(
                conn.execute(
                    "SELECT row_count, skipped_rows FROM saved_import_runs"
                ).fetchone(),
                (2, 1),
            )
            conn.close()

    def test_source_labels_scope_same_named_collections_without_copying_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            first = saved_places.import_takeout(conn, FIXTURES, source_label="account-a")
            second = saved_places.import_takeout(conn, FIXTURES, source_label="account-b")
            repeat = saved_places.import_takeout(conn, FIXTURES, source_label="account-a")

            self.assertEqual(first.source_label, "account-a")
            self.assertEqual(second.source_label, "account-b")
            self.assertEqual(
                (second.created_collections, second.created_items, second.created_memberships),
                (3, 0, 4),
            )
            self.assertEqual(
                (repeat.created_collections, repeat.created_items, repeat.created_memberships),
                (0, 0, 0),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_collections").fetchone()[0],
                6,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_memberships").fetchone()[0],
                8,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT DISTINCT source_label FROM saved_import_runs ORDER BY source_label"
                ).fetchall(),
                [("account-a",), ("account-b",)],
            )
            conn.close()

    def test_adopt_unlabeled_import_scopes_existing_collections_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")
            saved_places.import_takeout(conn, FIXTURES)

            adopted = saved_places.import_takeout(
                conn,
                FIXTURES,
                source_label="account-a",
                adopt_unlabeled=True,
            )
            repeat = saved_places.import_takeout(conn, FIXTURES, source_label="account-a")

            self.assertEqual(adopted.adopted_collections, 3)
            self.assertEqual(
                (adopted.created_collections, adopted.created_items, adopted.created_memberships),
                (0, 0, 0),
            )
            self.assertEqual(
                (repeat.created_collections, repeat.created_items, repeat.created_memberships),
                (0, 0, 0),
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_collections").fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_memberships").fetchone()[0],
                4,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM saved_collections WHERE source_product NOT LIKE '%:account-a'"
                ).fetchone()[0],
                0,
            )
            conn.close()

    def test_adopt_unlabeled_refuses_a_different_export_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")
            saved_places.import_takeout(conn, FIXTURES)
            source = Path(tmp) / "Saved" / "Date Places.csv"
            source.parent.mkdir()
            source.write_text(
                "title,item_content_url\nDifferent place,https://example.com/different\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "saved_import_unlabeled_adoption_mismatch"):
                saved_places.import_takeout(
                    conn,
                    source.parent.parent,
                    source_label="account-a",
                    adopt_unlabeled=True,
                )

            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_collections").fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT status, error_code FROM saved_import_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone(),
                ("failed", "saved_import_unlabeled_adoption_mismatch"),
            )
            conn.close()

    def test_ensure_schema_migrates_existing_import_receipts_for_scoped_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(Path(tmp) / "saved.db")
            conn.executescript(
                """
                CREATE TABLE saved_import_runs (
                    run_id TEXT PRIMARY KEY,
                    source_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    created_collections INTEGER NOT NULL DEFAULT 0,
                    created_items INTEGER NOT NULL DEFAULT 0,
                    created_memberships INTEGER NOT NULL DEFAULT 0,
                    updated_collections INTEGER NOT NULL DEFAULT 0,
                    updated_items INTEGER NOT NULL DEFAULT 0,
                    updated_memberships INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    started_at REAL NOT NULL,
                    completed_at REAL
                );
                """
            )

            saved_places.ensure_schema(conn)
            conn.close()
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(saved_import_runs)")
            }
            self.assertIn("skipped_rows", columns)
            self.assertIn("source_label", columns)
            self.assertIn("adopted_collections", columns)
            conn.close()

    def test_missing_item_identity_rolls_back_collection_and_item_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "Saved.csv"
            source.write_text(
                "title,item_content_url,note,comment\n,,,metadata only\n",
                encoding="utf-8",
            )
            conn = sqlite3.connect(Path(tmp) / "saved.db")

            with self.assertRaisesRegex(ValueError, "saved_import_missing_identity"):
                saved_places.import_takeout(conn, source)

            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM saved_collections").fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM saved_items").fetchone()[0], 0)
            self.assertEqual(
                conn.execute(
                    "SELECT status, error_code FROM saved_import_runs"
                ).fetchone(),
                ("failed", "saved_import_missing_identity"),
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
