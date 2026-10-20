# Installing hermes-proton

A step-by-step guide to giving a Hermes Agent a Proton Mail account it can read,
search, send from, and move attachments through — on a free Proton plan, with no
Proton Bridge.

The one rule that shapes everything below: **your Proton password never travels
through the chat.** You type it in a terminal, or drop it in a one-time file the
agent consumes and deletes. There is no tool that accepts a password, so the
agent cannot be talked into putting one in a transcript.

---

## 1. Install and enable the plugin

```bash
hermes plugins install Maytrella007/hermes-proton --enable
hermes plugins list        # hermes-proton should show "enabled"
```

`--enable` matters: the Python dependencies (PGPy, bcrypt, requests) are resolved
when the plugin is enabled, so an install left disabled has none of them yet.

---

## 2. Sign in to Proton

Pick whichever fits where you are. Either way the password is used once and only a
session token is kept afterward.

### Option A — in a terminal (recommended when you have one)

This is the host shell, or the **Terminal tab** in Hermes Desktop / the dashboard —
any shell the model cannot see.

```bash
hermes proton login
```

What happens:

1. It asks for your Proton address and then your password (the password is not
   echoed).
2. **Verification page.** Signing in from a server almost always makes Proton ask
   a person to complete a page first. The command prints a link like
   `https://verify.proton.me/?methods=captcha&token=…`. Open it in a browser,
   complete it, and the login continues. (There is no CAPTCHA solver here — this
   is the same step Proton's own apps do.)
3. **Two-factor.** If the account has an authenticator app, it asks for the
   current six-digit code. Type it straight away — codes expire in ~30 seconds.
   It never asks for the authenticator's setup secret, only one live code.

Then check it:

```bash
hermes proton status
```

### Option B — by asking the agent (phone or chat only)

Useful when the only thing you have is a chat window. You leave the password in a
one-time file, then tell the agent to sign in.

```bash
install -m 600 /dev/null ~/.config/protonlite/login-password
cat > ~/.config/protonlite/login-password     # paste the password, then Ctrl-D
```

Then, in the chat:

> **you:** sign in to Proton as you@proton.me
>
> **agent:** Proton wants you to complete this page first:
> `https://verify.proton.me/?methods=captcha&token=…` — tell me when you're done.
> If the account has 2FA I'll ask for the code then.
>
> **you:** done, the code is 123456
>
> **agent:** Signed in, and the password file is deleted.

The agent reads the one-time file, signs in, and deletes it on success — and
also deletes it if the sign-in fails for good, so a wrong password is not left
on disk (the verification and two-factor steps keep it for that one retry). It
never sees the password itself, and it will decline if you offer to paste the
password into the chat.

> If the login link is hard to tap on a phone, ask the agent to send it as a file
> — it can hand you a page with a clickable button.

---

## 3. Add more than one account (optional)

Sign in again as a second address. Each account gets its own session file under
`~/.config/protonlite/sessions/`, and every tool then takes an optional account.

```bash
hermes proton accounts
hermes proton unread --account work@proton.me
```

Rule of thumb: with **one** account signed in you can leave the account out; with
**several**, a call that does not name one is refused (it lists them) rather than
guessing — sending from the wrong mailbox is not worth the convenience. A
distinctive fragment is enough (`william` picks `william.work@proton.me`).

---

## 4. Turn on sending

Reading works as soon as you are signed in. **Sending stays off until you say who
the agent may write to** — an agent with mail tools usually also has a shell, and
an allowlist keeps a confused or manipulated agent to a list you chose.

Put an allowlist in `~/.hermes/.env` and restart the gateway:

```bash
# comma-separated; globs like *@your-company.com are allowed
PROTON_ALLOWED_RECIPIENTS=you@example.com,*@your-company.com
```

`hermes proton status` prints the current allowlist alongside the session. A send
to anyone not covered is refused before it leaves, and `to`, `cc` **and** `bcc`
are all checked.

On top of that, **every send is confirmed by a person.** The plugin routes
`proton_send` through Hermes's approval gate: before a send runs, you are asked to
approve or deny it (`/approve`, `/deny`, or yes/no) with the recipients, subject
and attachment count shown. The gate runs before the send and fails closed, so a
manipulated or less capable model cannot send on its own. Choose *always* at the
prompt to pre-approve a recipient. If you would rather let the agent write to
anyone but confirm each one, set `PROTON_ALLOWED_RECIPIENTS=*` and rely on the
approval gate.

> **Keep the allowlist tight.** When it sends, the agent can attach any local
> file it is able to read. A narrow allowlist (specific addresses, not broad
> wildcards) is what stops a manipulated agent from mailing a file it shouldn't
> to somewhere it shouldn't.

---

## 5. What you can ask the agent, in plain language

Once signed in, every capability can be asked for in natural language. Examples:

| You say | The agent does |
|---|---|
| "Which Proton accounts are connected?" | lists accounts and unread counts |
| "Show me my unread mail" | lists the unread inbox |
| "List the last 10 in my archive" | lists a folder (any page of it) |
| "Find the email from support about the invoice" | searches by keyword / sender / subject |
| "Open that one and summarize it" | reads and decrypts the message |
| "Reply-less: send a note to a@b.com, cc my boss" | sends with cc (and bcc) |
| "Write a short status report and email it to X as an attachment" | writes the file, then sends it attached |
| "Download the attachment on that email and tell me what's in it" | downloads, decrypts, saves it locally |
| "Move those test emails to the trash" | trashes them (reversible) |

The agent names which account an answer came from whenever more than one is
signed in, and asks which to use if a request is ambiguous.

---

## 6. Attachments

### Receiving — download and read a document someone sent

Ask the agent to fetch it. It downloads the attachment, decrypts it with your
account key, and saves it to a local file under
`~/.config/protonlite/attachments/<message>/`. For a text file it shows the
contents inline; for a PDF, image, or archive it gives you the path so the agent
(or you) can open it.

> "Find the email with subject 'uv photos' and download its attachment."

### Sending — attach a report, a photo, anything

Point the agent at local file paths, or have it produce a file first:

> "Write a one-page summary of today's numbers and email it to me as an
> attachment."

Each file is encrypted and signed, uploaded to the draft, and its key is wrapped
per recipient — so a Proton recipient gets it end-to-end encrypted and an outside
recipient (Gmail, etc.) gets ordinary mail with the attachment. The recipient
allowlist still decides where it may go.

---

## 7. Verify it is working

```bash
hermes proton status          # session, addresses, unread count, allowlist
hermes proton unread          # a quick read
```

Or just ask the agent: *"How many unread do I have, and who are the three most
recent from?"*

---

## 8. What is stored (and what is not)

- A per-account session file (`~/.config/protonlite/sessions/<address>.json`,
  mode 0600) holds the access/refresh tokens and the **salted key passphrase**.
- **Your password is never stored.** The passphrase in that file can decrypt your
  mail but cannot log in, change the password, or reach any other Proton service.
- The session is a signed-in device on Proton's side. `hermes proton logout`
  revokes it, and so does Proton's own security-settings page.
- This is **not an inbound channel**: nothing here lets someone drive the agent by
  emailing it — a `From:` header is trivially forged.

---

## 9. Troubleshooting

- **"Sending is disabled: no recipient allowlist is configured."**
  Set `PROTON_ALLOWED_RECIPIENTS` in `~/.hermes/.env` and restart the gateway
  (step 4).
- **It keeps asking for the verification page.** Complete the printed link in a
  real browser; if Proton rate-limits repeated logins, sign in once from a browser
  and retry.
- **Two-factor:** use a code from an authenticator app. A hardware security key
  (FIDO2/U2F) will not work — add an app code as an alternative in Proton's
  settings.
- **"There are N accounts signed in … say which."** Pass or name the account
  (`--account you@proton.me`, or "…from my work account").
- **A pre-2016 account is refused.** Change the password once in Proton's web
  client to upgrade it, then sign in again.
- **The agent can't find the Proton tools** (it reaches for a browser, or says
  the Proton tools aren't available, even though `hermes proton status` works).
  This happens **only** after something re-resolves dependencies — a **Hermes
  core update** or **installing / updating / enabling a plugin** — which can leave
  the runtime's packages out of sync with the lock. This plugin's compiled
  dependencies (`cryptography`/`cffi`, via `pgpy`) then fail to import when the
  agent loads it, so it is quietly skipped. Ordinary restarts, reboots and new
  chats do **not** cause this — they only surface a venv that is already out of
  sync. The one-time fix, run after such an update:

  ```bash
  hermes pm install
  # then restart whatever serves the chat, e.g. the gateway / dashboard:
  systemctl --user restart hermes-gateway hermes-dashboard   # names vary by setup
  ```

  You do **not** need this on every restart — only after a Hermes/plugin update,
  and only if a Hermes command prints `install out of sync (venv: out of sync
  with uv.lock)`. Pure-Python plugins are unaffected, which is why this one can
  stop loading while others keep working. Opening a **new** chat afterwards picks up the tools (an
  existing chat keeps the toolset it started with).
- **It suddenly stops working.** This talks to Proton's private web API; Proton can
  change it without notice. That is the trade for not needing a paid Bridge plan.

---

## 10. Sign out or remove

```bash
hermes proton logout --account you@proton.me   # revoke one session
hermes plugins disable hermes-proton           # keep it installed, turn it off
hermes plugins remove hermes-proton            # uninstall
```

---

See the [README](../README.md) for the design rationale and the full tool list.
