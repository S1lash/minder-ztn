"""SSRF guard for the http read/act adapter (roles_tool_http).

A read tool's URL is body-supplied, and the body can be steered by poisoned tool
content it just ingested. The guard refuses a request that targets — or a redirect
that lands on — a link-local / cloud-metadata address, so the host's IAM role or an
internal link-local service can never be read into the model's ephemeral context
(INV-10). Loopback / RFC1918 are intentionally NOT blocked (the design lets a
public-fetch tool roam; the stage fixtures use 127.0.0.1).
"""

import unittest

import roles_tool_http as rh
import roles_tools as rt


class SsrfHostClassifierTest(unittest.TestCase):
    def test_metadata_ipv4_blocked(self):
        # AWS/GCP/Azure IMDS — the crown-jewel SSRF target.
        self.assertEqual(rh._ssrf_blocked_host("169.254.169.254"), "169.254.169.254")

    def test_link_local_range_blocked(self):
        # The whole 169.254.0.0/16 link-local range, not only the metadata IP.
        self.assertTrue(rh._ssrf_blocked_host("169.254.42.7"))

    def test_ipv6_link_local_blocked(self):
        self.assertTrue(rh._ssrf_blocked_host("fe80::1"))

    def test_ipv6_metadata_literal_blocked(self):
        self.assertEqual(rh._ssrf_blocked_host("fd00:ec2::254"), "fd00:ec2::254")

    def test_loopback_allowed(self):
        # Loopback is intentionally allowed (fixtures + a role reaching a local service).
        self.assertEqual(rh._ssrf_blocked_host("127.0.0.1"), "")

    def test_private_rfc1918_allowed(self):
        # RFC1918 is not blocked (documented roam) — only link-local / metadata are.
        self.assertEqual(rh._ssrf_blocked_host("10.0.0.5"), "")

    def test_public_literal_allowed(self):
        self.assertEqual(rh._ssrf_blocked_host("93.184.216.34"), "")


class SsrfExecGuardTest(unittest.TestCase):
    def _spec(self):
        return rt.ToolSpec(
            tool_id="web-fetch", direction="read", adapter="http",
            cadence_slot="on-demand", grounding_landing="ephemeral",
            max_calls_per_run=2, credential_ref=None, plain_purpose="", usage_note="",
            status="active")

    def test_metadata_url_refused_before_network(self):
        # The guard fires BEFORE any socket work: the message is the SSRF-guard message,
        # not a connection-error ("http request failed") — proving no fetch was attempted.
        r = rh.exec_tool(
            self._spec(),
            {"url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/"},
            None)
        self.assertEqual(r.status, "unknown")
        self.assertIn("SSRF guard", r.summary)
        self.assertNotIn("http request failed", r.summary)

    def test_link_local_url_refused(self):
        r = rh.exec_tool(self._spec(), {"url": "http://169.254.42.7/x"}, None)
        self.assertEqual(r.status, "unknown")
        self.assertIn("SSRF guard", r.summary)


if __name__ == "__main__":
    unittest.main()
