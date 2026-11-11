import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "release", Path(__file__).parent.parent / "support" / "release.py"
)
release = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(release)


class TestFindPrev(unittest.TestCase):
    def test_highest_by_version_not_text(self):
        self.assertEqual(release.find_prev({"1.2.2", "1.10.0", "1.9.9"}), "1.10.0")

    def test_ignores_non_semver_tags(self):
        tags = {"1.2.2", "1.3.0rc1", "v2.0.0", "1.3.0.dev0", "latest"}
        self.assertEqual(release.find_prev(tags), "1.2.2")

    def test_none_when_no_matching_tag(self):
        self.assertIsNone(release.find_prev({"1.0.0rc3", "foo"}))
        self.assertIsNone(release.find_prev(set()))


class TestFindNew(unittest.TestCase):
    def test_one_new_tag(self):
        self.assertEqual(release.find_new({"1.2.2"}, {"1.2.2", "1.3.0"}), "1.3.0")

    def test_no_new_tag(self):
        with self.assertRaises(release.ReleaseError):
            release.find_new({"1.2.2"}, {"1.2.2"})

    def test_several_new_tags(self):
        with self.assertRaises(release.ReleaseError):
            release.find_new({"1.2.2"}, {"1.2.2", "1.3.0", "1.3.1"})


if __name__ == "__main__":
    unittest.main()
