"""Tests for the sign-in tool's guard rails.

The password never reaches the agent: it is read from a one-time file and
destroyed. These check the paths that do not need a live account.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import proton_tools as tools
from protonlite.accounts import ROOT_ENV
from protonlite.errors import AuthError


class LoginGuards(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self._saved = {
            key: os.environ.get(key)
            for key in (ROOT_ENV, tools.PASSWORD_FILE_ENV)
        }
        os.environ[ROOT_ENV] = str(root)
        os.environ[tools.PASSWORD_FILE_ENV] = str(root / "login-password")

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._dir.cleanup()

    def test_address_is_required(self) -> None:
        self.assertIn("address", tools.handle_login({}).lower())

    def test_explains_how_to_leave_the_password(self) -> None:
        answer = tools.handle_login({"address": "me@proton.me"})
        self.assertIn(tools.password_file(), answer)
        self.assertIn("install -m 600", answer)
        self.assertIn("Do not ask for the password in this conversation", answer)

    def test_an_empty_password_file_is_not_a_password(self) -> None:
        Path(tools.password_file()).write_text("   \n")
        self.assertIn("No password file is waiting", tools.handle_login({"address": "me@proton.me"}))

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
        self.assertIn("No password file is waiting", answer)

    def test_a_failed_sign_in_removes_the_password_file(self) -> None:
        """A wrong password must not be left sitting in plaintext on disk."""
        drop = Path(tools.password_file())
        drop.write_text("not-the-real-password\n")
        with mock.patch.object(
            tools.ProtonMail, "login", side_effect=AuthError("rejected")
        ):
            answer = tools.handle_login({"address": "me@proton.me"})
        self.assertFalse(drop.exists(), "password file should be gone after a failure")
        self.assertIn("Sign-in failed", answer)
        self.assertIn("removed the password file", answer)

    def test_accounts_tool_reports_nothing_signed_in(self) -> None:
        self.assertIn("No Proton account", tools.handle_accounts({}))

    def test_the_schema_does_not_take_a_password(self) -> None:
        """The whole point: no password-shaped parameter for a model to fill in.

        A single authenticator code is a different matter -- it is one-use and
        worthless in a minute -- so ``totp_code`` is allowed and a lasting
        secret is not.
        """
        properties = tools.PROTON_LOGIN_SCHEMA["parameters"]["properties"]
        self.assertEqual(
            sorted(properties),
            ["address", "force", "totp_code", "verification_token"],
        )
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
