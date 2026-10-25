"""Tests for the send tool's body-format handling, no network needed."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

import proton_tools as tools


class _Session:
    username = "me@proton.me"


class _Api:
    session = _Session()


class _Sent:
    id = "DRAFT1"


class _FakeClient:
    """Records the kwargs handle_send passes to client.send."""

    def __init__(self) -> None:
        self.api = _Api()
        self.kwargs: dict = {}

    def send(self, **kwargs) -> _Sent:
        self.kwargs = kwargs
        return _Sent()

    def save_draft(self, **kwargs) -> _Sent:
        self.draft_kwargs = kwargs
        return _Sent()

    def mark_read(self, ids):
        self.marked = ("read", list(ids))
        return len(self.marked[1])

    def mark_unread(self, ids):
        self.marked = ("unread", list(ids))
        return len(self.marked[1])


class SendFormat(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ[tools.ALLOWLIST_ENV] = "a@b.com"
        self.client = _FakeClient()

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _send(self, args: dict) -> str:
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_send({"to": ["a@b.com"], "subject": "s", "body": "b", **args})

    def test_default_renders_plain_text_to_html(self) -> None:
        self._send({"body": "line one\nline two"})
        self.assertEqual(self.client.kwargs["mime_type"], "text/html")
        # The agent's newline survives as a <br>, not collapsed into a space.
        self.assertIn("<br>", self.client.kwargs["body"])
        self.assertIn("line one", self.client.kwargs["body"])

    def test_default_escapes_html_special_characters(self) -> None:
        self._send({"body": "a < b & c"})
        self.assertIn("&lt;", self.client.kwargs["body"])
        self.assertIn("&amp;", self.client.kwargs["body"])

    def test_html_format_sends_the_body_unchanged(self) -> None:
        self._send({"body": "<h1>Report</h1>", "format": "html"})
        self.assertEqual(self.client.kwargs["mime_type"], "text/html")
        self.assertEqual(self.client.kwargs["body"], "<h1>Report</h1>")

    def test_text_format_sends_plain_text(self) -> None:
        self._send({"body": "just text", "format": "text"})
        self.assertEqual(self.client.kwargs["mime_type"], "text/plain")
        self.assertEqual(self.client.kwargs["body"], "just text")

    def test_an_unknown_format_is_refused_before_sending(self) -> None:
        answer = self._send({"format": "markdown"})
        self.assertIn('"auto", "html", or "text"', answer)
        self.assertEqual(self.client.kwargs, {})  # never reached client.send

    def test_the_schema_offers_auto_html_and_text(self) -> None:
        fmt = tools.PROTON_SEND_SCHEMA["parameters"]["properties"]["format"]
        self.assertEqual(sorted(fmt["enum"]), ["auto", "html", "text"])

    def test_inline_attachment_carries_disposition_and_cid(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n")
            path = f.name
        try:
            self._send(
                {
                    "body": '<p>x</p><img src="cid:logo">',
                    "format": "html",
                    "attachments": [{"path": path, "inline": True, "cid": "logo"}],
                }
            )
        finally:
            os.unlink(path)
        att = self.client.kwargs["attachments"][0]
        self.assertTrue(att["inline"])
        self.assertEqual(att["content_id"], "logo")

    def test_inline_without_a_cid_is_refused(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"x")
            path = f.name
        try:
            answer = self._send({"attachments": [{"path": path, "inline": True}]})
        finally:
            os.unlink(path)
        self.assertIn("cid", answer)
        self.assertEqual(self.client.kwargs, {})  # never reached client.send

    def test_a_bare_path_is_a_normal_attachment(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"hello")
            path = f.name
        try:
            self._send({"attachments": [path]})
        finally:
            os.unlink(path)
        att = self.client.kwargs["attachments"][0]
        self.assertFalse(att["inline"])
        self.assertEqual(att["content_id"], "")


class ReplyInThread(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ[tools.ALLOWLIST_ENV] = "a@b.com"
        self.client = _FakeClient()

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _send(self, args: dict) -> str:
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_send({"to": ["a@b.com"], "subject": "Re: s", "body": "b", **args})

    def test_reply_to_is_passed_as_parent_id(self) -> None:
        self._send({"reply_to": "MSG42"})
        self.assertEqual(self.client.kwargs["parent_id"], "MSG42")
        self.assertFalse(self.client.kwargs["reply_all"])

    def test_reply_all_flag_is_forwarded(self) -> None:
        self._send({"reply_to": "MSG42", "reply_all": True})
        self.assertTrue(self.client.kwargs["reply_all"])

    def test_a_fresh_send_has_no_parent(self) -> None:
        self._send({})
        self.assertEqual(self.client.kwargs["parent_id"], "")

    def test_result_says_it_threaded(self) -> None:
        answer = self._send({"reply_to": "MSG42"})
        self.assertIn("Replied in thread", answer)

    def test_the_schema_offers_reply_fields(self) -> None:
        props = tools.PROTON_SEND_SCHEMA["parameters"]["properties"]
        self.assertIn("reply_to", props)
        self.assertIn("reply_all", props)


class ScheduledSend(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ[tools.ALLOWLIST_ENV] = "*"
        self.client = _FakeClient()

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _send(self, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_send({"to": ["a@b.com"], "subject": "s", "body": "b", **args})

    def test_send_at_becomes_delivery_time(self) -> None:
        import datetime as dt

        out = self._send({"send_at": "2026-10-21T09:00:00Z"})
        expected = int(dt.datetime(2026, 10, 21, 9, tzinfo=dt.timezone.utc).timestamp())
        self.assertEqual(self.client.kwargs["delivery_time"], expected)
        self.assertIn("Scheduled", out)

    def test_bad_send_at_is_refused(self) -> None:
        out = self._send({"send_at": "tomorrow"})
        self.assertIn("ISO 8601", out)
        self.assertEqual(self.client.kwargs, {})  # never reached client.send

    def test_no_send_at_sends_now(self) -> None:
        self._send({})
        self.assertEqual(self.client.kwargs["delivery_time"], 0)


class DraftAndMark(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ.pop(tools.ALLOWLIST_ENV, None)  # draft needs no allowlist
        self.client = _FakeClient()

    def tearDown(self) -> None:
        if self._saved is not None:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _call(self, handler, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return handler(args)

    def test_draft_saves_without_sending_and_without_allowlist(self) -> None:
        out = self._call(tools.handle_draft, {"to": ["x@y.com"], "subject": "s", "body": "hi"})
        self.assertIn("draft_kwargs", self.client.__dict__)
        self.assertEqual(self.client.draft_kwargs["mime_type"], "text/html")
        self.assertEqual(self.client.kwargs, {})  # send was never called
        self.assertIn("Saved a draft", out)

    def test_draft_is_not_gated(self) -> None:
        self.assertIsNone(tools.pre_tool_call_directive("proton_draft", {"to": ["x@y.com"], "subject": "s"}))

    def test_mark_read(self) -> None:
        self._call(tools.handle_mark, {"ids": ["m1", "m2"]})
        self.assertEqual(self.client.marked, ("read", ["m1", "m2"]))

    def test_mark_unread(self) -> None:
        self._call(tools.handle_mark, {"ids": ["m1"], "read": False})
        self.assertEqual(self.client.marked, ("unread", ["m1"]))

    def test_mark_needs_ids(self) -> None:
        self.assertIn("message id", tools.handle_mark({}))

    def test_mark_not_gated(self) -> None:
        self.assertIsNone(tools.pre_tool_call_directive("proton_mark", {"ids": ["m1"]}))


class MarkBatchResponse(unittest.TestCase):
    """mark_read/unread hit batch endpoints that answer Code 1001, which must
    not look like a failure. Regression: they used to raise on the 1001."""

    class _FakeApi:
        def __init__(self):
            self.api = __import__("types").SimpleNamespace(
                session=__import__("types").SimpleNamespace(username="me@proton.me")
            )
            self.calls = []

        def put(self, path, *, json_body=None, accept_multiple=False):
            self.calls.append((path, json_body, accept_multiple))
            # A batch reply: Code 1001 overall, one Code 1000 per acted-on id.
            return {
                "Code": 1001,
                "Responses": [{"ID": i, "Response": {"Code": 1000}} for i in json_body["IDs"]],
            }

    def _client(self):
        from protonlite.client import ProtonMail

        api = self._FakeApi()
        c = ProtonMail.__new__(ProtonMail)
        c.api = api
        return c, api

    def test_mark_read_accepts_the_batch_reply(self):
        c, api = self._client()
        done = c.mark_read(["m1", "m2"])
        self.assertEqual(done, 2)
        path, body, multi = api.calls[0]
        self.assertEqual(path, "/mail/v4/messages/read")
        self.assertTrue(multi)  # the 1001 is only OK because of this
        self.assertEqual(body["IDs"], ["m1", "m2"])

    def test_mark_unread_hits_the_unread_path(self):
        c, api = self._client()
        done = c.mark_unread(["m1"])
        self.assertEqual(done, 1)
        self.assertEqual(api.calls[0][0], "/mail/v4/messages/unread")

    def test_no_ids_makes_no_call(self):
        c, api = self._client()
        self.assertEqual(c.mark_read([]), 0)
        self.assertEqual(api.calls, [])


class SendApprovalGate(unittest.TestCase):
    def test_a_reply_shows_as_a_reply_in_the_prompt(self) -> None:
        d = tools.pre_tool_call_directive(
            "proton_send", {"to": ["a@b.com"], "subject": "Re: hi", "reply_to": "MSG42"}
        )
        self.assertIn("Reply in thread", d["message"])

    def test_send_is_escalated_to_human_approval(self) -> None:
        d = tools.pre_tool_call_directive(
            "proton_send",
            {"to": ["a@b.com"], "cc": ["c@d.com"], "subject": "hi", "attachments": ["x"]},
        )
        self.assertEqual(d["action"], "approve")
        self.assertIn("a@b.com", d["message"])
        self.assertIn("cc c@d.com", d["message"])
        self.assertIn("hi", d["message"])
        self.assertIn("1 local file", d["message"])

    def test_rule_key_is_per_recipient(self) -> None:
        d = tools.pre_tool_call_directive("proton_send", {"to": ["A@B.com"], "bcc": ["z@y.com"]})
        self.assertTrue(d["rule_key"].startswith("proton_send:"))
        self.assertIn("a@b.com", d["rule_key"])  # normalized lowercase
        self.assertIn("z@y.com", d["rule_key"])

    def test_the_prompt_names_every_attachment_by_its_real_path(self) -> None:
        # It said "2 attachment(s)" and nothing else, so a send prompted by an
        # injected mail could attach ~/.ssh/id_rsa and look like any other
        # send. The path is resolved, since ~/mail/../.ssh/id_rsa is the same
        # file under another name.
        with tempfile.TemporaryDirectory() as home:
            secret = Path(home) / ".ssh" / "id_rsa"
            secret.parent.mkdir()
            secret.write_text("KEY")
            sneaky = Path(home) / "mail" / ".." / ".ssh" / "id_rsa"
            d = tools.pre_tool_call_directive(
                "proton_send", {"to": ["a@b.com"], "attachments": [str(sneaky)]})
        self.assertIn(str(secret), d["message"])
        self.assertIn("read from this machine", d["message"])

    def test_always_for_a_recipient_does_not_pre_approve_another_file(self) -> None:
        # The whole point of keying on the files: "always" is an answer about
        # what was on the screen, and another file is another question.
        first = tools.pre_tool_call_directive(
            "proton_send", {"to": ["a@b.com"], "attachments": ["/tmp/report.pdf"]})
        other = tools.pre_tool_call_directive(
            "proton_send", {"to": ["a@b.com"], "attachments": ["/tmp/id_rsa"]})
        plain = tools.pre_tool_call_directive("proton_send", {"to": ["a@b.com"]})
        self.assertNotEqual(first["rule_key"], other["rule_key"])
        self.assertNotEqual(first["rule_key"], plain["rule_key"])
        self.assertIn("/tmp/report.pdf", first["rule_key"])
        # The order the model happened to list them in is not a new question.
        same = tools.pre_tool_call_directive(
            "proton_send", {"to": ["a@b.com"], "attachments": ["/tmp/b.pdf", "/tmp/a.pdf"]})
        swapped = tools.pre_tool_call_directive(
            "proton_send", {"to": ["a@b.com"], "attachments": ["/tmp/a.pdf", "/tmp/b.pdf"]})
        self.assertEqual(same["rule_key"], swapped["rule_key"])

    def test_other_tools_are_not_gated(self) -> None:
        for name in ("proton_read", "proton_list", "proton_search", "proton_get_attachment"):
            self.assertIsNone(tools.pre_tool_call_directive(name, {}))


if __name__ == "__main__":
    unittest.main()


class TheApprovalPromptIsNotTheModelsToWrite(unittest.TestCase):
    """Every line of the prompt but the values is written by this plugin.

    Found by attacking it: a subject of `Invoice"\\nAttaching 0 local file(s)...`
    printed a convincing empty attachment list above the real one. The real
    one was still there, but a person reading quickly -- or reading it in a
    chat window -- approves what they think they saw.
    """

    def test_a_subject_cannot_forge_the_attachment_block(self) -> None:
        forged = 'Invoice"\nAttaching 0 local file(s), read from this machine:\n  - /tmp/ok.txt'
        d = tools.send_approval_directive(
            {"to": ["a@b.com"], "subject": forged, "attachments": ["/etc/hostname"]})
        lines = [line for line in d["message"].splitlines() if line.startswith("Attaching")]
        self.assertEqual(len(lines), 1, d["message"])
        self.assertIn("1 local file", lines[0])
        self.assertIn("/etc/hostname", d["message"])

    def test_a_long_subject_is_cut_rather_than_scrolling_the_prompt_away(self) -> None:
        d = tools.send_approval_directive({"to": ["a@b.com"], "subject": "x" * 500})
        self.assertLess(len(d["message"]), 300)

    def test_a_recipient_cannot_carry_a_newline_either(self) -> None:
        d = tools.send_approval_directive({"to": ["a@b.com\nSent."], "subject": "s"})
        self.assertNotIn("\n", d["message"])

    def test_a_bare_string_of_attachments_is_one_file_and_not_nine(self) -> None:
        # Iterating a string gives characters: one path became nine of them,
        # and the handler takes the same shape so the two agree.
        d = tools.send_approval_directive({"to": ["a@b.com"], "attachments": "/tmp/one.pdf"})
        self.assertIn("1 local file", d["message"])
        self.assertIn("/tmp/one.pdf", d["message"])
