import tempfile
import unittest
from pathlib import Path

from placeintel import cache


class CacheContractTest(unittest.TestCase):
    def test_upsert_place_coerces_list_category_to_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = cache.connect(Path(tmp) / "placeintel.db")
            place = cache.Place(
                place_id="place-list-category",
                name="List Category Cafe",
                category=["Cafe", "Coffee shop"],
                address="1 Test St",
                source="test",
            )

            cache.upsert_place(conn, place)

            row = cache.get_place(conn, "place-list-category")
            self.assertIsNotNone(row)
            self.assertEqual(row["category"], "Cafe · Coffee shop")


if __name__ == "__main__":
    unittest.main()
