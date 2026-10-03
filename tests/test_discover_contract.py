import unittest

from placeintel import discover


class DiscoverContractTest(unittest.TestCase):
    def test_serpapi_places_without_link_keep_scraper_friendly_maps_url(self) -> None:
        place = discover._serpapi_result_to_place({
            "title": "Melody Boutique Villa Hoi An",
            "place_id": "ChIJ3Ws992wOQjEREoE-Ob2T4HE",
            "data_id": "0x31420e6cf73d6bdd:0x71e093bd393e8112",
            "gps_coordinates": {"latitude": 15.895, "longitude": 108.3177},
            "reviews": 596,
        })

        self.assertIsNotNone(place)
        self.assertIn("/maps/place/Melody+Boutique+Villa+Hoi+An/", place.maps_url)
        self.assertIn("place_id:ChIJ3Ws992wOQjEREoE-Ob2T4HE", place.maps_url)


if __name__ == "__main__":
    unittest.main()
