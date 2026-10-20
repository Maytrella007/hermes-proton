"""Tests for reading Proton Calendar: iCal parsing, event decryption, the tool.

No network: the crypto is exercised through a clear-text card, and the one
encrypted-card path is checked with crypto.decrypt_attachment stubbed.
"""

from __future__ import annotations

import base64
import os
import types
import unittest
from unittest import mock

import proton_tools as tools
from protonlite import calendar as cal


CLEAR_ICAL = (
    "BEGIN:VEVENT\r\n"
    "DTSTART;TZID=America/New_York:20260922T093000\r\n"
    "ORGANIZER;CN=Benjamin Azancot:mailto:benjamin@example.com\r\n"
    "SUMMARY;LANGUAGE=en-US:Review Design with William\r\n"
    "LOCATION:Microsoft Teams Meeting\r\n"
    "DESCRIPTION:line one\\nline two\\, still line two\r\n"
    "END:VEVENT\r\n"
)


class ICalParsing(unittest.TestCase):
    def test_unfold_joins_continuation_lines(self):
        folded = "DESCRIPTION:aaa\r\n bbb\r\n ccc"
        self.assertEqual(cal._unfold(folded), ["DESCRIPTION:aaabbbccc"])

    def test_unescape_handles_the_text_escapes(self):
        self.assertEqual(cal._unescape("a\\nb\\, c\\; d\\\\e"), "a\nb, c; d\\e")

    def test_fields_reads_summary_location_description(self):
        f = cal._fields(CLEAR_ICAL)
        self.assertEqual(f["SUMMARY"], "Review Design with William")
        self.assertEqual(f["LOCATION"], "Microsoft Teams Meeting")
        self.assertEqual(f["DESCRIPTION"], "line one\nline two, still line two")

    def test_organizer_prefers_the_display_name(self):
        self.assertEqual(cal._fields(CLEAR_ICAL)["ORGANIZER"], "Benjamin Azancot")


class ICalBuilding(unittest.TestCase):
    def test_escape_is_the_inverse_of_unescape(self):
        for s in ("plain", "a, b; c", "line\nbreak", "back\\slash", "¡hola, señor!"):
            self.assertEqual(cal._unescape(cal._escape(s)), s)

    def test_fold_keeps_lines_within_75_octets_and_unfolds_back(self):
        long = "DESCRIPTION:" + "x" * 300
        folded = cal._fold(long)
        for physical in folded.split("\r\n"):
            self.assertLessEqual(len(physical.encode("utf-8")), 75)
        self.assertEqual(cal._unfold(folded), [long])

    def test_fold_does_not_split_a_multibyte_character(self):
        folded = cal._fold("SUMMARY:" + "ñ" * 60)
        for physical in folded.split("\r\n"):
            physical.encode("utf-8").decode("utf-8")  # must not raise
        self.assertEqual("".join(cal._unfold(folded)), "SUMMARY:" + "ñ" * 60)

    def test_vevent_round_trips_through_the_reader(self):
        body = cal.vevent("UID-1", [("SUMMARY", "Lunch, with Ana; soon"), ("LOCATION", "Café")])
        self.assertIn("BEGIN:VEVENT", body)
        f = cal._fields(body)
        self.assertEqual(f["SUMMARY"], "Lunch, with Ana; soon")
        self.assertEqual(f["LOCATION"], "Café")


