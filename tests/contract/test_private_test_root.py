"""Private debug data must never become release source or package content."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts._source_capture import SourceCaptureError, capture_source_tree
from scripts.check_package import PackageCheckError, validate_tarball
from tools.test.environment import configure_paths


ROOT = Path(__file__).resolve().parents[2]


class PrivateTestRootTests(unittest.TestCase):
    def setUp(self):
        base = Path(os.environ.get("CORAGENT_TEST_ENV_ROOT", ROOT / "local_debug")) / "tmp"
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="privacy-", dir=base)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def repository(self):
        root = self.root / "repo"
        files = {
            ".gitignore": "/local_debug/\n",
            "README.md": "fixture\n",
            "package.json": '{}\n',
            "backend/pyproject.toml": "[build-system]\nrequires = []\n",
            "scripts/build_release.py": "# fixture\n",
            "scripts/check_package.py": "# fixture\n",
            "scripts/package_inventory.py": "# fixture\n",
        }
        for name, content in files.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        self.git(root, "init", "-q")
        self.git(root, "add", ".")
        self.git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        return root

    @staticmethod
    def git(root, *args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    def test_clean_and_dirty_captures_inside_debug_exclude_private_data(self):
        root = self.repository()
        private = root / "local_debug" / "private.txt"
        private.parent.mkdir()
        private.write_text("synthetic-private-marker")
        for dirty in (False, True):
            if dirty:
                (root / "README.md").write_text("changed fixture\n")
            captured = capture_source_tree(root, private.parent / str(dirty), allow_dirty=dirty)
            self.assertEqual(captured.dirty, dirty)
            self.assertFalse((captured.root / "local_debug").exists())
            self.assertFalse(any(name.startswith(b"local_debug/") for name in captured.relative_names))
            captured.verify()

    def test_force_staged_debug_data_blocks_release_capture(self):
        root = self.repository()
        private = root / "local_debug" / "private.txt"
        private.parent.mkdir()
        private.write_text("synthetic-private-marker")
        self.git(root, "add", "-f", str(private.relative_to(root)))
        with self.assertRaisesRegex(SourceCaptureError, "private local_debug"):
            capture_source_tree(root, self.root / "output", allow_dirty=True)
        self.assertFalse((self.root / "output").exists())

    def test_package_rejects_debug_even_if_an_allowlist_includes_it(self):
        private = "local_debug/notes.txt"
        with patch("scripts.check_package.REQUIRED_TARBALL_FILES", set()), \
             patch("scripts.check_package.expanded_allowlisted_files", return_value={private}):
            with self.assertRaisesRegex(PackageCheckError, "forbidden files.*local_debug"):
                validate_tarball({"package.json", private})

    def test_scratch_and_caches_follow_the_selected_private_root(self):
        previous_tempdir = tempfile.tempdir
        self.addCleanup(setattr, tempfile, "tempdir", previous_tempdir)
        root = self.root / "environment"
        with patch.dict(os.environ):
            configure_paths(root)
            with tempfile.TemporaryDirectory() as temporary:
                self.assertTrue(Path(temporary).is_relative_to(root))
            for key in ("CORAGENT_TEST_ROOT", "TMPDIR", "npm_config_cache", "PIP_CACHE_DIR",
                        "CONDA_PKGS_DIRS", "XDG_CACHE_HOME"):
                self.assertTrue(Path(os.environ[key]).is_relative_to(root), key)


if __name__ == "__main__":
    unittest.main()
