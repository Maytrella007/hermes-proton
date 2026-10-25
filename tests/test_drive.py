"""Tests for the Proton Drive read tools (crypto tree verified live, not here)."""

from __future__ import annotations

import os
import tempfile
import types
from pathlib import Path
import unittest
from unittest import mock

import proton_tools as tools


class _FakeDrive:
    def __init__(self, entries=None, download=None):
        self._entries = entries
        self._download = download
        self.calls = {}

    def list_folder(self, path):
        if self._entries is None:
            from protonlite.errors import ProtonError

            raise ProtonError("this account has no Proton Drive")
        return self._entries

    def download(self, path, *, size_limit=0):
        return self._download

    def create_folder(self, parent, name):
        self.calls["create_folder"] = (parent, name)
        return "NEWFOLDER"

    def trash(self, path):
        self.calls["trash"] = path
        return path.split("/")[-1]

    def move(self, path, to):
        self.calls["move"] = (path, to)
        return "MOVEDID"

    def upload(self, folder, name, data, mime):
        self.calls["upload"] = (folder, name, len(data), mime)
        return "UPLOADEDID"

    def rename(self, path, new_name):
        self.calls["rename"] = (path, new_name)
        return "RENAMEDID"

    def share_link(self, path):
        self.calls["share"] = path
        return {
            "url": "https://drive.proton.me/urls/ABC123#secretpass12",
            "token": "ABC123",
            "password": "secretpass12",
            "share_id": "SHARE1",
            "share_url_id": "URL1",
        }

    def unshare_link(self, path):
        self.calls["unshare"] = path
        return self._shared

    _shared = True


class _DriveClient:
    def __init__(self, reader):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self._reader = reader

    def drive(self):
        return self._reader


def _run(handler, reader, args):
    with mock.patch.object(tools.ProtonMail, "for_account", return_value=_DriveClient(reader)):
        return handler(args)


class DriveList(unittest.TestCase):
    def test_lists_folders_first_and_fences(self):
        entries = [
            {"name": "Report.pdf", "type": "file", "size": 1234, "mime": "application/pdf"},
            {"name": "Work", "type": "folder", "size": 0, "mime": ""},
        ]
        out = _run(tools.handle_drive_list, _FakeDrive(entries), {})
        self.assertIn("[folder] Work/", out)
        self.assertIn("Report.pdf (1,234 bytes, application/pdf)", out)
        self.assertIn("begin email content", out)  # untrusted fence
        self.assertTrue(out.startswith("Account: me@proton.me"))

    def test_empty_folder(self):
        out = _run(tools.handle_drive_list, _FakeDrive([]), {"path": "Work"})
        self.assertIn("is empty", out)
        self.assertIn("'Work'", out)

    def test_no_drive_is_reported(self):
        out = _run(tools.handle_drive_list, _FakeDrive(None), {})
        self.assertIn("no Proton Drive", out)


class DriveDownload(unittest.TestCase):
    def test_requires_a_path(self):
        self.assertIn("path", tools.handle_drive_download({}))

    def test_downloads_to_a_local_file(self):
        reader = _FakeDrive(download=("notes.txt", "text/plain", b"hola mundo"))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(tools, "default_root", return_value=d):
                out = _run(tools.handle_drive_download, reader, {"path": "Docs/notes.txt"})
            self.assertIn("Downloaded notes.txt", out)
            self.assertIn("hola mundo", out)  # small text file is fenced inline
            saved = os.path.join(d, "drive", "notes.txt")
            self.assertTrue(os.path.isfile(saved))
            self.assertEqual(open(saved, "rb").read(), b"hola mundo")

    def test_binary_is_saved_not_inlined(self):
        reader = _FakeDrive(download=("photo.heic", "image/heic", b"\x00\x00\x00\x18ftypheic"))
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(tools, "default_root", return_value=d):
                out = _run(tools.handle_drive_download, reader, {"path": "photo.heic"})
            self.assertIn("Downloaded photo.heic", out)
            self.assertNotIn("begin email content", out)  # binary not inlined


