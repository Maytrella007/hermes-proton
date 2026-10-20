"""Tests for the label tools: listing, and adding/removing by name.

Names resolve to ids three ways -- a system mailbox, an existing custom label,
or (only for an add with create=true) a label made on the spot. An unknown
name is reported, never guessed.
"""

from __future__ import annotations

import types
import unittest
from unittest import mock

import proton_tools as tools


class _FakeClient:
    """A mailbox with two custom labels and a folder, recording label calls."""

    def __init__(self) -> None:
        self.api = types.SimpleNamespace(
            session=types.SimpleNamespace(username="me@proton.me")
        )
        self._labels = [
            {"ID": "L1", "Name": "Work", "Type": 1},
            {"ID": "L2", "Name": "Facturas", "Type": 1},
            {"ID": "F1", "Name": "Clientes", "Type": 3},
        ]
        self.applied: list[tuple[str, list[str]]] = []
        self.removed: list[tuple[str, list[str]]] = []
        self.created: list[str] = []

    def list_labels(self):
        return list(self._labels)

    def apply_label(self, label_id, ids):
        self.applied.append((label_id, list(ids)))
        return len(list(ids))

    def remove_label(self, label_id, ids):
        self.removed.append((label_id, list(ids)))
        return len(list(ids))

    def create_label(self, name, **_kw):
        self.created.append(name)
        new = {"ID": "NEW", "Name": name, "Type": 1}
        self._labels.append(new)
        return new


class LabelListing(unittest.TestCase):
    def _run(self, client):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_labels({})

    def test_lists_labels_and_folders_apart(self):
        out = self._run(_FakeClient())
        self.assertIn("Labels: Facturas, Work", out)  # sorted, case-insensitive
        self.assertIn("Folders: Clientes", out)

    def test_empty_account_names_the_system_mailboxes(self):
        client = _FakeClient()
        client._labels = []
        out = self._run(client)
        self.assertIn("archive", out)
        self.assertIn("inbox", out)


class LabelApply(unittest.TestCase):
    def setUp(self):
        self.client = _FakeClient()

    def _run(self, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_label({"ids": ["m1", "m2"], **args})

    def test_requires_ids(self):
        self.assertIn("message id", tools.handle_label({"add": ["Work"]}))

    def test_requires_something_to_do(self):
        self.assertIn("add or remove", self._run({}))

    def test_adds_an_existing_label_by_name(self):
        out = self._run({"add": ["Work"]})
        self.assertEqual(self.client.applied, [("L1", ["m1", "m2"])])
        self.assertIn("added 'work'", out.lower())

    def test_label_name_casing_is_kept_in_the_answer(self):
        out = self._run({"add": ["Work"]})
        self.assertIn("Work", out)       # not lowercased to "work"
        self.assertTrue(out[0].isupper())  # but the sentence still starts capital

    def test_a_system_name_resolves_to_its_fixed_id(self):
        self._run({"add": ["archive"]})
        self.assertEqual(self.client.applied[0][0], tools.SYSTEM_LABELS["archive"])

    def test_removes_a_label(self):
        self._run({"remove": ["Facturas"]})
        self.assertEqual(self.client.removed, [("L2", ["m1", "m2"])])

    def test_unknown_label_is_reported_not_guessed(self):
        out = self._run({"add": ["Nope"]})
        self.assertIn("Unknown label", out)
        self.assertEqual(self.client.applied, [])  # nothing touched
        self.assertEqual(self.client.created, [])

    def test_create_makes_a_missing_label(self):
        out = self._run({"add": ["Proyectos"], "create": True})
        self.assertEqual(self.client.created, ["Proyectos"])
        self.assertEqual(self.client.applied[0][0], "NEW")
        self.assertIn("created new label", out.lower())

    def test_remove_never_creates(self):
        out = self._run({"remove": ["Ghost"], "create": True})
        self.assertIn("Unknown label", out)
        self.assertEqual(self.client.created, [])


class LabelToolsetSplit(unittest.TestCase):
    def test_listing_reads_and_changing_writes(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_labels"], tools.TOOLSET)       # reading
        self.assertEqual(toolset_of["proton_label"], tools.TOOLSET_WRITE)  # mutation

    def test_label_change_is_not_gated_for_approval(self):
        # The human approval gate is for sending only; labelling is reversible.
        self.assertIsNone(tools.pre_tool_call_directive("proton_label", {"ids": ["m1"]}))


if __name__ == "__main__":
    unittest.main()
