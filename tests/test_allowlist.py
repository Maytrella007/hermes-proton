"""Tests for the one thing standing between the agent and your contact book."""

from __future__ import annotations

import os
import unittest

import proton_tools as tools


class Allowlist(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _set(self, value: str) -> None:
        os.environ[tools.ALLOWLIST_ENV] = value

    def test_empty_allowlist_refuses_everyone(self) -> None:
        os.environ.pop(tools.ALLOWLIST_ENV, None)
        self.assertEqual(tools.recipient_refusals(["a@b.com"]), ["a@b.com"])

    def test_exact_address(self) -> None:
        self._set("boss@acme.com")
        self.assertEqual(tools.recipient_refusals(["boss@acme.com"]), [])
        self.assertEqual(tools.recipient_refusals(["other@acme.com"]), ["other@acme.com"])

    def test_case_insensitive(self) -> None:
        self._set("Boss@Acme.com")
        self.assertEqual(tools.recipient_refusals(["BOSS@acme.COM"]), [])

    def test_domain_glob(self) -> None:
        self._set("*@acme.com")
        self.assertEqual(tools.recipient_refusals(["anyone@acme.com"]), [])
        self.assertEqual(
            tools.recipient_refusals(["anyone@evil.com"]), ["anyone@evil.com"]
        )

    def test_lookalike_domain_is_refused(self) -> None:
        self._set("*@acme.com")
        for sneaky in ("x@acme.com.evil.com", "x@notacme.com", "x@acme.co"):
            self.assertEqual(tools.recipient_refusals([sneaky]), [sneaky], sneaky)

    def test_bcc_is_also_checked_against_the_allowlist(self) -> None:
        self._set("a@b.com")
        answer = tools.handle_send(
            {"to": ["a@b.com"], "bcc": ["c@d.com"], "subject": "s", "body": "b"}
        )
        self.assertIn("Refused", answer)
        self.assertIn("c@d.com", answer)

    def test_send_refuses_without_allowlist(self) -> None:
        os.environ.pop(tools.ALLOWLIST_ENV, None)
        answer = tools.handle_send({"to": ["a@b.com"], "subject": "s", "body": "b"})
        self.assertIn("Sending is disabled", answer)


if __name__ == "__main__":
    unittest.main()


class AllowlistComesFromTheSettings(unittest.TestCase):
    """The allowlist is a setting, not a secret.

    `.env` holds secrets; a list of addresses the agent may write to is
    visible behaviour a person should be able to read and change on the
    plugin's own page, and it belongs to the profile that set it. The
    environment variable is still read when the setting is empty, because the
    standalone CLI has no settings and nobody configured that way should have
    sending stop working.
    """

    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ.pop(tools.ALLOWLIST_ENV, None)

    def tearDown(self) -> None:
        tools.use_hermes(None)
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _ctx(self, value):
        class _Ctx:
            def get_config(self, key, default=None):
                return value if key == "allowed_recipients" else default
        return _Ctx()

    def test_a_list_setting_is_the_allowlist(self) -> None:
        tools.use_hermes(self._ctx(["A@B.com", "*@acme.com"]))
        self.assertEqual(tools.allowed_recipients(), ["a@b.com", "*@acme.com"])
        self.assertEqual(tools.recipient_refusals(["who@acme.com"]), [])

    def test_a_comma_separated_string_is_accepted_too(self) -> None:
        tools.use_hermes(self._ctx("a@b.com, *@acme.com"))
        self.assertEqual(tools.allowed_recipients(), ["a@b.com", "*@acme.com"])

    def test_the_environment_still_answers_when_the_setting_is_empty(self) -> None:
        tools.use_hermes(self._ctx([]))
        os.environ[tools.ALLOWLIST_ENV] = "legacy@b.com"
        self.assertEqual(tools.allowed_recipients(), ["legacy@b.com"])

    def test_with_neither_there_is_no_allowlist_and_sending_is_refused(self) -> None:
        tools.use_hermes(self._ctx([]))
        self.assertEqual(tools.allowed_recipients(), [])
        self.assertEqual(tools.recipient_refusals(["a@b.com"]), ["a@b.com"])
