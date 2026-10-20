"""hermes-proton: a Proton Mail connector for Hermes Agent.

Registers thirty-seven tools (``proton_login``, ``proton_accounts``, ``proton_unread``,
``proton_list``, ``proton_search``, ``proton_read``, ``proton_send``,
``proton_draft``, ``proton_mark``, ``proton_delete``, ``proton_get_attachment``, ``proton_gather_context``,
``proton_labels``, ``proton_label``, ``proton_calendar``, ``proton_contacts``, ``proton_contact``, ``proton_drive_list``, ``proton_drive_download``, ``proton_drive_create_folder``, ``proton_drive_upload``, ``proton_drive_move``, ``proton_drive_rename``, ``proton_drive_delete``, ``proton_create_event``, ``proton_cancel_event``, ``proton_create_contact``, ``proton_edit_contact``, ``proton_delete_contact``, ``proton_edit_event``, ``proton_rsvp``,
``proton_schedule_followup``) and
the ``hermes proton`` command. Several accounts can be signed in at once; every
tool takes an optional ``account``.

The acting tools (send, delete, schedule) sit in the ``proton_mail_write``
toolset, the reading tools in ``proton_mail``, so a scheduled follow-up can fire
with reading only and be unable to send.

The login is a CLI command rather than a tool on purpose: it is the one step
that needs the account password typed by a person, and it should never be
something the agent can be talked into doing.
"""

from __future__ import annotations

import getpass
import logging
import os
import sys

# Hermes loads this file directly, not as a package, so relative imports have
# no parent to resolve against. Putting the plugin's own directory on sys.path
# makes the imports below work the same way they do for the standalone CLI --
# and keeps a missing dependency reporting itself instead of being masked by a
# fallback import.
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

import proton_tools as _tools

logger = logging.getLogger(__name__)

__version__ = "0.26.1"


def _setup_cli(parser) -> None:
    sub = parser.add_subparsers(dest="proton_command", required=True)

    login = sub.add_parser("login", help="log in to Proton and save a session")
    login.add_argument("--user", help="your Proton address")
    login.add_argument(
        "--verification-token",
        default="",
        help="a verification token you already completed on Proton's page",
    )
    login.add_argument(
        "--totp-code",
        default="",
        help="six-digit code from your authenticator app, if the account has one",
    )

    sub.add_parser("status", help="show every signed-in account")
    sub.add_parser("accounts", help="list the signed-in accounts")

    logout = sub.add_parser("logout", help="revoke one account's session")
    logout.add_argument("--account", default="", help="which account (address or fragment)")

    unread = sub.add_parser("unread", help="list unread messages")
    unread.add_argument("--limit", type=int, default=20)
    unread.add_argument("--account", default="")

    listing = sub.add_parser("list", help="list a folder")
    listing.add_argument("--folder", default="inbox")
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--account", default="")

    read = sub.add_parser("read", help="read one message by id")
    read.add_argument("id")
    read.add_argument("--mark-read", action="store_true")
    read.add_argument("--account", default="")