class EncryptCardRoundTrip(unittest.TestCase):
    """A card encrypted for write decrypts back through the read path."""

    @classmethod
    def setUpClass(cls):
        import warnings

        warnings.simplefilter("ignore")
        import os

        from pgpy import PGPKey, PGPUID
        from pgpy.constants import (
            CompressionAlgorithm,
            HashAlgorithm,
            KeyFlags,
            PubKeyAlgorithm,
            SymmetricKeyAlgorithm,
        )
        from protonlite.crypto import KeyBundle

        key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
        key.add_uid(
            PGPUID.new("Cal", email="cal@proton.me"),
            usage={KeyFlags.Sign, KeyFlags.EncryptCommunications},
            hashes=[HashAlgorithm.SHA256],
            ciphers=[SymmetricKeyAlgorithm.AES256],
            compression=[CompressionAlgorithm.Uncompressed],
        )
        cls.key = key
        cls.bundle = KeyBundle(id="cal", armored=str(key), passphrase=b"")
        cls.session = os.urandom(32)

    def test_encrypt_then_decrypt_attachment_recovers_the_ical(self):
        ical = cal.vevent("UID-9", [("SUMMARY", "Secret, meeting"), ("LOCATION", "HQ")])
        data_b64, sig = self.encrypt(ical)
        skp = base64.b64decode(cal.wrap_session_key(self.session, str(self.key.pubkey)))
        out = cal.crypto.decrypt_attachment(skp, base64.b64decode(data_b64), [self.bundle])
        self.assertEqual(out.decode("utf-8"), ical)
        self.assertEqual(sig, "")  # no signer given

    def test_signature_is_over_the_plaintext_and_verifies(self):
        ical = cal.vevent("UID-9", [("SUMMARY", "x")])
        _data, sig = self.encrypt(ical, signer=self.bundle)
        self.assertTrue(sig)
        import pgpy

        self.assertTrue(self.key.pubkey.verify(ical, pgpy.PGPSignature.from_blob(sig)))

    def encrypt(self, ical, signer=None):
        return cal.encrypt_card(ical, self.session, str(self.key.pubkey), signer)


class DecryptEvent(unittest.TestCase):
    def _raw(self, card_type, data, **extra):
        base = {
            "ID": "EV1",
            "StartTime": 1790083800,
            "EndTime": 1790087400,
            "StartTimezone": "America/New_York",
            "FullDay": 0,
            "SharedKeyPacket": base64.b64encode(b"keypacket").decode(),
            "SharedEvents": [{"Type": card_type, "Data": data}],
            "Attendees": [{"ID": "a"}, {"ID": "b"}],
        }
        base.update(extra)
        return base

    def test_a_clear_card_is_read_without_decryption(self):
        ev = cal.decrypt_event(self._raw(0, CLEAR_ICAL), mock.Mock())
        self.assertEqual(ev.title, "Review Design with William")
        self.assertEqual(ev.start, 1790083800)
        self.assertEqual(ev.start_tz, "America/New_York")
        self.assertEqual(ev.num_attendees, 2)
        self.assertFalse(ev.full_day)

    def test_an_encrypted_card_goes_through_decrypt_attachment(self):
        data = base64.b64encode(b"datapacket").decode()
        with mock.patch.object(
            cal.crypto, "decrypt_attachment", return_value=CLEAR_ICAL.encode()
        ) as dec:
            ev = cal.decrypt_event(self._raw(1, data), mock.Mock())
        dec.assert_called_once()
        # it was handed the key packet and the data packet, base64-decoded
        self.assertEqual(dec.call_args.args[0], b"keypacket")
        self.assertEqual(dec.call_args.args[1], b"datapacket")
        self.assertEqual(ev.title, "Review Design with William")

    def test_a_card_that_will_not_decrypt_is_skipped_not_fatal(self):
        from protonlite.errors import ProtonError

        data = base64.b64encode(b"x").decode()
        with mock.patch.object(cal.crypto, "decrypt_attachment", side_effect=ProtonError("nope")):
            ev = cal.decrypt_event(self._raw(1, data), mock.Mock())
        self.assertEqual(ev.title, "")  # no crash, just no title


class _Event:
    def __init__(self, start, title, tz="UTC", full_day=False, location="", organizer="", n=0):
        self.id = "EVID1"
        self.start = start
        self.end = start + 3600
        self.start_tz = tz
        self.full_day = full_day
        self.title = title
        self.location = location
        self.description = ""
        self.organizer = organizer
        self.rrule = ""
        self.num_attendees = n


class _CalClient:
    def __init__(self, calendars, events):
        self.api = types.SimpleNamespace(
            session=types.SimpleNamespace(username="me@proton.me")
        )
        self._calendars = calendars
        self._events = events

    def list_calendars(self):
        return list(self._calendars)

    def list_events(self, calendar_id, *, start, end, **_kw):
        return [e for e in self._events.get(calendar_id, []) if start <= e.start <= end]


