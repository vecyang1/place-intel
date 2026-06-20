import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-prd-contract.sh"


class PrdContractTest(unittest.TestCase):
    def test_current_prd_set_passes_with_legacy_audit(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), "--allow-legacy", str(ROOT)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PRD contract OK", result.stdout)

    def test_strict_mode_rejects_legacy_prds(self) -> None:
        result = subprocess.run(
            [str(SCRIPT), str(ROOT)],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy PRD", result.stderr)

    def test_unrouted_new_prd_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks"
            tasks.mkdir()
            (tasks / "README.md").write_text("# PRD Router\n", encoding="utf-8")
            (tasks / "2026-06-20 - prd missing-route.md").write_text(
                textwrap.dedent(
                    """\
                    # Missing Route PRD

                    Created: 2026-06-20
                    Last Updated: 2026-06-20
                    Status: Draft
                    Feature Type: Internal governance
                    Owner: Codex
                    """
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [str(SCRIPT), str(root)],
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not routed", result.stderr)


if __name__ == "__main__":
    unittest.main()
