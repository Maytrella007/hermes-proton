"""Tests for keeping several accounts apart."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path

import proton_tools as tools
from protonlite.accounts import AccountStore, default_root
from protonlite.errors import ProtonError, SessionExpired


def _write(path: Path, address: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "uid": "u",
                "access_token": "a",
                "refresh_token": "r",
                "username": address,
                "salted_key_pass": "p",
            }
        )
    )


class Resolution(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = AccountStore(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _add(self, address: str) -> None:
        _write(self.store.path_for(address), address)

    def test_nothing_signed_in(self) -> None:
        with self.assertRaises(SessionExpired):
            self.store.resolve()

    def test_one_account_needs_no_selector(self) -> None:
        self._add("solo@proton.me")
        self.assertEqual(self.store.resolve().address, "solo@proton.me")

    def test_two_accounts_refuse_to_be_guessed(self) -> None:
        self._add("work@proton.me")
        self._add("home@proton.me")
        with self.assertRaises(ProtonError) as caught:
            self.store.resolve()
        self.assertIn("say which one", str(caught.exception))
        self.assertIn("work@proton.me", str(caught.exception))

    def test_exact_address(self) -> None:
        self._add("work@proton.me")
        self._add("home@proton.me")
        self.assertEqual(self.store.resolve("home@proton.me").address, "home@proton.me")

    def test_case_insensitive(self) -> None:
        self._add("Work@Proton.me")
        self.assertEqual(self.store.resolve("work@proton.me").address, "Work@Proton.me")

    def test_a_distinctive_fragment_is_enough(self) -> None:
        self._add("william.work@proton.me")
        self._add("personal@proton.me")
        self.assertEqual(
            self.store.resolve("william").address, "william.work@proton.me"
        )

    def test_an_ambiguous_fragment_is_an_error(self) -> None:
        self._add("one@proton.me")
        self._add("two@proton.me")
        with self.assertRaises(ProtonError) as caught:
            self.store.resolve("proton.me")
        self.assertIn("be exact", str(caught.exception))

    def test_an_unknown_selector_lists_what_exists(self) -> None:
        self._add("one@proton.me")
        with self.assertRaises(ProtonError) as caught:
            self.store.resolve("nope@proton.me")
        self.assertIn("one@proton.me", str(caught.exception))

    def test_separate_files_per_account(self) -> None:
        self._add("one@proton.me")
        self._add("two@proton.me")
        paths = {a.path for a in self.store.list()}
        self.assertEqual(len(paths), 2)

    def test_a_corrupt_file_is_not_an_account(self) -> None:
        self._add("fine@proton.me")
        (self.store.sessions_dir / "broken.json").write_text("{ not json")
        self.assertEqual([a.address for a in self.store.list()], ["fine@proton.me"])


class LegacyMigration(unittest.TestCase):
    """Early versions kept a single session.json; it is moved in, once."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.store = AccountStore(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_moves_the_old_file_into_the_new_layout(self) -> None:
        _write(self.store.legacy_session, "old@proton.me")
        accounts = self.store.list()
        self.assertEqual([a.address for a in accounts], ["old@proton.me"])
        self.assertFalse(self.store.legacy_session.exists())
        self.assertTrue(self.store.path_for("old@proton.me").exists())

    def test_without_a_username_it_still_becomes_an_account(self) -> None:
        self.store.legacy_session.parent.mkdir(parents=True, exist_ok=True)
        self.store.legacy_session.write_text(
            json.dumps({"version": 1, "uid": "u", "access_token": "a", "refresh_token": "r"})
        )
        self.assertEqual(len(self.store.list()), 1)

    def test_a_newer_session_is_not_overwritten(self) -> None:
        _write(self.store.path_for("same@proton.me"), "same@proton.me")
        _write(self.store.legacy_session, "same@proton.me")
        self.store.list()
        # The legacy file stays put rather than clobbering the live session.
        self.assertTrue(self.store.legacy_session.exists())
        self.assertEqual(len(self.store.list()), 1)


if __name__ == "__main__":
    unittest.main()