def _handle_cli(args) -> int:
    import sys

    from protonlite.client import ProtonMail
    from protonlite.errors import (
        HumanVerificationRequired,
        ProtonError,
        TwoFactorRequired,
    )

    store = _tools.store()
    command = getattr(args, "proton_command", None)
    selector = getattr(args, "account", "") or ""

    try:
        if command == "login":
            username = getattr(args, "user", None) or input("Proton address: ").strip()
            path = store.path_for(username)
            password = getpass.getpass("Proton password (not shown): ")
            if not password:
                print("no password given")
                return 2
            token = getattr(args, "verification_token", "") or ""
            code = getattr(args, "totp_code", "") or ""

            def attempt(verification: str, totp: str):
                return ProtonMail.login(
                    username,
                    password.encode(),
                    session_path=path,
                    verification_token=verification,
                    totp_code=totp,
                )

            # Two things can interrupt a sign-in, and either can come first:
            # Proton's verification page, and a code from an authenticator app.
            # Both are answered by a person, so loop until neither is pending.
            client = None
            while client is None:
                try:
                    client = attempt(token, code)
                except HumanVerificationRequired as challenge:
                    print(
                        f"\nProton wants verification first "
                        f"({', '.join(challenge.methods)})."
                    )
                    print(f"Open this and complete it:\n\n  {challenge.web_url}\n")
                    if not sys.stdin.isatty():
                        print("Then run again with:")
                        print(
                            f"  hermes proton login --verification-token {challenge.token}"
                        )
                        return 1
                    input("Press Enter once it is done... ")
                    token = challenge.token
                except TwoFactorRequired as needed:
                    if code or not sys.stdin.isatty():
                        print(f"\n{needed}")
                        return 1
                    print(f"\n{needed}")
                    code = input("Six-digit code: ").strip()
                    if not code:
                        return 2
                    # The verification token is kept: if Proton still accepts it
                    # the page is not asked for twice, and if it is spent the
                    # loop simply hands over a fresh link.
            print(f"logged in as {username}")
            print("addresses: " + ", ".join(a["Email"] for a in client.addresses()))
            print(f"session saved to {path} (0600)")
            return 0

        if command == "status":
            allowed = _tools.allowed_recipients()
            accounts = store.list()
            if not accounts:
                print(_tools.check_requirements()[1])
                return 1
            for account in accounts:
                client = ProtonMail.from_session(session_path=account.path)
                print(f"account:   {account.label}")
                print("addresses: " + ", ".join(a["Email"] for a in client.addresses()))
                print(f"unread:    {client.unread_count()}")
                print(f"session:   {account.path}")
                print()
            print(
                "sending:   "
                + (", ".join(allowed) if allowed else f"disabled (set {_tools.ALLOWLIST_ENV})")
            )
            return 0

        if command == "accounts":
            print(_tools.handle_accounts({}))
            return 0

        if command == "logout":
            account = store.resolve(selector)
            ProtonMail.from_session(session_path=account.path).api.logout()
            account.path.unlink(missing_ok=True)
            print(f"session revoked for {account.label}")
            return 0

        # Reading from a terminal, without going through the agent. These share
        # the tools' own handlers so both surfaces behave identically.
        if command == "unread":
            print(_tools.handle_unread({"limit": args.limit, "account": selector}))
            return 0

        if command == "list":
            print(
                _tools.handle_list(
                    {"folder": args.folder, "limit": args.limit, "account": selector}
                )
            )
            return 0

        if command == "read":
            print(
                _tools.handle_read(
                    {"id": args.id, "mark_read": args.mark_read, "account": selector}
                )
            )
            return 0
    except ProtonError as exc:
        print(f"error: {exc}")
        return 1

    print("unknown subcommand")
    return 2


def register(ctx) -> None:
    """Called once by the plugin loader."""
    # Signing in cannot be gated on having a session: that is what it creates.
    for name, schema, handler, emoji, toolset in _tools.UNGATED_TOOLS:
        ctx.register_tool(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            emoji=emoji,
        )
    for name, schema, handler, emoji, toolset in _tools.TOOLS:
        ctx.register_tool(
            name=name,
            toolset=toolset,
            schema=schema,
            handler=handler,
            check_fn=_tools.check_requirements,
            emoji=emoji,
        )

    # Route every outgoing email through Hermes's human-approval gate. The gate
    # runs before the handler and fails closed, so no send happens -- by a
    # confused, manipulated, or less capable model -- without a person approving
    # it first. Only proton_send is gated; reading and searching are not.
    def _pre_tool_call(tool_name: str = "", args=None, **_kwargs):
        return _tools.pre_tool_call_directive(tool_name, args)

    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_cli_command(
        name="proton",
        help="Proton Mail session (login, status, logout)",
        setup_fn=_setup_cli,
        handler_fn=_handle_cli,
        description=(
            "Log in to Proton Mail once so the proton_* tools can read and send mail. "
            "The password is typed here and never stored: what is saved is a session "
            "token plus the key passphrase, which cannot be used to log in."
        ),
    )
