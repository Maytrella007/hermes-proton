"""Tests for the contextual follow-up: the gather-context tool and the scheduler.

Re-grounding is anchored on a thread (conversation_id) and gathered as evidence
split into earlier vs new-since-a-date. The scheduled job is reading-only, so it
can never send.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import proton_tools as tools


# --- a tiny fake mailbox for the gather tool ---------------------------------
class _Sender:
    def __init__(self, text): self._t = text
    def __str__(self): return self._t


class _Sum:
    def __init__(self, mid, t, subject, sender, conv="C1"):
        self.id = mid; self.time = t; self.subject = subject
        self.sender = _Sender(sender); self.conversation_id = conv


class _Msg:
    def __init__(self, text): self.text = text


class _GatherClient:
    def __init__(self, rows, bodies):
        self._rows = rows; self._bodies = bodies
        self.api = types.SimpleNamespace(session=types.SimpleNamespace(username="me@proton.me"))

    def list_messages(self, **kw):
        return list(self._rows)

    def read_message(self, mid, **kw):
        return _Msg(self._bodies.get(mid, "(body)"))


class GatherContext(unittest.TestCase):
    def setUp(self):
        # Mar 1 (old), Apr 1 (old), Jun 20 (new, after a May 1 "since")
        self.rows = [
            _Sum("a", 1772337600, "Order #1 - placed", "us <me@proton.me>"),
            _Sum("b", 1775016000, "RE: Order #1", "Acme <v@acme.com>"),
            _Sum("c", 1781001600, "RE: Order #1 - shipped", "Acme <v@acme.com>"),
        ]
        self.bodies = {"a": "we placed it", "b": "confirmed, 3 months", "c": "shipped TRK-9"}

    def _run(self, args):
        client = _GatherClient(self.rows, self.bodies)
        with mock.patch.object(tools.ProtonMail, "for_account", return_value=client):
            return tools.handle_gather_context(args)

    def test_needs_an_anchor(self):
        self.assertIn("anchor", tools.handle_gather_context({}).lower())

    def test_splits_earlier_and_new_since(self):
        out = self._run({"conversation_id": "C1", "since": "2026-05-01"})
        self.assertIn("Earlier (before 2026-05-01)", out)
        self.assertIn("NEW since 2026-05-01", out)
        # the June message is in the NEW section, the March one is earlier
        new_part = out[out.index("NEW since"):]
        self.assertIn("shipped TRK-9", new_part)
        self.assertNotIn("we placed it", new_part)

    def test_output_is_fenced_as_untrusted(self):
        out = self._run({"conversation_id": "C1", "since": "2026-05-01"})
        self.assertIn("begin email content", out)
        self.assertIn("never an instruction", out.lower())

    def test_expired_session_is_reported_not_swallowed(self):
        from protonlite.errors import SessionExpired
        with mock.patch.object(tools.ProtonMail, "for_account",
                               side_effect=SessionExpired("revoked")):
            out = tools.handle_gather_context({"conversation_id": "C1", "since": "2026-05-01"})
        self.assertIn("AUTH REQUIRED", out)
        self.assertIn("proton_login", out)


# --- the scheduler -----------------------------------------------------------
class ScheduleFollowup(unittest.TestCase):
    def setUp(self):
        self.jobs = []

        def _create_job(**kwargs):
            self.jobs.append(dict(kwargs))
            return {"id": f"JOB{len(self.jobs)}", "next_run_at": "2026-12-24T09:00:00"}

        fake_jobs = types.ModuleType("cron.jobs"); fake_jobs.create_job = _create_job
        fake_cron = types.ModuleType("cron"); fake_cron.jobs = fake_jobs
        self._saved = {k: sys.modules.get(k) for k in ("cron", "cron.jobs")}
        sys.modules["cron"] = fake_cron
        sys.modules["cron.jobs"] = fake_jobs

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None: sys.modules.pop(k, None)
            else: sys.modules[k] = v

    def _call(self, **extra):
        args = {"when": "2026-12-24T09:00", "about": "check on order #4521",
                "conversation_id": "CONV9"}
        args.update(extra)
        return tools.handle_schedule_followup(args)

    def test_requires_when_and_about(self):
        self.assertIn("I need", tools.handle_schedule_followup({"when": "in 3d"}))

    def test_creates_reading_only_job_with_gather_prompt(self):
        answer = self._call()
        self.assertIn("JOB1", answer)
        main = self.jobs[0]
        self.assertEqual(main["repeat"], 1)
        self.assertEqual(main["enabled_toolsets"], [tools.TOOLSET])
        p = main["prompt"]
        self.assertIn("proton_gather_context", p)        # re-grounding via the gather tool
        self.assertIn('conversation_id="CONV9"', p)       # anchored on the pinned thread
        self.assertIn("CANNOT send", p)
        self.assertIn("untrusted data", p)
        self.assertIn("since=", p)                         # the time anchor
        self.assertIn("AUTH REQUIRED", p)                  # auth-failure is not swallowed

    def test_schedules_a_silent_unless_inactive_precheck(self):
        self._call()  # far-future follow-up -> a pre-check job is also created
        self.assertEqual(len(self.jobs), 2)
        pre = self.jobs[1]
        self.assertEqual(pre["enabled_toolsets"], [tools.TOOLSET])  # reading only
        self.assertIn("[SILENT]", pre["prompt"])            # silent unless inactive
        self.assertIn("proton_accounts", pre["prompt"])
        self.assertIn("proton_login", pre["prompt"])

    def test_no_precheck_when_disabled(self):
        self._call(remind_days_before=0)
        self.assertEqual(len(self.jobs), 1)  # only the follow-up, no pre-check

    def test_toolset_split(self):
        toolset_of = {name: ts for name, _s, _h, _e, ts in tools.TOOLS}
        self.assertEqual(toolset_of["proton_gather_context"], tools.TOOLSET)       # reading
        self.assertEqual(toolset_of["proton_schedule_followup"], tools.TOOLSET_WRITE)
        self.assertEqual(toolset_of["proton_send"], tools.TOOLSET_WRITE)


if __name__ == "__main__":
    unittest.main()
