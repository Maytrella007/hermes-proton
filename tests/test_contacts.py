"""Tests for Proton Contacts: vCard parsing, decryption merge, the tools."""

from __future__ import annotations

import types
import unittest
from unittest import mock

import proton_tools as tools
from protonlite import contacts as ct


VCARD_CLEAR = (
    "BEGIN:VCARD\r\nVERSION:4.0\r\n"
    "FN:Ana López\r\n"
    "item1.EMAIL;PREF=1:ana@example.com\r\n"
    "item2.EMAIL:ana.work@acme.com\r\n"
    "TEL;TYPE=cell:+1 555 0100\r\n"
    "ORG:Acme Inc;Sales\r\n"
    "TITLE:Manager\r\n"
    "END:VCARD\r\n"
)


class VcardParsing(unittest.TestCase):
    def test_pulls_name_emails_phone_org(self):
        f = ct.parse_vcard(VCARD_CLEAR)
        self.assertEqual(f["name"], "Ana López")
        self.assertEqual(f["emails"], ["ana@example.com", "ana.work@acme.com"])
        self.assertEqual(f["phones"], ["+1 555 0100"])
        self.assertEqual(f["org"], "Acme Inc Sales")
        self.assertEqual(f["title"], "Manager")

    def test_ignores_begin_end_and_blank_values(self):
        f = ct.parse_vcard("BEGIN:VCARD\nFN:\nEMAIL:x@y.com\nEND:VCARD\n")
        self.assertNotIn("name", f)
        self.assertEqual(f["emails"], ["x@y.com"])


class ReadContact(unittest.TestCase):
    def test_merges_clear_and_encrypted_cards(self):
        raw = {
            "ID": "C1",
            "Name": "Ana",
            "Cards": [
                {"Type": 2, "Data": VCARD_CLEAR, "Signature": "s"},
                {"Type": 3, "Data": "<enc>", "Signature": "s"},
            ],
        }
        enc_vcard = "BEGIN:VCARD\nNOTE:private note\nTEL:+1 555 0199\nEND:VCARD\n"
        with mock.patch.object(ct.crypto, "decrypt_text", return_value=enc_vcard):
            c = ct.read_contact(raw, ["userkey"])
        self.assertEqual(c.name, "Ana López")
        self.assertIn("ana@example.com", c.emails)
        self.assertIn("+1 555 0199", c.phones)  # from the encrypted card
        self.assertEqual(c.note, "private note")

    def test_a_card_that_will_not_decrypt_is_skipped(self):
        from protonlite.errors import ProtonError

        raw = {"ID": "C1", "Name": "Ana", "Cards": [{"Type": 1, "Data": "x", "Signature": None}]}
        with mock.patch.object(ct.crypto, "decrypt_text", side_effect=ProtonError("no")):
            c = ct.read_contact(raw, ["k"])
        self.assertEqual(c.name, "Ana")  # fell back to the list name, no crash


class _ContactsClient:
    def __init__(self, rows, details=None):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self._rows = rows
        self._details = details or {}

    def list_contact_emails(self):
        return list(self._rows)

    def get_contact(self, cid):
        return self._details[cid]


class ContactsTool(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "Ana López", "email": "ana@example.com", "contact_id": "C1"},
            {"name": "Bob", "email": "bob@acme.com", "contact_id": "C2"},
            {"name": "contacto@inco.com", "email": "person@example.net", "contact_id": "C3"},
        ]

    def _run(self, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=_ContactsClient(self.rows)):
            return tools.handle_contacts(args)

    def test_lists_all_and_fences(self):
        out = self._run({})
        self.assertIn("ana@example.com", out)
        self.assertIn("Bob <bob@acme.com>", out)
        self.assertIn("begin email content", out)  # untrusted fence

    def test_query_filters_by_name_or_email(self):
        self.assertIn("person@example.net", self._run({"query": "inco"}))  # name match
        out = self._run({"query": "acme"})
        self.assertIn("bob@acme.com", out)
        self.assertNotIn("ana@example.com", out)

    def test_no_match(self):
        self.assertIn("No contacts matching", self._run({"query": "zzz"}))


class ContactDetailTool(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "Ana López", "email": "ana@example.com", "contact_id": "C1"},
            {"name": "Ana Ruiz", "email": "ana2@example.com", "contact_id": "C9"},
            {"name": "Bob", "email": "bob@acme.com", "contact_id": "C2"},
        ]
        self.detail = ct.Contact(id="C2", name="Bob", emails=["bob@acme.com"], phones=["+1"], org="Acme")

    def _run(self, args):
        client = _ContactsClient(self.rows, {"C2": self.detail})
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_contact(args)

    def test_by_id_shows_details(self):
        out = self._run({"contact_id": "C2"})
        self.assertIn("Name: Bob", out)
        self.assertIn("Emails: bob@acme.com", out)
        self.assertIn("Org: Acme", out)

    def test_by_unique_name(self):
        out = self._run({"name": "Bob"})
        self.assertIn("Name: Bob", out)

    def test_ambiguous_name_is_refused(self):
        out = self._run({"name": "Ana"})
        self.assertIn("More than one contact matches", out)

    def test_unknown_name(self):
        self.assertIn("No contact matching", self._run({"name": "Zoltan"}))

    def test_needs_id_or_name(self):
        self.assertIn("contact_id", self._run({}))


