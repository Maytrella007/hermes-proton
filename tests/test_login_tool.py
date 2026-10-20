"""Tests for the sign-in tool's guard rails.

The password never reaches the agent: the tool hands the person a terminal
command (``hermes proton login``) that reads it privately. These check the
paths that do not need a live account.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import proton_tools as tools
from protonlite.accounts import ROOT_ENV


class LoginGuards(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self._saved = os.environ.get(ROOT_ENV)
        os.environ[ROOT_ENV] = str(root)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(ROOT_ENV, None)
        else:
            os.environ[ROOT_ENV] = self._saved
        self._dir.cleanup()

    def test_address_is_required(self) -> None:
        self.assertIn("address", tools.handle_login({}).lower())

    def test_hands_off_to_the_terminal(self) -> None:
        answer = tools.handle_login({"address": "me@proton.me"})
        self.assertIn("hermes proton login --user me@proton.me", answer)
        self.assertIn("terminal", answer.lower())
        # The agent must never take the password through chat.
        self.assertIn("never take the account password through chat", answer)

    def test_refuses_when_that_account_is_already_signed_in(self) -> None:
        target = tools.store().path_for("me@proton.me")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        answer = tools.handle_login({"address": "me@proton.me"})
        self.assertIn("already signed in", answer)
        self.assertIn("force=true", answer)

    def test_a_second_account_does_not_need_force(self) -> None:
        """Adding a mailbox is normal; only re-signing the same one is wasteful."""
        target = tools.store().path_for("first@proton.me")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
        answer = tools.handle_login({"address": "second@proton.me"})
        self.assertIn("hermes proton login --user second@proton.me", answer)

    def test_accounts_tool_reports_nothing_signed_in(self) -> None:
        self.assertIn("No Proton account", tools.handle_accounts({}))

    def test_the_schema_does_not_take_a_password(self) -> None:
        """The whole point: no password-shaped parameter for a model to fill in.

        Sign-in happens in a terminal, so the tool only needs the address (and
        ``force`` to replace a session); nothing a lasting secret could ride in.
        """
        properties = tools.PROTON_LOGIN_SCHEMA["parameters"]["properties"]
        self.assertEqual(sorted(properties), ["address", "force"])
        for name in properties:
            self.assertNotIn("password", name)
            self.assertNotIn("secret", name)

    def test_login_is_offered_without_a_session(self) -> None:
        """Gating it on a session would leave no way to create one."""
        ungated = [name for name, *_ in tools.UNGATED_TOOLS]
        gated = [name for name, *_ in tools.TOOLS]
        self.assertIn("proton_login", ungated)
        self.assertNotIn("proton_login", gated)


if __name__ == "__main__":
    unittest.main()