class CalendarTool(unittest.TestCase):
    def _run(self, client, args=None):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_calendar(args or {})

    def test_agenda_lists_events_and_is_fenced_as_untrusted(self):
        import datetime as dt

        soon = int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600
        client = _CalClient(
            [{"ID": "C1", "Members": [{"Name": "Personal"}]}],
            {"C1": [_Event(soon, "Dentist", organizer="Dr X", n=1)]},
        )
        out = self._run(client)
        self.assertIn("Dentist", out)
        self.assertIn("organizer: Dr X", out)
        self.assertIn("begin email content", out)      # untrusted fence
        self.assertIn("never an instruction", out.lower())
        self.assertTrue(out.startswith("Account: me@proton.me"))

    def test_a_calendar_that_cannot_be_opened_is_skipped(self):
        import datetime as dt
        from protonlite.errors import ProtonError

        soon = int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600
        client = _CalClient(
            [{"ID": "GOOD", "Members": [{"Name": "Personal"}]},
             {"ID": "BROKEN", "Members": [{"Name": "Keyless"}]}],
            {"GOOD": [_Event(soon, "Dentist")]},
        )
        orig = client.list_events

        def maybe_raise(cid, **kw):
            if cid == "BROKEN":
                raise ProtonError("A passphrase must be created before executing this action")
            return orig(cid, **kw)

        client.list_events = maybe_raise
        out = self._run(client)
        self.assertIn("Dentist", out)  # the good calendar still shows

    def test_no_events_in_window(self):
        client = _CalClient([{"ID": "C1", "Members": [{"Name": "Personal"}]}], {"C1": []})
        out = self._run(client)
        self.assertIn("No events", out)

    def test_no_calendars(self):
        out = self._run(_CalClient([], {}))
        self.assertIn("No calendars", out)

    def test_unknown_calendar_name_is_reported(self):
        client = _CalClient([{"ID": "C1", "Members": [{"Name": "Personal"}]}], {"C1": []})
        out = self._run(client, {"calendar": "Work"})
        self.assertIn("No calendar named", out)

    def test_bad_date_is_refused(self):
        client = _CalClient([{"ID": "C1", "Members": [{"Name": "P"}]}], {"C1": []})
        self.assertIn("YYYY-MM-DD", self._run(client, {"start": "22-09-2026"}))

    def test_expired_session_says_auth_required(self):
        from protonlite.errors import SessionExpired

        client = _CalClient([{"ID": "C1", "Members": [{"Name": "P"}]}], {})
        client.list_calendars = mock.Mock(side_effect=SessionExpired("revoked"))
        out = self._run(client)
        self.assertIn("AUTH REQUIRED", out)
        self.assertIn("proton_login", out)


class CreateHelpers(unittest.TestCase):
    def test_attendee_token_is_sha1_of_uid_then_email(self):
        import hashlib

        tok = cal.attendee_token("UID-1", "person@example.com")
        self.assertEqual(tok, hashlib.sha1(b"UID-1person@example.com").hexdigest())
        self.assertEqual(len(tok), 40)

    def test_invite_ics_is_a_request_with_tokened_attendees(self):
        ics = cal.build_invite_ics(
            uid="U1", dtstamp="20260101T000000Z", dtstart="20260101T090000Z",
            dtend="20260101T100000Z", summary="Sync, weekly", location="HQ",
            description="bring notes", organizer_email="me@proton.me",
            attendees=[("a@x.com", "tok123")],
        )
        self.assertIn("METHOD:REQUEST", ics)
        self.assertIn("X-PM-TOKEN=tok123", ics)
        self.assertIn("mailto:a@x.com", ics)
        f = cal._fields(ics)
        self.assertEqual(f["SUMMARY"], "Sync, weekly")  # escaping round-trips


class _CreateClient:
    def __init__(self, calendars):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self._calendars = calendars
        self.created = None
        self.sent = None

    def list_calendars(self):
        return list(self._calendars)

    def create_event(self, calendar_id, **kwargs):
        self.created = {"calendar_id": calendar_id, **kwargs}
        return {"id": "EVNEW123456789", "attendees": [(a, "tok") for a in kwargs.get("attendees") or []],
                "invite_ics": "BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\nEND:VCALENDAR"}

    def send(self, **kwargs):
        self.sent = kwargs
        return types.SimpleNamespace(id="MSG1")


