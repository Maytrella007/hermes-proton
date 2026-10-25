"""Tests for the delete tool and the send tool's bcc parameter."""

from __future__ import annotations

import inspect
import unittest

import proton_tools as tools
from protonlite.client import ProtonMail


class DeleteTool(unittest.TestCase):
    def test_registered(self) -> None:
        names = [name for name, *_ in tools.TOOLS]
        self.assertIn("proton_delete", names)

    def test_schema_requires_ids(self) -> None:
        schema = tools.PROTON_DELETE_SCHEMA
        self.assertEqual(schema["name"], "proton_delete")
        self.assertIn("ids", schema["parameters"]["properties"])
        self.assertEqual(schema["parameters"]["required"], ["ids"])
        self.assertIn("permanent", schema["parameters"]["properties"])

    def test_empty_ids_is_reported(self) -> None:
        self.assertEqual(
            tools.handle_delete({"ids": []}), "At least one message id is required."
        )
        self.assertEqual(
            tools.handle_delete({"ids": ["  "]}), "At least one message id is required."
        )

    def test_client_has_trash_and_permanent_delete(self) -> None:
        self.assertTrue(hasattr(ProtonMail, "trash"))
        self.assertTrue(hasattr(ProtonMail, "delete_permanently"))


class BatchResponse(unittest.TestCase):
    def test_counts_only_ids_proton_acted_on(self) -> None:
        payload = {"Code": 1001, "Responses": [
            {"Response": {"Code": 1000}},
            {"Response": {"Code": 2061}},
            {"Response": {"Code": 1000}},
        ]}
        self.assertEqual(ProtonMail._batch_ok(payload, 3), 2)

    def test_plain_ok_has_no_list(self) -> None:
        self.assertEqual(ProtonMail._batch_ok({"Code": 1000}, 4), 4)


class SendBcc(unittest.TestCase):
    def test_send_schema_exposes_bcc(self) -> None:
        self.assertIn("bcc", tools.PROTON_SEND_SCHEMA["parameters"]["properties"])

    def test_client_send_accepts_bcc(self) -> None:
        self.assertIn("bcc", inspect.signature(ProtonMail.send).parameters)


if __name__ == "__main__":
    unittest.main()


class IrreversibleDeletesAreApproved(unittest.TestCase):
    """Trash is recoverable and is not gated; "for good" is gated.

    The review that asked for this put it plainly: the irreversible ones are
    the ones worth a prompt. Gating the recoverable ones as well would teach a
    person to click through every prompt, including the ones that matter.
    """

    def test_a_move_to_trash_is_not_gated(self):
        self.assertIsNone(tools.pre_tool_call_directive("proton_delete", {"ids": ["a", "b"]}))

    def test_a_permanent_delete_is_gated_and_says_so(self):
        asked = tools.pre_tool_call_directive(
            "proton_delete", {"ids": ["a", "b"], "permanent": True})
        self.assertEqual(asked["action"], "approve")
        self.assertIn("PERMANENTLY", asked["message"])
        self.assertIn("a", asked["message"])

    def test_deleting_a_contact_is_gated(self):
        asked = tools.pre_tool_call_directive("proton_delete_contact", {"name": "Ana"})
        self.assertEqual(asked["action"], "approve")
        self.assertIn("Ana", asked["message"])
        self.assertIn("no trash", asked["message"])
