"""The Android release key must never be in the repository, and a release must not quietly ship with the wrong one."""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRADLE = (ROOT / "app/android/app/build.gradle.kts").read_text()
WORKFLOW = (ROOT / ".github/workflows/build-app.yml").read_text()


class Signing(unittest.TestCase):
    def test_passwords_and_key_files_come_from_the_environment_only(self):
        self.assertIn('System.getenv("BOB_KEYSTORE_FILE")', GRADLE)
        self.assertIn('System.getenv("BOB_KEYSTORE_PASSWORD")', GRADLE)
        self.assertIsNone(re.search(r'(storePassword|keyPassword)\s*=\s*"', GRADLE), "a password is written into the build file")

    def test_no_key_files_are_tracked(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        bad = [f for f in files if f.endswith((".jks", ".keystore", ".p12")) or Path(f).name == "key.properties"]
        self.assertEqual(bad, [])

    def test_a_release_without_the_key_is_refused_and_a_test_build_only_warns(self):
        self.assertIn("BOB_KEYSTORE_BASE64", WORKFLOW)
        step = WORKFLOW[WORKFLOW.index("Release signing key"):WORKFLOW.index("name: Build\n        working-directory: app", WORKFLOW.index("Release signing key"))]
        self.assertIn('= "release" ]', step)
        self.assertIn("exit 1", step)
        self.assertIn("::warning::", step)

    def test_builds_get_a_rising_build_number_and_the_signer_is_checked(self):
        self.assertIn("--build-number=${{ github.run_number }}", WORKFLOW)
        self.assertIn("apksigner", WORKFLOW)
        self.assertIn("Android Debug", WORKFLOW)

    def test_the_debug_key_is_still_the_fallback_for_local_builds(self):
        self.assertIn('findByName("release") ?: signingConfigs.getByName("debug")', GRADLE)


if __name__ == "__main__":
    unittest.main()
