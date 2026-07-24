#!/usr/bin/env python3
"""Secrets resolver for the Roles + Tools engine (CONTRACT §5, INV-12/INV-13).

A tool spec never carries an inline token — it carries a `credential_ref:
secret://<name>` indirection. The actual secrets live ENCRYPTED in a blob
committed to the owner's OWN private repo at
`_system/state/secrets.enc.json` — a flat JSON of `{ "<name>": "<ciphertext>" }`
where each value is encrypted INDEPENDENTLY, so onboarding can add one secret
(`store_secret`) without re-encrypting the rest.

The MASTER KEY never sits in git. It arrives at run time via the environment
variable `ZTN_SECRET_MASTER_KEY`, set per-instance in the roles scheduler
routine's own env / secret config (never in the prompt body, never committed —
see `scheduler-prompts/roles-nightly.md → §Secrets`). The runner resolves
`secret://<name>` → plaintext IN MEMORY at run time and hands only the tool
RESULT to the body — a secret never enters an LLM prompt and never sits in git
as plaintext (INV-12).

Crypto primitive: `cryptography.fernet.Fernet` (AES128-CBC + HMAC, authenticated,
url-safe-base64 key). The master key IS a Fernet key (44-char urlsafe-base64).
Fernet is imported LAZILY inside the functions that need it — PyYAML is the
engine's only hard dependency, and a role with NO secrets must import this module
and run the pure helpers (`is_secret_ref` / `parse_secret_ref` /
`secrets_blob_path` / `master_key_present`) without `cryptography` present.

Deterministic module layer, no LLM. Cross-platform: `pathlib`, atomic writes
(`.tmp` + `Path.replace`, mirroring `roles_common._atomic_write`), UTF-8, LF.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from _common import state_dir


# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------

class SecretError(Exception):
    """A secret could not be resolved or stored (fail-closed).

    Raised — never a wrong/empty secret returned silently — when the master key
    env var is absent/empty, the blob is missing/corrupt, a requested name is
    absent, the name is malformed, or decryption fails (wrong key / tampered
    ciphertext). Messages are actionable and NEVER carry a plaintext secret.
    """


# -----------------------------------------------------------------------------
# Ref parsing (pure — no crypto)
# -----------------------------------------------------------------------------

# A secret name is a lowercase slug: starts alphanumeric, then `[a-z0-9._-]`.
# The same shape gates both a `secret://<name>` ref and a `store_secret(name)`
# argument (one SoT for the shape).
_SECRET_NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
# `\Z` (not `$`) so a trailing newline never sneaks through — `$` matches before
# a final `\n`, which would accept `secret://name\n` as well-formed.
SECRET_REF_RE = re.compile(r"^secret://([a-z0-9][a-z0-9._-]*)\Z")

# Environment variable the runner reads the master key from (§5, INV-13).
MASTER_KEY_ENV = "ZTN_SECRET_MASTER_KEY"


def is_secret_ref(value) -> bool:
    """True when `value` is a well-formed `secret://<name>` ref."""
    return isinstance(value, str) and SECRET_REF_RE.match(value) is not None


def parse_secret_ref(value) -> str | None:
    """Return `<name>` for a valid `secret://<name>` ref, else None."""
    if not isinstance(value, str):
        return None
    match = SECRET_REF_RE.match(value)
    return match.group(1) if match else None


def _valid_secret_name(name) -> bool:
    """True when `name` is a bare well-formed secret name (no `secret://`)."""
    return (
        isinstance(name, str)
        and _SECRET_NAME_RE.fullmatch(name) is not None
    )


def _coerce_name(ref_or_name) -> str:
    """Accept either `secret://<name>` or a bare `<name>`; return the name.

    Raises `SecretError` on anything that is not a well-formed secret name (the
    message names the offending value, never a secret value).
    """
    name = parse_secret_ref(ref_or_name)
    if name is None:
        name = ref_or_name
    if not _valid_secret_name(name):
        raise SecretError(
            f"invalid secret name {ref_or_name!r}: expected a lowercase slug "
            "matching [a-z0-9][a-z0-9._-]* (optionally as 'secret://<name>')"
        )
    return name


# -----------------------------------------------------------------------------
# Paths (resolved from _common.state_dir — no hardcoded paths)
# -----------------------------------------------------------------------------

def secrets_blob_path(base: Path | None = None) -> Path:
    """`_system/state/secrets.enc.json` — the encrypted secrets blob."""
    return state_dir(base) / "secrets.enc.json"


# -----------------------------------------------------------------------------
# Master key
# -----------------------------------------------------------------------------

def master_key_present() -> bool:
    """True when `ZTN_SECRET_MASTER_KEY` is set AND non-empty."""
    return bool(os.environ.get(MASTER_KEY_ENV, "").strip())


def _require_master_key() -> str:
    """Return the master key from the environment, or raise `SecretError`."""
    key = os.environ.get(MASTER_KEY_ENV, "").strip()
    if not key:
        raise SecretError(
            f"master key env var {MASTER_KEY_ENV} is absent or empty — set it as "
            f"{MASTER_KEY_ENV}=<your key> in the roles scheduler routine's env / secret "
            "config (see scheduler-prompts/roles-nightly.md §Secrets). Generate one "
            "with roles_secrets.generate_master_key()."
        )
    return key


def _fernet(key: str):
    """Build a `Fernet` from the master key. Lazy-imports `cryptography`.

    Raises `SecretError` (not `ImportError`) when `cryptography` is absent, or
    when the key is not a valid Fernet key — both actionable.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise SecretError(
            "the 'cryptography' package is required to resolve or store secrets "
            "but is not installed — run: pip install cryptography"
        ) from exc
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretError(
            f"master key in {MASTER_KEY_ENV} is not a valid Fernet key "
            "(expected 44-char urlsafe-base64) — regenerate it with "
            "roles_secrets.generate_master_key()"
        ) from exc


