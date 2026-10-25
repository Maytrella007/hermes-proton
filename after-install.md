# hermes-proton is installed

Two steps and the agent can read your Proton mailbox. Sending is a third,
separate step, because it is the one that can reach other people.

## 1. Sign in (once)

Proton has no app passwords, so this needs the account password once — and it
must not travel through a chat. You type it into a terminal prompt instead. In
the Terminal tab of Hermes Desktop/dashboard, or your shell over SSH:

```bash
hermes proton login --user you@proton.me
```

It asks for the password privately (not echoed), walks you through Proton's
verification page and a 2FA code if the account has one, and saves the session.
Or just tell the agent **"sign in to Proton as you@proton.me"** and it hands you
that same command to run — it never takes the password through the chat. Nothing
keeps the password afterwards: what is saved is a session token plus the
passphrase that opens your keys — which can decrypt mail but cannot log in or
change the password.

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

Sending refuses everything until you say who may be emailed:

```
hermes plugins settings hermes-proton --set allowed_recipients='["you@example.com","*@your-company.com"]'
```

(or the plugin's page in the Desktop app). The reason it works this way: whatever holds these
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