class CreateEventTool(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        self.client = _CreateClient([{"ID": "C1", "Members": [{"Name": "Personal"}]}])

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _run(self, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_create_event(args)

    def test_requires_title_and_start(self):
        self.assertIn("title", self._run({"title": "x"}))

    def test_bad_start_is_refused(self):
        self.assertIn("ISO 8601", self._run({"title": "x", "start": "next tuesday"}))

    def test_private_event_creates_without_sending(self):
        out = self._run({"title": "Focus", "start": "2026-10-21T15:00:00Z"})
        self.assertIn("Created", out)
        self.assertIsNotNone(self.client.created)
        self.assertIsNone(self.client.sent)  # no attendees -> no invitation email

    def test_attendee_must_be_on_the_allowlist(self):
        os.environ[tools.ALLOWLIST_ENV] = "team@acme.com"
        out = self._run({"title": "x", "start": "2026-10-21T15:00:00Z", "attendees": ["evil@no.com"]})
        self.assertIn("not on the allowlist", out)
        self.assertIsNone(self.client.created)  # refused before creating

    def test_invitation_is_emailed_with_an_ics_attachment(self):
        os.environ[tools.ALLOWLIST_ENV] = "*"
        out = self._run(
            {"title": "Kickoff", "start": "2026-10-21T15:00:00Z", "attendees": ["a@x.com"]}
        )
        self.assertIn("invitation emailed to a@x.com", out)
        att = self.client.sent["attachments"][0]
        self.assertEqual(att["name"], "invite.ics")
        self.assertIn("text/calendar", att["mime"])

    def test_default_end_is_one_hour_after_start(self):
        self._run({"title": "x", "start": "2026-10-21T15:00:00Z"})
        delta = self.client.created["end"] - self.client.created["start"]
        self.assertEqual(delta.total_seconds(), 3600)


class CreateEventGate(unittest.TestCase):
    def test_gated_only_when_there_are_attendees(self):
        with_att = tools.pre_tool_call_directive(
            "proton_create_event", {"title": "x", "start": "s", "attendees": ["a@x.com"]}
        )
        self.assertEqual(with_att["action"], "approve")
        self.assertIn("a@x.com", with_att["message"])
        self.assertTrue(with_att["rule_key"].startswith("proton_create_event:"))
        # a private event is an internal write -> not gated
        self.assertIsNone(
            tools.pre_tool_call_directive("proton_create_event", {"title": "x", "start": "s"})
        )


class _EditClient:
    def __init__(self):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))
        self.updated = None

    def list_calendars(self):
        return [{"ID": "C1", "Members": [{"Name": "Personal"}]}]

    def find_event_calendar(self, _eid):
        return "C1"

    def delete_event(self, calendar_id, event_id):
        self.deleted = (calendar_id, event_id)
        return True

    def update_event(self, calendar_id, event_id, **kwargs):
        import datetime as dt

        self.updated = {"calendar_id": calendar_id, "event_id": event_id, **kwargs}
        return {
            "id": event_id, "summary": kwargs.get("summary", "Existing"),
            "location": "", "description": "", "sequence": 1,
            "start": kwargs.get("start") or dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
            "end": dt.datetime(2026, 1, 1, 1, tzinfo=dt.timezone.utc),
        }


class EditEventTool(unittest.TestCase):
    def _run(self, args):
        client = _EditClient()
        self.client = client
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_edit_event(args)

    def test_requires_an_event_id(self):
        self.assertIn("event id", tools.handle_edit_event({}))

    def test_requires_at_least_one_change(self):
        self.assertIn("Nothing to change", self._run({"event_id": "E1"}))

    def test_bad_date_is_refused(self):
        self.assertIn("ISO 8601", self._run({"event_id": "E1", "start": "mañana"}))

    def test_title_change_is_passed_as_summary(self):
        out = self._run({"event_id": "E1", "title": "New Title"})
        self.assertEqual(self.client.updated["summary"], "New Title")
        self.assertIn("Updated", out)

    def test_notify_zero_removes_reminder(self):
        self._run({"event_id": "E1", "notify_minutes": 0})
        self.assertEqual(self.client.updated["notify_minutes"], 0)

    def test_edit_is_not_gated(self):
        self.assertIsNone(tools.pre_tool_call_directive("proton_edit_event", {"event_id": "E1"}))