def generate_master_key() -> str:
    """Return a fresh Fernet master key (44-char urlsafe-base64 string).

    Lazy-imports `cryptography`; raises `SecretError` if it is missing.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise SecretError(
            "the 'cryptography' package is required to generate a master key "
            "but is not installed — run: pip install cryptography"
        ) from exc
    return Fernet.generate_key().decode("utf-8")


# -----------------------------------------------------------------------------
# Blob I/O (atomic, per-value encryption)
# -----------------------------------------------------------------------------

def _atomic_write(path: Path, text: str) -> None:
    """Atomic write mirroring `roles_common._atomic_write` (LF, UTF-8, `.tmp`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    tmp.replace(path)


def _load_blob(base: Path | None) -> dict:
    """Read the secrets blob into a `{name: ciphertext}` dict.

    A MISSING blob is a hard error at RESOLVE time (a caller asking for a secret
    when no blob exists is a misconfiguration to surface, not to paper over). An
    absent blob is handled separately by `store_secret` (it creates one), which
    does not call this. A present-but-corrupt blob raises `SecretError`.
    """
    path = secrets_blob_path(base)
    if not path.is_file():
        raise SecretError(
            f"secrets blob not found at {path} — no secrets are stored yet. Add "
            "one via the concierge onboarding (roles_secrets.store_secret)."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SecretError(f"cannot read secrets blob at {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SecretError(
            f"secrets blob at {path} is corrupt (not valid JSON): {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise SecretError(
            f"secrets blob at {path} is corrupt: expected a JSON object of "
            f"{{name: ciphertext}}, got {type(data).__name__}"
        )
    return data


def resolve_secret(ref_or_name, base: Path | None = None) -> str:
    """Resolve `secret://<name>` (or a bare `<name>`) to its plaintext.

    Reads the master key from `ZTN_SECRET_MASTER_KEY`, loads the blob, and
    decrypts the one value in memory. Fail-closed: raises `SecretError` — never
    returns a wrong/empty value — when the key is absent, the blob is missing or
    corrupt, the name is absent, or decryption fails (wrong key / tampered
    ciphertext → Fernet `InvalidToken`). The exception message never carries the
    plaintext.
    """
    name = _coerce_name(ref_or_name)
    key = _require_master_key()
    blob = _load_blob(base)
    if name not in blob:
        raise SecretError(
            f"secret {name!r} is not present in the blob at "
            f"{secrets_blob_path(base)} — store it first via the concierge "
            "onboarding (roles_secrets.store_secret)."
        )
    token = blob[name]
    if not isinstance(token, str):
        raise SecretError(
            f"secret {name!r} in the blob is corrupt (ciphertext is "
            f"{type(token).__name__}, expected a string)"
        )
    # `_fernet` wraps a missing `cryptography` into an actionable SecretError; build it
    # FIRST so that path is honoured, then import InvalidToken (safe — cryptography is
    # present if `_fernet` returned). A bare top-of-block import would leak ImportError.
    fernet = _fernet(key)
    from cryptography.fernet import InvalidToken
    try:
        plaintext = fernet.decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise SecretError(
            f"failed to decrypt secret {name!r} — the master key is wrong for "
            "this blob, or the ciphertext was tampered with. Check that "
            f"{MASTER_KEY_ENV} matches the key used to store it."
        ) from exc
    return plaintext.decode("utf-8")


def store_secret(name, plaintext, base: Path | None = None) -> None:
    """Encrypt `plaintext` under `name` and upsert it into the blob (atomic).

    Used by the concierge first-secret onboarding. READS the existing blob (if
    any), upserts the ONE name, and writes atomically — so adding one secret
    preserves the others (each value independently encrypted). Creates the blob
    when absent. Validates `name` against the same shape as `parse_secret_ref`.

    Fail-closed: raises `SecretError` on a bad name, an absent/invalid master
    key, missing `cryptography`, or a corrupt existing blob. Never logs the
    plaintext.
    """
    name = _coerce_name(name)
    if not isinstance(plaintext, str):
        raise SecretError(
            f"plaintext for secret {name!r} must be a string, got "
            f"{type(plaintext).__name__}"
        )
    key = _require_master_key()
    fernet = _fernet(key)

    path = secrets_blob_path(base)
    if path.is_file():
        blob = _load_blob(base)
    else:
        blob = {}

    token = fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    blob[name] = token
    # Sorted keys + trailing newline → a stable, diff-friendly blob.
    text = json.dumps(blob, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(path, text)