class VcardBuilding(unittest.TestCase):
    def test_split_signed_has_name_email_private_has_the_rest(self):
        signed, private = ct.build_contact_cards(
            name="Ana, Jr", emails=["a@x.com", "a2@y.com"], phones=["+1 555"], org="Acme"
        )
        sf = ct.parse_vcard(signed)
        self.assertEqual(sf["name"], "Ana, Jr")  # comma survives escape/unescape
        self.assertEqual(sf["emails"], ["a@x.com", "a2@y.com"])
        self.assertEqual(sf["phones"], [])  # TEL is NOT allowed in the signed card
        pf = ct.parse_vcard(private)
        self.assertEqual(pf["phones"], ["+1 555"])  # it lives in the private card
        self.assertEqual(pf["org"], "Acme")
        # both cards share one UID
        self.assertEqual(
            next(l for l in signed.splitlines() if l.startswith("UID:")),
            next(l for l in private.splitlines() if l.startswith("UID:")),
        )

    def test_no_private_card_when_only_name_and_email(self):
        signed, private = ct.build_contact_cards(name="Bob", emails=["b@x.com"])
        self.assertIsNotNone(signed)
        self.assertIsNone(private)


class _CrudClient:
    def __init__(self, rows=None):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self._rows = rows or []
        self.created = None
        self.deleted = None

    def list_contact_emails(self):
        return list(self._rows)

    def create_contact(self, **kwargs):
        self.created = kwargs
        return "NEWID1234567890"

    def delete_contacts(self, ids):
        self.deleted = list(ids)
        return len(self.deleted)

    def update_contact(self, cid, **kwargs):
        self.updated = {"id": cid, **kwargs}
        return cid


class CreateContactTool(unittest.TestCase):
    def _run(self, args):
        self.client = _CrudClient()
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_create_contact(args)

    def test_requires_a_name(self):
        self.assertIn("name", tools.handle_create_contact({}))

    def test_creates_with_name_and_emails(self):
        out = self._run({"name": "Ana", "emails": ["ana@x.com"]})
        self.assertEqual(self.client.created["name"], "Ana")
        self.assertEqual(self.client.created["emails"], ["ana@x.com"])
        self.assertIn("Saved contact", out)

    def test_create_is_not_gated(self):
        self.assertIsNone(tools.pre_tool_call_directive("proton_create_contact", {"name": "x"}))


class DeleteContactTool(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "Ana López", "email": "ana@x.com", "contact_id": "C1"},
            {"name": "Ana Ruiz", "email": "ana2@x.com", "contact_id": "C9"},
            {"name": "Bob", "email": "bob@x.com", "contact_id": "C2"},
        ]

    def _run(self, args):
        self.client = _CrudClient(self.rows)
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_delete_contact(args)

    def test_by_id(self):
        out = self._run({"contact_id": "C2"})
        self.assertEqual(self.client.deleted, ["C2"])
        self.assertIn("Deleted contact", out)

    def test_by_unique_name(self):
        self._run({"name": "Bob"})
        self.assertEqual(self.client.deleted, ["C2"])

    def test_ambiguous_name_refused_nothing_deleted(self):
        out = self._run({"name": "Ana"})
        self.assertIn("More than one contact matches", out)
        self.assertIsNone(self.client.deleted)

    def test_needs_id_or_name(self):
        self.assertIn("contact_id", self._run({}))


class EditContactTool(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"name": "Ana López", "email": "ana@x.com", "contact_id": "C1"},
            {"name": "Bob", "email": "bob@x.com", "contact_id": "C2"},
        ]

    def _run(self, args):
        self.client = _CrudClient(self.rows)
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_edit_contact(args)

    def test_needs_a_change(self):
        self.assertIn("Nothing to change", self._run({"contact_id": "C1"}))

    def test_edit_by_id_passes_only_given_fields(self):
        out = self._run({"contact_id": "C1", "phones": ["+1 555"], "org": "Acme"})
        self.assertEqual(self.client.updated["id"], "C1")
        self.assertEqual(self.client.updated["phones"], ["+1 555"])
        self.assertEqual(self.client.updated["org"], "Acme")
        self.assertNotIn("name", self.client.updated)  # unchanged fields not forced
        self.assertIn("Updated contact", out)

    def test_edit_by_unique_name(self):
        self._run({"name_lookup": "Bob", "name": "Robert"})
        self.assertEqual(self.client.updated["id"], "C2")
        self.assertEqual(self.client.updated["name"], "Robert")

    def test_edit_not_gated(self):
        self.assertIsNone(tools.pre_tool_call_directive("proton_edit_contact", {"contact_id": "C1"}))


class ContactsToolset(unittest.TestCase):
    def test_reading_and_not_gated(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_contacts"], tools.TOOLSET)
        self.assertEqual(toolset_of["proton_contact"], tools.TOOLSET)
        self.assertEqual(toolset_of["proton_create_contact"], tools.TOOLSET_WRITE)
        self.assertEqual(toolset_of["proton_edit_contact"], tools.TOOLSET_WRITE)
        self.assertEqual(toolset_of["proton_delete_contact"], tools.TOOLSET_WRITE)
        self.assertIsNone(tools.pre_tool_call_directive("proton_contacts", {}))
        self.assertIsNone(tools.pre_tool_call_directive("proton_contact", {}))


if __name__ == "__main__":
    unittest.main()
