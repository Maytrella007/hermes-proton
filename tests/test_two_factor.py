"""Tests for the second factor, with the network stubbed out.

``2FA.Enabled`` is a bitfield: 1 is a code from an app, 2 is a security key.
"""

from __future__ import annotations

import unittest

from protonlite.api import ProtonAPI, Session
from protonlite.errors import APIError, TwoFactorRequired


class _StubbedAPI(ProtonAPI):
    """A client that records calls instead of making them."""

    def __init__(self, *, reject_code: bool = False) -> None:
        super().__init__()
        self.posted: list[tuple[str, dict]] = []
        self.deleted = 0
        self._reject_code = reject_code
        self.session = Session(
            uid="uid", access_token="access", refresh_token="refresh", username="me@proton.me"
        )

    def post(self, path, **kwargs):  # type: ignore[override]
        self.posted.append((path, kwargs.get("json_body") or {}))
        if self._reject_code:
            raise APIError(422, 8002, "Incorrect login credentials")
        return {"Code": 1000}

    def request(self, method, path, **kwargs):  # type: ignore[override]
        if method == "DELETE":
            self.deleted += 1
            return {"Code": 1000}
        return {"Code": 1000}


class SecondFactor(unittest.TestCase):
    def test_a_code_is_submitted_to_the_right_endpoint(self) -> None:
        api = _StubbedAPI()
        api._settle_second_factor(1, "123456")
        self.assertEqual(api.posted, [("/auth/v4/2fa", {"TwoFactorCode": "123456"})])
        self.assertTrue(api.session.authenticated)

    def test_spaces_in_the_code_are_tolerated(self) -> None:
        api = _StubbedAPI()
        api._settle_second_factor(1, " 123 456 ")
        self.assertEqual(api.posted[0][1], {"TwoFactorCode": "123456"})

    def test_both_factors_registered_still_uses_the_code(self) -> None:
        api = _StubbedAPI()
        api._settle_second_factor(3, "654321")
        self.assertEqual(api.posted[0][0], "/auth/v4/2fa")

    def test_without_a_code_it_asks_and_drops_the_half_session(self) -> None:
        api = _StubbedAPI()
        with self.assertRaises(TwoFactorRequired) as caught:
            api._settle_second_factor(1, "")
        self.assertIn("six-digit code", str(caught.exception))
        self.assertEqual(api.posted, [])
        # A session that never opened should not be left listed as a device.
        self.assertEqual(api.deleted, 1)
        self.assertFalse(api.session.authenticated)

    def test_a_security_key_is_reported_as_unsupported(self) -> None:
        api = _StubbedAPI()
        with self.assertRaises(TwoFactorRequired) as caught:
            api._settle_second_factor(2, "123456")
        message = str(caught.exception)
        self.assertIn("security key", message)
        self.assertIn("authenticator app", message)  # points at the way out
        self.assertEqual(api.posted, [])
        self.assertEqual(api.deleted, 1)

    def test_a_rejected_code_explains_the_thirty_seconds(self) -> None:
        api = _StubbedAPI(reject_code=True)
        with self.assertRaises(TwoFactorRequired) as caught:
            api._settle_second_factor(1, "000000")
        message = str(caught.exception)
        self.assertIn("thirty seconds", message)
        self.assertIn("clock", message)  # the other classic cause
        self.assertEqual(api.deleted, 1)


if __name__ == "__main__":
    unittest.main()
