# hermes-proton is installed

Two steps and the agent can read your Proton mailbox. Sending is a third,
separate step, because it is the one that can reach other people.

## 1. Sign in (once)

Proton has no app passwords, so this needs the account password once — and it
must not travel through a chat. Leave it in a one-time file instead:

```bash
install -m 600 /dev/null ~/.config/protonlite/login-password
cat > ~/.config/protonlite/login-password   # paste it, then Ctrl-D
```

Then either run `hermes proton login --user you@proton.me`, or just tell the
agent **"sign in to Proton as you@proton.me"**. It will call `proton_login`,
read that file, and delete it as soon as the sign-in succeeds — and also if the
sign-in fails for good, so a wrong password is not left on disk. Nothing keeps
the password afterwards: what is saved is a session token plus the passphrase
that opens your keys — which can decrypt mail but cannot log in or change the
password.

### Expect a verification page

Signing in from a server address almost always makes Proton ask a person to
complete a verification page. The agent will hand you a `verify.proton.me`
link: open it, complete it, tell the agent you are done, and it finishes the
sign-in. The link is good for about 25 minutes.

There is deliberately no solver here. A person completes that page, which is
exactly how Proton's own apps behave.

## 2. Check it

```bash
hermes proton status
```

Addresses, unread count, and whether sending is on. `hermes proton unread`
and `hermes proton read <id>` work from the terminal too.

## 3. Turn on sending, if you want it

Sending refuses everything until you say who may be emailed. In
`~/.hermes/.env`:

```
PROTON_ALLOWED_RECIPIENTS=you@example.com,*@your-company.com
```

Then restart the gateway. The reason it works this way: whatever holds these
tools usually also holds a terminal, and a confused or manipulated agent
should only be able to mail people you nominated.

## Good to know

- The session renews itself. The access token lasts about a day and is
  refreshed automatically, so you will not be asked to sign in again unless
  you revoke the session, change the password, or lose the session file.
- It shows up as a signed-in device in Proton's security settings, and you can
  kill it from there at any time.
- Two-factor sign-in and attachments (sending and downloading) are supported.
  Bodies go out as HTML by default so the mail looks normal; plain text you
  write is rendered to HTML for you, and raw HTML or plain text are both
  available on request.
- This talks to Proton's private API. If Proton changes it, this breaks.
