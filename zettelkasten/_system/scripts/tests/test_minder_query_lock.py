"""Hard read-lock: --config/--remit-json gated behind ZTN_DEV=1 + --enforced mode.

INV-15 / CONTRACT §6.1: the tick body's only scope source is `--role`; the
`--config`/`--remit-json` dev overrides must be gated behind an explicit dev flag,
and an `--enforced` (role-bound) invocation refuses them unconditionally so the
body cannot read around its remit by construction.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import minder_query as mq  # noqa: E402


def _ns(**kw) -> argparse.Namespace:
    base = dict(role=None, config=None, remit_json=None, base=None, enforced=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _write_role(tmp: Path) -> None:
    d = tmp / "_system" / "roles" / "r"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yml").write_text(
        "id: r\nparts: [{id: p1, kind: ledger}]\nremit: {all: true}\n"
        "cadence: daily\nstatus: active\n", encoding="utf-8")


class RemitJsonGateTest(unittest.TestCase):
    def test_remit_json_refused_without_ztn_dev(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SystemExit):
                mq._load_remit_source(_ns(remit_json='{"all": true}'))

    def test_config_refused_without_ztn_dev(self):
        with tempfile.TemporaryDirectory() as t:
            with unittest.mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(SystemExit):
                    mq._load_remit_source(_ns(config=str(Path(t) / "c.yml")))

    def test_remit_json_allowed_with_ztn_dev(self):
        with unittest.mock.patch.dict(os.environ, {"ZTN_DEV": "1"}):
            remit, cfg = mq._load_remit_source(_ns(remit_json='{"all": true}'))
            self.assertTrue(remit.all)
            self.assertIsNone(cfg)

    def test_role_source_always_works(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _write_role(tmp)
            with unittest.mock.patch.dict(os.environ, {}, clear=True):
                remit, cfg = mq._load_remit_source(_ns(role="r", base=str(tmp)))
            self.assertTrue(remit.all)
            self.assertEqual(cfg.id, "r")


class EnforcedModeTest(unittest.TestCase):
    def test_enforced_refuses_config_even_with_ztn_dev(self):
        # Belt-and-suspenders: --enforced refuses scope overrides UNCONDITIONALLY.
        with unittest.mock.patch.dict(os.environ, {"ZTN_DEV": "1"}):
            with self.assertRaises(SystemExit):
                mq._load_remit_source(_ns(enforced=True, remit_json='{"all": true}'))

    def test_enforced_requires_role(self):
        with self.assertRaises(SystemExit):
            mq._load_remit_source(_ns(enforced=True))

    def test_enforced_with_role_works(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _write_role(tmp)
            remit, cfg = mq._load_remit_source(_ns(enforced=True, role="r", base=str(tmp)))
            self.assertTrue(remit.all)


if __name__ == "__main__":
    unittest.main()
