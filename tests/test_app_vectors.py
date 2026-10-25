"""The Dart app and appapi.py must compute identical pairing proofs. The expected values are written in the app's tests
(app/test/protocol_test.dart); this checks the Python side still produces exactly those, so neither side can drift alone."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appapi  # noqa: E402

DART_TEST = Path(__file__).resolve().parent.parent / "app" / "test" / "protocol_test.dart"


class VectorTests(unittest.TestCase):
    def test_python_gives_the_values_the_dart_tests_expect(self):
        text = DART_TEST.read_text()
        client = re.search(r"clientProof\(\s*code,\s*nonce,\s*fp\s*\),\s*'([0-9a-f]{64})'", text).group(1)
        server = re.search(r"serverProof\(\s*code,\s*nonce,\s*fp,\s*'tok_en-123'\s*\),\s*'([0-9a-f]{64})'", text).group(1)
        code, nonce, fp = "K7PQ-2M9X-4TWD", "abcDEF123_-xyz", "ab" * 32
        self.assertEqual(appapi.client_proof(code, nonce, fp), client)
        self.assertEqual(appapi.server_proof(code, nonce, fp, "tok_en-123"), server)


if __name__ == "__main__":
    unittest.main()
