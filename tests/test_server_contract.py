import unittest

import placeintel
from placeintel import server


class ServerContractTest(unittest.TestCase):
    def test_fastapi_version_matches_package_version(self) -> None:
        self.assertEqual(server.app.version, placeintel.__version__)


if __name__ == "__main__":
    unittest.main()