class CancelEventTool(unittest.TestCase):
    def test_requires_event_id(self):
        self.assertIn("event id", tools.handle_cancel_event({}))

    def test_cancels_via_delete_event(self):
        client = _EditClient()
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            out = tools.handle_cancel_event({"event_id": "E1"})
        self.assertEqual(client.deleted, ("C1", "E1"))
        self.assertIn("Cancelled", out)

    def test_not_gated(self):
        self.assertIsNone(tools.pre_tool_call_directive("proton_cancel_event", {"event_id": "E1"}))


class RsvpHelpers(unittest.TestCase):
    def _invite(self):
        return cal.build_invite_ics(
            uid="U-1", dtstamp="20260101T000000Z", dtstart="20260101T090000Z",
            dtend="20260101T100000Z", summary="Standup", location="HQ", description="",
            organizer_email="boss@acme.com", attendees=[("me@proton.me", "tok-me")],
        )

    def test_parse_invite_extracts_organizer_uid_and_attendee_token(self):
        p = cal.parse_invite(self._invite())
        self.assertEqual(p["uid"], "U-1")
        self.assertEqual(p["organizer"], "boss@acme.com")
        self.assertEqual(p["summary"], "Standup")
        self.assertEqual(p["attendees"][0], {"email": "me@proton.me", "token": "tok-me"})
        self.assertTrue(any(t.startswith("DTSTART") for t in p["timing"]))

    def test_ical_to_datetime_handles_z_tzid_and_floating(self):
        import datetime as dt

        z = cal.ical_to_datetime("DTSTART:20260101T090000Z")
        self.assertEqual(z, dt.datetime(2026, 1, 1, 9, tzinfo=dt.timezone.utc))
        ny = cal.ical_to_datetime("DTSTART;TZID=America/New_York:20260101T090000")
        self.assertEqual(ny.astimezone(dt.timezone.utc).hour, 14)  # EST = UTC-5
        floating = cal.ical_to_datetime("DTSTART:20260101T090000")
        self.assertEqual(floating.tzinfo, dt.timezone.utc)

    def test_parse_invite_reads_description(self):
        ics = cal.build_invite_ics(
            uid="U", dtstamp="20260101T000000Z", dtstart="20260101T090000Z",
            dtend="20260101T100000Z", summary="S", location="L", description="notes here",
            organizer_email="o@x.com", attendees=[],
        )
        self.assertEqual(cal.parse_invite(ics)["description"], "notes here")

    def test_build_reply_is_a_reply_with_partstat_and_token(self):
        p = cal.parse_invite(self._invite())
        reply = cal.build_reply_ics(
            uid=p["uid"], organizer_email=p["organizer"], attendee_email="me@proton.me",
            token="tok-me", partstat="ACCEPTED", dtstamp="20260101T010000Z",
            timing=p["timing"], summary=p["summary"],
        )
        self.assertIn("METHOD:REPLY", reply)
        self.assertIn("PARTSTAT=ACCEPTED", reply)
        self.assertIn("X-PM-TOKEN=tok-me", reply)
        self.assertIn("mailto:me@proton.me", reply)


class _RsvpClient:
    def __init__(self, ics, me="me@proton.me"):
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username=me))
        self._ics = ics
        self._me = me
        self.sent = None

    def list_attachments(self, _mid):
        return [{"ID": "A1", "MIMEType": "text/calendar", "Name": "invite.ics"}]

    def get_attachment(self, _mid, attachment_id=None, **_kw):
        return ("invite.ics", "text/calendar", self._ics.encode("utf-8"))

    def addresses(self):
        return [{"Email": self._me, "ID": "addr1"}]

    def canonical_emails(self, emails):
        return {e: e.lower() for e in emails}

    def send(self, **kwargs):
        self.sent = kwargs
        return types.SimpleNamespace(id="M1")

    # calendar side, for add_to_calendar
    def __post_init__(self):
        pass

    def list_calendars(self):
        return getattr(self, "_calendars", [])

    def provision_default_calendar(self):
        self.provisioned = True
        return "NEWCAL"

    def import_invitation(self, calendar_id, invite, *, status):
        self.imported = {"calendar_id": calendar_id, "status": status, "uid": invite.get("uid")}
        return "EVNEW"


