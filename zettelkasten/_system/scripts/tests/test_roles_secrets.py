"""Tests for roles_secrets.py — the secrets resolver (CONTRACT §5, INV-12/13).

Tempdir-isolated; `ZTN_SECRET_MASTER_KEY` is patched per-test via
`patch.dict(os.environ, ...)`. No network, no LLM. The crypto tests self-skip
if `cryptography` is unavailable — but it IS installed (cryptography==41.0.7),
so they run.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roles_secrets as rs  # noqa: E402

try:
    import cryptography  # noqa: F401

    _HAVE_CRYPTO = True
except ImportError:
    _HAVE_CRYPTO = False


class RefParsingTest(unittest.TestCase):
    """Pure ref parsing — no crypto, no env, no filesystem."""

    def test_is_secret_ref_valid(self) -> None:
        for ref in (
            "secret://notion-token",
            "secret://a",
            "secret://gdrive.oauth_refresh",
            "secret://x_1",
            "secret://perplexity-key",
        ):
            self.assertTrue(rs.is_secret_ref(ref), ref)

    def test_is_secret_ref_invalid(self) -> None:
        for bad in (
            "notion-token",             # no scheme
            "secret://",                # empty name
            "secret://-lead",           # must start alphanumeric
            "secret://Upper",           # uppercase not allowed
            "secret://a b",             # space
            "secret://a/b",             # slash
            "secret://a\n",             # trailing newline
            "http://x",                 # wrong scheme
            "",
            None,
            123,
        ):
            self.assertFalse(rs.is_secret_ref(bad), repr(bad))

    def test_parse_secret_ref_returns_name_or_none(self) -> None:
        self.assertEqual(rs.parse_secret_ref("secret://notion-token"), "notion-token")
        self.assertEqual(rs.parse_secret_ref("secret://a.b_c-d"), "a.b_c-d")
        self.assertIsNone(rs.parse_secret_ref("notion-token"))
        self.assertIsNone(rs.parse_secret_ref("secret://"))
        self.assertIsNone(rs.parse_secret_ref(None))
        self.assertIsNone(rs.parse_secret_ref(42))


class BlobPathTest(unittest.TestCase):
    def test_blob_path_under_state_dir(self) -> None:
        base = Path("/tmp/some-base")
        path = rs.secrets_blob_path(base)
        self.assertEqual(path.name, "secrets.enc.json")
        self.assertTrue(str(path).endswith("_system/state/secrets.enc.json"))


class MasterKeyPresentTest(unittest.TestCase):
    def test_present_true_when_set_nonempty(self) -> None:
        with unittest.mock.patch.dict(os.environ, {rs.MASTER_KEY_ENV: "some-key"}):
            self.assertTrue(rs.master_key_present())

    def test_present_false_when_absent(self) -> None:
        # Remove the var entirely if it exists in the ambient env.
        env = dict(os.environ)
        env.pop(rs.MASTER_KEY_ENV, None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(rs.master_key_present())

    def test_present_false_when_empty_or_whitespace(self) -> None:
        for val in ("", "   "):
            with unittest.mock.patch.dict(os.environ, {rs.MASTER_KEY_ENV: val}):
                self.assertFalse(rs.master_key_present())


@unittest.skipUnless(_HAVE_CRYPTO, "cryptography not installed")
class CryptoRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.key = rs.generate_master_key()

    def _env(self, key: str | None = None):
        return unittest.mock.patch.dict(
            os.environ, {rs.MASTER_KEY_ENV: key or self.key}
        )

    def test_generate_master_key_is_fernet_shaped(self) -> None:
        # 44-char urlsafe-base64 (Fernet key).
        self.assertEqual(len(self.key), 44)
        self.assertIsInstance(self.key, str)

    def test_store_then_resolve_round_trip(self) -> None:
        with self._env():
            rs.store_secret("notion-token", "s3cr3t-value", base=self.base)
            # Resolve via bare name and via secret:// ref — both return plaintext.
            self.assertEqual(
                rs.resolve_secret("notion-token", base=self.base), "s3cr3t-value"
            )
            self.assertEqual(
                rs.resolve_secret("secret://notion-token", base=self.base),
                "s3cr3t-value",
            )

    def test_upsert_preserves_earlier_secret(self) -> None:
        with self._env():
            rs.store_secret("token-a", "aaa", base=self.base)
            rs.store_secret("token-b", "bbb", base=self.base)
            self.assertEqual(rs.resolve_secret("token-a", base=self.base), "aaa")
            self.assertEqual(rs.resolve_secret("token-b", base=self.base), "bbb")

    def test_upsert_overwrites_same_name(self) -> None:
        with self._env():
            rs.store_secret("token-a", "old", base=self.base)
            rs.store_secret("token-a", "new", base=self.base)
            self.assertEqual(rs.resolve_secret("token-a", base=self.base), "new")

    def test_ciphertext_at_rest_is_not_plaintext(self) -> None:
        with self._env():
            rs.store_secret("token-a", "PLAINTEXT-MARKER", base=self.base)
        raw = rs.secrets_blob_path(self.base).read_text(encoding="utf-8")
        self.assertNotIn("PLAINTEXT-MARKER", raw)
        # And it is a well-formed JSON object of {name: ciphertext-string}.
        data = json.loads(raw)
        self.assertIn("token-a", data)
        self.assertIsInstance(data["token-a"], str)

    def test_each_value_independently_encrypted(self) -> None:
        # Two names present; each is its own token (independent encryption so
        # onboarding adds one without touching the rest).
        with self._env():
            rs.store_secret("token-a", "aaa", base=self.base)
            rs.store_secret("token-b", "bbb", base=self.base)
        data = json.loads(rs.secrets_blob_path(self.base).read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"token-a", "token-b"})
        self.assertNotEqual(data["token-a"], data["token-b"])

    def test_resolve_wrong_key_raises_secret_error(self) -> None:
        # Store with key A, resolve with key B → InvalidToken → SecretError.
        other_key = rs.generate_master_key()
        with self._env():
            rs.store_secret("token-a", "aaa", base=self.base)
        with self._env(other_key):
            with self.assertRaises(rs.SecretError) as ctx:
                rs.resolve_secret("token-a", base=self.base)
        # The error must NOT leak the plaintext.
        self.assertNotIn("aaa", str(ctx.exception))

    def test_resolve_missing_name_raises(self) -> None:
        with self._env():
            rs.store_secret("token-a", "aaa", base=self.base)
            with self.assertRaises(rs.SecretError) as ctx:
                rs.resolve_secret("nonesuch", base=self.base)
        self.assertIn("nonesuch", str(ctx.exception))

    def test_resolve_missing_blob_raises(self) -> None:
        # No store call — blob does not exist.
        with self._env():
            with self.assertRaises(rs.SecretError) as ctx:
                rs.resolve_secret("token-a", base=self.base)
        self.assertIn("not found", str(ctx.exception).lower())

    def test_resolve_corrupt_blob_raises(self) -> None:
        path = rs.secrets_blob_path(self.base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json {{{", encoding="utf-8")
        with self._env():
            with self.assertRaises(rs.SecretError) as ctx:
                rs.resolve_secret("token-a", base=self.base)
        self.assertIn("corrupt", str(ctx.exception).lower())

    def test_bad_secret_name_raises_on_store_and_resolve(self) -> None:
        with self._env():
            for bad in ("Upper", "-lead", "a b", "", "a/b"):
                with self.assertRaises(rs.SecretError):
                    rs.store_secret(bad, "x", base=self.base)
                with self.assertRaises(rs.SecretError):
                    rs.resolve_secret(bad, base=self.base)


@unittest.skipUnless(_HAVE_CRYPTO, "cryptography not installed")
class MasterKeyAbsentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def _clear_env(self):
        env = dict(os.environ)
        env.pop(rs.MASTER_KEY_ENV, None)
        return unittest.mock.patch.dict(os.environ, env, clear=True)

    def test_resolve_without_key_raises(self) -> None:
        with self._clear_env():
            with self.assertRaises(rs.SecretError) as ctx:
                rs.resolve_secret("token-a", base=self.base)
        self.assertIn(rs.MASTER_KEY_ENV, str(ctx.exception))

    def test_store_without_key_raises(self) -> None:
        with self._clear_env():
            with self.assertRaises(rs.SecretError) as ctx:
                rs.store_secret("token-a", "aaa", base=self.base)
        self.assertIn(rs.MASTER_KEY_ENV, str(ctx.exception))

    def test_empty_key_raises(self) -> None:
        with unittest.mock.patch.dict(os.environ, {rs.MASTER_KEY_ENV: "   "}):
            with self.assertRaises(rs.SecretError):
                rs.resolve_secret("token-a", base=self.base)


if __name__ == "__main__":
    unittest.main()
