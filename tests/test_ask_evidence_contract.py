import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from placeintel import cache, config, pipeline


class _FakeResponse:
    text = "D'Class is usable, but confirm the deposit before leaving ID."


class _FakeModels:
    def generate_content(self, **kwargs):
        return _FakeResponse()


class _FakeClient:
    models = _FakeModels()


class AskEvidenceContractTest(unittest.TestCase):
    def _with_temp_cache(self):
        tmp = tempfile.TemporaryDirectory()
        data_dir = Path(tmp.name) / "data"
        db_path = data_dir / "placeintel.db"
        patcher = mock.patch.multiple(config, DATA_DIR=data_dir, DB_PATH=db_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(tmp.cleanup)
        conn = cache.connect()
        cache.upsert_place(conn, cache.Place(
            place_id="place-1",
            name="D'Class Guitar",
            category="Musical instrument store",
            address="49/9 Nguyen Tat Thanh",
            rating=4.8,
            review_count=149,
            phone="+84 123",
            website="https://example.test",
            hours={"Mon": "09:00-18:00"},
        ))
        cache.upsert_reviews(conn, [cache.Review(
            review_id="review-1",
            place_id="place-1",
            author="Grace",
            rating=2,
            text="Parking was difficult, but the owner explained rental deposits clearly.",
            lang="en",
            review_date="2026-06-01",
        )])
        cache.store_vectors(conn, [("review-1", np.array([1.0, 0.0], dtype=np.float32))])
        conn.close()

    def test_fresh_ask_returns_listing_and_review_evidence_cards(self) -> None:
        self._with_temp_cache()
        provider_info = {"reason": {"model": "test-model", "provider": "VectorEngine"}}
        with mock.patch.object(pipeline.embed, "embed_query", return_value=np.array([1.0, 0.0])), \
             mock.patch.object(pipeline.config, "provider_info", return_value=provider_info), \
             mock.patch.object(pipeline.analyze, "_client", return_value=_FakeClient()):
            result = pipeline.ask("Is the deposit clear?", place_id="place-1", top_k=1)

        self.assertFalse(result["cached"])
        self.assertEqual(result["cache_scope"]["kind"], "place")
        self.assertEqual(result["cache_scope"]["place_id"], "place-1")
        self.assertEqual(result["cache_scope"]["label"], "D'Class Guitar")
        self.assertGreater(result["evidence_fresh_after"], 0)
        self.assertEqual({item["type"] for item in result["evidence"]}, {"listing", "review"})

        listing = [item for item in result["evidence"] if item["type"] == "listing"]
        self.assertIn(("address", "49/9 Nguyen Tat Thanh"), [(item["label"], item["value"]) for item in listing])
        self.assertIn(("phone", "+84 123"), [(item["label"], item["value"]) for item in listing])

        review = next(item for item in result["evidence"] if item["type"] == "review")
        self.assertEqual(review["place_name"], "D'Class Guitar")
        self.assertEqual(review["review_id"], "review-1")
        self.assertEqual(review["rating"], 2)
        self.assertEqual(review["date"], "2026-06-01")
        self.assertEqual(review["source_lang"], "en")
        self.assertIn("Parking was difficult", review["text"])


if __name__ == "__main__":
    unittest.main()
