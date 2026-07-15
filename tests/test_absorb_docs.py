import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AbsorbDocumentationTests(unittest.TestCase):
    def test_required_documentation_sections_exist(self):
        for section in (
            "brand", "architecture", "conversation", "deployment",
            "migration", "security", "troubleshooting",
        ):
            self.assertTrue((ROOT / "docs" / section / "README.md").is_file(), section)

    def test_documentation_section_links_exist(self):
        for readme in (ROOT / "docs").glob("*/README.md"):
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                with self.subTest(readme=readme, target=target):
                    self.assertTrue((readme.parent / target.split("#", 1)[0]).resolve().exists())

    def test_readme_local_links_exist(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", readme):
            if "://" in target or target.startswith("#"):
                continue
            path = (ROOT / target.split("#", 1)[0]).resolve()
            with self.subTest(target=target):
                self.assertTrue(path.is_file())

    def test_cutover_checklist_covers_external_boundaries_and_rollback(self):
        text = (ROOT / "docs" / "absorb-cutover-checklist.md").read_text(encoding="utf-8")
        for required in (
            "GitHub repository rename",
            "Cloud Run",
            "LINE Official Account",
            "Windows data root",
            "Rollback",
            "不刪",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