class DriveWrite(unittest.TestCase):
    def _run(self, handler, args):
        self.drive = _FakeDrive(entries=[])
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=_DriveClient(self.drive)):
            return handler(args)

    def test_create_folder(self):
        out = self._run(tools.handle_drive_create_folder, {"parent": "Work", "name": "Reports"})
        self.assertEqual(self.drive.calls["create_folder"], ("Work", "Reports"))
        self.assertIn('Created folder "Reports"', out)

    def test_create_folder_needs_name(self):
        self.assertIn("name", tools.handle_drive_create_folder({}))

    def test_move(self):
        out = self._run(tools.handle_drive_move, {"path": "a/x.pdf", "to": "b"})
        self.assertEqual(self.drive.calls["move"], ("a/x.pdf", "b"))
        self.assertIn("Moved 'x.pdf' to 'b'", out)

    def test_delete_trashes(self):
        out = self._run(tools.handle_drive_delete, {"path": "a/old.pdf"})
        self.assertEqual(self.drive.calls["trash"], "a/old.pdf")
        self.assertIn("trash", out.lower())

    def test_upload_reads_local_file(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello drive")
            local = f.name
        try:
            out = self._run(tools.handle_drive_upload, {"local_path": local, "folder": "Docs"})
        finally:
            os.unlink(local)
        folder, name, size, mime = self.drive.calls["upload"]
        self.assertEqual(folder, "Docs")
        self.assertEqual(size, len(b"hello drive"))
        self.assertIn("Uploaded", out)

    def test_upload_missing_file(self):
        self.assertIn("not found", self._run(tools.handle_drive_upload, {"local_path": "/no/such/file.xyz"}))

    def test_rename(self):
        out = self._run(tools.handle_drive_rename, {"path": "a/old.txt", "new_name": "new.txt"})
        self.assertEqual(self.drive.calls["rename"], ("a/old.txt", "new.txt"))
        self.assertIn("Renamed", out)

    def test_rename_needs_both(self):
        self.assertIn("new_name", tools.handle_drive_rename({"path": "a"}))

    def test_share_returns_the_public_url(self):
        out = self._run(tools.handle_drive_share, {"path": "Work/report.pdf"})
        self.assertEqual(self.drive.calls["share"], "Work/report.pdf")
        self.assertIn("https://drive.proton.me/urls/ABC123#secretpass12", out)
        self.assertIn("secret", out.lower())

    def test_share_needs_a_path(self):
        self.assertIn("path", tools.handle_drive_share({}))

    def test_unshare_revokes(self):
        out = self._run(tools.handle_drive_unshare, {"path": "Work/report.pdf"})
        self.assertEqual(self.drive.calls["unshare"], "Work/report.pdf")
        self.assertIn("Revoked", out)

    def test_unshare_when_not_shared(self):
        self.drive = _FakeDrive(entries=[])
        self.drive._shared = False
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=_DriveClient(self.drive)):
            out = tools.handle_drive_unshare({"path": "x.pdf"})
        self.assertIn("not shared", out)

    def test_share_is_gated_unshare_is_not(self):
        d = tools.pre_tool_call_directive("proton_drive_share", {"path": "a/b.pdf"})
        self.assertEqual(d["action"], "approve")
        self.assertIn("PUBLIC", d["message"])
        self.assertIn("a/b.pdf", d["message"])
        self.assertIsNone(tools.pre_tool_call_directive("proton_drive_unshare", {"path": "a/b.pdf"}))


class LinkShareId(unittest.TestCase):
    """_link_share_id must read both shapes of SharingDetails and treat an
    unshared link as empty (so share_link's already-shared guard works)."""

    def _reader(self):
        from protonlite.drive import DriveReader

        return DriveReader.__new__(DriveReader)

    def test_top_level_share_id(self):
        r = self._reader()
        self.assertEqual(r._link_share_id({"SharingDetails": {"ShareID": "S1"}}), "S1")

    def test_nested_under_share_url(self):
        r = self._reader()
        self.assertEqual(r._link_share_id({"SharingDetails": {"ShareUrl": {"ShareID": "S2"}}}), "S2")

    def test_not_shared_is_empty(self):
        r = self._reader()
        self.assertEqual(r._link_share_id({}), "")
        self.assertEqual(r._link_share_id({"SharingDetails": None}), "")


class DriveToolset(unittest.TestCase):
    def test_reading_and_not_gated(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_drive_list"], tools.TOOLSET)
        self.assertEqual(toolset_of["proton_drive_download"], tools.TOOLSET)
        # Recoverable writes are not gated: Proton's own trash keeps a trashed
        # item, and a move or a rename can be moved or renamed back. Asking
        # about those teaches a person to click through the prompts that do
        # matter.
        for w in ("proton_drive_create_folder", "proton_drive_move", "proton_drive_delete",
                  "proton_drive_rename", "proton_drive_unshare"):
            self.assertEqual(toolset_of[w], tools.TOOLSET_WRITE)
            self.assertIsNone(tools.pre_tool_call_directive(w, {"path": "x", "name": "y"}))
        self.assertEqual(toolset_of["proton_drive_share"], tools.TOOLSET_WRITE)  # gated, see DriveWrite
        self.assertEqual(toolset_of["proton_drive_upload"], tools.TOOLSET_WRITE)  # gated, below
        self.assertIsNone(tools.pre_tool_call_directive("proton_drive_list", {}))
        self.assertIsNone(tools.pre_tool_call_directive("proton_drive_download", {"path": "x"}))


class DriveUploadApproval(unittest.TestCase):
    """An upload reads a local file, so a person is shown which one.

    It read any path with no approval at all, and the prompt that came after
    it -- the share link -- shows only the Drive name, which the model chose.
    A secret uploaded as "report.pdf" looked like a report everywhere a person
    was asked anything.
    """

    def test_the_prompt_shows_the_resolved_local_path_and_the_destination(self):
        d = tools.pre_tool_call_directive(
            "proton_drive_upload",
            {"local_path": "~/.ssh/id_rsa", "name": "report.pdf", "folder": "Shared"},
        )
        self.assertEqual(d["action"], "approve")
        self.assertIn(str(Path("~/.ssh/id_rsa").expanduser().resolve()), d["message"])
        self.assertIn("Shared/report.pdf", d["message"])

    def test_always_is_per_file_and_per_destination(self):
        first = tools.pre_tool_call_directive("proton_drive_upload", {"local_path": "/tmp/a.pdf"})
        other = tools.pre_tool_call_directive("proton_drive_upload", {"local_path": "/tmp/b.pdf"})
        renamed = tools.pre_tool_call_directive(
            "proton_drive_upload", {"local_path": "/tmp/a.pdf", "name": "elsewhere.pdf"})
        self.assertNotEqual(first["rule_key"], other["rule_key"])
        self.assertNotEqual(first["rule_key"], renamed["rule_key"])


if __name__ == "__main__":
    unittest.main()