class RsvpTool(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(tools.ALLOWLIST_ENV)
        os.environ[tools.ALLOWLIST_ENV] = "*"
        self.ics = cal.build_invite_ics(
            uid="U-9", dtstamp="20260101T000000Z", dtstart="20260101T090000Z",
            dtend="20260101T100000Z", summary="Kickoff", location="", description="",
            organizer_email="boss@acme.com", attendees=[("me@proton.me", "tok-me")],
        )
        self.client = _RsvpClient(self.ics)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(tools.ALLOWLIST_ENV, None)
        else:
            os.environ[tools.ALLOWLIST_ENV] = self._saved

    def _run(self, args):
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=self.client):
            return tools.handle_rsvp({"message_id": "M", **args})

    def test_bad_answer_refused(self):
        self.assertIn("yes", self._run({"answer": "perhaps"}))

    def test_accept_emails_a_reply_to_the_organizer(self):
        out = self._run({"answer": "yes"})
        self.assertIn("accepted", out.lower())
        self.assertEqual(self.client.sent["to"], ["boss@acme.com"])
        self.assertEqual(self.client.sent["parent_id"], "M")  # threaded onto the invite
        att = self.client.sent["attachments"][0]
        self.assertEqual(att["name"], "reply.ics")
        self.assertIn("method=REPLY", att["mime"])
        self.assertIn("PARTSTAT=ACCEPTED", att["data"].decode())

    def test_decline_maps_to_declined(self):
        self._run({"answer": "no"})
        self.assertIn("PARTSTAT=DECLINED", self.client.sent["attachments"][0]["data"].decode())

    def test_organizer_must_be_on_the_allowlist(self):
        os.environ[tools.ALLOWLIST_ENV] = "someone@else.com"
        out = self._run({"answer": "yes"})
        self.assertIn("not on the allowlist", out)
        self.assertIsNone(self.client.sent)

    def test_gate_escalates_rsvp(self):
        d = tools.pre_tool_call_directive("proton_rsvp", {"message_id": "M", "answer": "no"})
        self.assertEqual(d["action"], "approve")
        self.assertIn("DECLINED", d["message"])

    def test_rsvp_rule_key_is_per_invitation(self):
        # Approving one reply must not pre-approve every future RSVP email.
        a = tools.pre_tool_call_directive("proton_rsvp", {"message_id": "M1", "answer": "yes"})
        b = tools.pre_tool_call_directive("proton_rsvp", {"message_id": "M2", "answer": "yes"})
        self.assertIn("M1", a["rule_key"])
        self.assertNotEqual(a["rule_key"], b["rule_key"])

    def test_add_to_calendar_provisions_when_none_and_imports(self):
        self.client._calendars = []  # no calendar yet
        out = self._run({"answer": "yes", "add_to_calendar": True})
        self.assertTrue(getattr(self.client, "provisioned", False))
        self.assertEqual(self.client.imported["calendar_id"], "NEWCAL")
        self.assertEqual(self.client.imported["status"], 3)  # ACCEPTED
        self.assertIn("newly created calendar", out)

    def test_add_to_calendar_uses_existing_calendar(self):
        self.client._calendars = [{"ID": "C1"}]
        out = self._run({"answer": "maybe", "add_to_calendar": True})
        self.assertFalse(getattr(self.client, "provisioned", False))
        self.assertEqual(self.client.imported["calendar_id"], "C1")
        self.assertEqual(self.client.imported["status"], 1)  # TENTATIVE
        self.assertIn("added to your calendar", out)

    def test_without_flag_no_calendar_write(self):
        self.client._calendars = [{"ID": "C1"}]
        self._run({"answer": "yes"})
        self.assertIsNone(getattr(self.client, "imported", None))


class CalendarToolset(unittest.TestCase):
    def test_calendar_reads_and_is_not_gated(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_calendar"], tools.TOOLSET)  # reading
        self.assertEqual(toolset_of["proton_create_event"], tools.TOOLSET_WRITE)  # writing
        self.assertEqual(toolset_of["proton_rsvp"], tools.TOOLSET_WRITE)  # writing
        self.assertEqual(toolset_of["proton_edit_event"], tools.TOOLSET_WRITE)  # writing
        self.assertIsNone(tools.pre_tool_call_directive("proton_calendar", {}))


if __name__ == "__main__":
    unittest.main()
