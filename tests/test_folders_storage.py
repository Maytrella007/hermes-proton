"""Tests for the Group 3 mail tools: storage quota, empty trash/spam, and
label/folder management (create/rename/delete)."""

from __future__ import annotations

import types
import unittest
from unittest import mock

import proton_tools as tools
from protonlite.client import ProtonMail, SYSTEM_LABELS
from protonlite.errors import ProtonError


def _bare_client(api):
    c = ProtonMail.__new__(ProtonMail)
    c.api = api
    c._user = None
    return c


class _FakeApi:
    def __init__(self, user=None):
        self.session = types.SimpleNamespace(username="me@proton.me")
        self._user = user or {}
        self.calls = []

    def get(self, path, **kw):
        self.calls.append(("GET", path, kw))
        if path == "/core/v4/users":
            return {"User": self._user}
        if path == "/core/v4/labels":
            return {"Labels": self._labels_for(kw.get("params", {}))}
        return {}

    def _labels_for(self, params):
        return []

    def delete(self, path, **kw):
        self.calls.append(("DELETE", path, kw))
        return {"Code": 1000}

    def put(self, path, **kw):
        self.calls.append(("PUT", path, kw))
        return {"Code": 1000, "Label": {"ID": "L1", "Name": kw.get("json_body", {}).get("Name", "")}}

    def post(self, path, **kw):
        self.calls.append(("POST", path, kw))
        return {"Code": 1000, "Label": {"ID": "NEW", "Name": kw.get("json_body", {}).get("Name", "")}}


# ---- storage --------------------------------------------------------------

class Storage(unittest.TestCase):
    def test_total_only(self):
        api = _FakeApi(user={"UsedSpace": 500, "MaxSpace": 1000})
        s = _bare_client(api).storage()
        self.assertEqual(s, {"used": 500, "max": 1000})

    def test_split_pools(self):
        api = _FakeApi(user={
            "UsedSpace": 3, "MaxSpace": 30,
            "MaxBaseSpace": 10, "UsedBaseSpace": 1,
            "MaxDriveSpace": 20, "UsedDriveSpace": 2,
        })
        s = _bare_client(api).storage()
        self.assertEqual(s["mail"], {"used": 1, "max": 10})
        self.assertEqual(s["drive"], {"used": 2, "max": 20})

    def test_tool_formats_bytes_and_percent(self):
        client = _bare_client(_FakeApi(user={"UsedSpace": 1500000000, "MaxSpace": 15000000000}))
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            out = tools.handle_storage({})
        self.assertIn("GB", out)
        self.assertIn("10.0%", out)

    def test_storage_is_read_and_not_gated(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_storage"], tools.TOOLSET)
        self.assertIsNone(tools.pre_tool_call_directive("proton_storage", {}))


# ---- empty trash/spam -----------------------------------------------------

class EmptyFolder(unittest.TestCase):
    def test_empty_trash_hits_the_endpoint(self):
        api = _FakeApi()
        _bare_client(api).empty_folder("trash")
        method, path, kw = api.calls[-1]
        self.assertEqual((method, path), ("DELETE", "/mail/v4/messages/empty"))
        self.assertEqual(kw["params"], {"LabelID": SYSTEM_LABELS["trash"]})

    def test_empty_spam(self):
        api = _FakeApi()
        _bare_client(api).empty_folder("spam")
        self.assertEqual(api.calls[-1][2]["params"], {"LabelID": SYSTEM_LABELS["spam"]})

    def test_refuses_other_folders(self):
        with self.assertRaises(ProtonError):
            _bare_client(_FakeApi()).empty_folder("inbox")

    def test_tool_refuses_bad_folder(self):
        self.assertIn("trash", tools.handle_empty({"folder": "inbox"}))

    def test_tool_empties(self):
        client = _bare_client(_FakeApi())
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            out = tools.handle_empty({"folder": "trash"})
        self.assertIn("Emptied Trash", out)
        self.assertIn("cannot be undone", out)


# ---- manage label/folder --------------------------------------------------

class _LabelClient:
    def __init__(self, labels=None):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self._labels = labels or []
        self.created = None
        self.updated = None
        self.deleted = None

    def list_labels(self):
        return list(self._labels)

    def create_label(self, name, **kw):
        self.created = {"name": name, **kw}
        return {"ID": "NEW", "Name": name}

    def update_label(self, lid, *, name=None, color=None):
        self.updated = {"id": lid, "name": name, "color": color}
        return {"ID": lid}

    def delete_label(self, lid):
        self.deleted = lid


class ManageLabel(unittest.TestCase):
    def _run(self, client, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_manage_label(args)

    def test_create_label(self):
        c = _LabelClient()
        out = self._run(c, {"action": "create", "name": "Work"})
        self.assertEqual(c.created["name"], "Work")
        self.assertFalse(c.created.get("folder"))
        self.assertIn("Created label 'Work'", out)

    def test_create_folder_with_color(self):
        c = _LabelClient()
        self._run(c, {"action": "create", "name": "Clients", "folder": True, "color": "#8080FF"})
        self.assertTrue(c.created["folder"])
        self.assertEqual(c.created["color"], "#8080FF")

    def test_create_refuses_duplicate(self):
        c = _LabelClient([{"ID": "L1", "Name": "Work"}])
        out = self._run(c, {"action": "create", "name": "work"})  # case-insensitive
        self.assertIn("already exists", out)
        self.assertIsNone(c.created)

    def test_rename_keeps_the_existing_colour(self):
        # Rename with no colour backfills the label's current colour, since
        # Proton's label update wants the whole object.
        c = _LabelClient([{"ID": "L1", "Name": "Work", "Color": "#111111"}])
        out = self._run(c, {"action": "rename", "name": "Work", "new_name": "Office"})
        self.assertEqual(c.updated, {"id": "L1", "name": "Office", "color": "#111111"})
        self.assertIn("renamed to 'Office'", out)

    def test_recolour_keeps_the_existing_name(self):
        c = _LabelClient([{"ID": "L1", "Name": "Work", "Color": "#111111"}])
        self._run(c, {"action": "rename", "name": "Work", "color": "#8080FF"})
        self.assertEqual(c.updated, {"id": "L1", "name": "Work", "color": "#8080FF"})

    def test_rename_needs_a_change(self):
        c = _LabelClient([{"ID": "L1", "Name": "Work"}])
        self.assertIn("new_name", self._run(c, {"action": "rename", "name": "Work"}))

    def test_delete(self):
        c = _LabelClient([{"ID": "L1", "Name": "Work"}])
        out = self._run(c, {"action": "delete", "name": "Work"})
        self.assertEqual(c.deleted, "L1")
        self.assertIn("kept", out)

    def test_unknown_name(self):
        c = _LabelClient()
        self.assertIn("No label or folder", self._run(c, {"action": "delete", "name": "Nope"}))

    def test_bad_action(self):
        self.assertIn("create", tools.handle_manage_label({"action": "frobnicate", "name": "x"}))

    def test_write_tools_not_gated(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        for w in ("proton_empty", "proton_manage_label"):
            self.assertEqual(toolset_of[w], tools.TOOLSET_WRITE)
            self.assertIsNone(tools.pre_tool_call_directive(w, {"folder": "trash", "action": "delete", "name": "x"}))


if __name__ == "__main__":
    unittest.main()