class SessionRootFollowsTheProfile(unittest.TestCase):
    """Each profile has its own signed-in accounts.

    They all shared ~/.config/protonlite, so two profiles shared one mailbox
    and the allowlist could come from the wrong one. Inside Hermes the root is
    the plugin's own data directory, resolved on every call because
    plugin_data_dir follows the active profile.
    """

    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ROOT_ENV)
        os.environ.pop(tools.ROOT_ENV, None)

    def tearDown(self) -> None:
        sys.modules.pop("plugins.plugin_storage", None)
        sys.modules.pop("plugins", None)
        if self._saved is None:
            os.environ.pop(tools.ROOT_ENV, None)
        else:
            os.environ[tools.ROOT_ENV] = self._saved

    def _pretend_hermes_is_hosting(self, where):
        package = types.ModuleType("plugins")
        package.__path__ = []
        storage = types.ModuleType("plugins.plugin_storage")
        storage.plugin_data_dir = lambda name: Path(where) / "plugin-data" / name
        package.plugin_storage = storage
        sys.modules["plugins"] = package
        sys.modules["plugins.plugin_storage"] = storage

    def test_inside_hermes_the_root_is_the_plugins_own_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            self._pretend_hermes_is_hosting(home)
            self.assertEqual(tools._root(), Path(home) / "plugin-data" / "hermes-proton")
            self.assertEqual(tools.store().root, Path(home) / "plugin-data" / "hermes-proton")

    def test_the_environment_override_still_wins(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as chosen:
            self._pretend_hermes_is_hosting(home)
            os.environ[tools.ROOT_ENV] = chosen
            self.assertEqual(tools._root(), Path(chosen))

    def test_without_hermes_protonlites_own_default_applies(self) -> None:
        # The standalone CLI, where there is no profile to follow.
        self.assertEqual(tools._root(), Path(default_root()))


class AdoptingAnOlderInstall(unittest.TestCase):
    """An upgrade must not read as "you are logged out".

    Moving the session root is right, but on its own it hides the accounts
    somebody signed in yesterday. They are copied once, and only when nothing
    has been signed in in the new place.
    """

    def setUp(self) -> None:
        self._saved = os.environ.get(tools.ROOT_ENV)
        os.environ.pop(tools.ROOT_ENV, None)

    def tearDown(self) -> None:
        sys.modules.pop("plugins.plugin_storage", None)
        sys.modules.pop("plugins", None)
        if self._saved is None:
            os.environ.pop(tools.ROOT_ENV, None)
        else:
            os.environ[tools.ROOT_ENV] = self._saved

    def _host(self, home, fake_home):
        package = types.ModuleType("plugins")
        package.__path__ = []
        storage = types.ModuleType("plugins.plugin_storage")
        storage.plugin_data_dir = lambda name: Path(home) / "plugin-data" / name
        package.plugin_storage = storage
        sys.modules["plugins"] = package
        sys.modules["plugins.plugin_storage"] = storage
        legacy = Path(fake_home) / ".config" / "protonlite" / "sessions"
        legacy.mkdir(parents=True)
        return legacy

    def test_sessions_from_the_old_place_are_adopted_once(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as fake_home:
            legacy = self._host(home, fake_home)
            (legacy / "me-at-proton-me.json").write_text('{"uid": "x"}')
            with mock.patch.object(Path, "home", staticmethod(lambda: Path(fake_home))):
                said = tools.adopt_legacy_sessions()
                landed = Path(home) / "plugin-data" / "hermes-proton" / "sessions"
                self.assertIn("adopted 1", said)
                self.assertTrue((landed / "me-at-proton-me.json").is_file())
                self.assertEqual((landed / "me-at-proton-me.json").stat().st_mode & 0o777, 0o600)
                # The old files stay, so going back a version still finds them.
                self.assertTrue((legacy / "me-at-proton-me.json").is_file())
                # And a second load does nothing.
                self.assertEqual(tools.adopt_legacy_sessions(), "")

    def test_an_account_signed_in_here_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as fake_home:
            legacy = self._host(home, fake_home)
            (legacy / "a.json").write_text('{"uid": "old"}')
            landed = Path(home) / "plugin-data" / "hermes-proton" / "sessions"
            landed.mkdir(parents=True)
            (landed / "a.json").write_text('{"uid": "new"}')
            with mock.patch.object(Path, "home", staticmethod(lambda: Path(fake_home))):
                self.assertEqual(tools.adopt_legacy_sessions(), "")
            self.assertIn("new", (landed / "a.json").read_text())

    def test_a_deliberate_override_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as fake_home:
            legacy = self._host(home, fake_home)
            (legacy / "a.json").write_text("{}")
            os.environ[tools.ROOT_ENV] = home
            with mock.patch.object(Path, "home", staticmethod(lambda: Path(fake_home))):
                self.assertEqual(tools.adopt_legacy_sessions(), "")
