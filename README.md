# MailFlow — email automation

MailFlow uses FastAPI, Microsoft Graph, SQLite, and an Excel-based recipient picker.

## What is included

- Gmail-style mailbox, opening to Inbox, with Inbox / Outbox / Sent / Drafts / Trash.
- Compose includes a grouped recipient picker, selection controls, disabled unavailable routes, To/CC routing, a fixed sender, content validation, and a preview. Each selected company receives a separate email.
- Send now, Schedule, and Save as draft at the bottom right of Compose. Every action has a confirmation preview; incomplete drafts can be saved.
- One-time, daily, weekly, and monthly schedules; adjustable interval, IANA timezone, and optional end date.
- Persistent drafts with edit conflict detection; persistent queue with per-route progress and a single scheduler owner.
- Microsoft Inbox and Sent, message reading, read/unread controls, folder search, 50-message remote pages, bulk delete, and restoration to the recorded original folder.
- Local Outbox/draft deletion and restoration. Restored Outbox jobs stay paused until explicitly resumed.

## Set up a new Windows checkout

1. Install Python 3.14 or newer, clone the repository, and open a PowerShell terminal in its folder. The app uses Python's built-in UUIDv7 generator. Create a virtual environment and install the dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   Copy-Item .env.example .env
   ```

2. Supply your own recipient workbook. By default the app reads `data/3rd Party- Ticket Support.xlsx`; the `data/` folder and workbook are not in Git. Create the folder and put your workbook there, or change `COMPANIES_FILE` in `.env` to its location. The active worksheet must have these headers within its first 50 rows: `Module`, `Third Party`, `Third Party Group`, `Email To`, and `Email CC`. Use one company per row. `Email To` and `Email CC` can contain addresses separated by commas, semicolons, or newlines.

3. Use an existing Microsoft Entra app registration if its owner gives you the client ID and client secret privately, or [register your own application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app). This version signs in personal Microsoft accounts (such as Outlook.com) through the `consumers` authority. The registration must support personal Microsoft accounts and have a **Web** redirect URI of `http://localhost:8000/auth/callback`. For a new registration, choose **Personal Microsoft accounts only**, create a client secret under **Certificates & secrets**, and copy its **Value** when shown. Under **API permissions**, add Microsoft Graph **Delegated** permissions `User.Read`, `Mail.Send`, and `Mail.ReadWrite`. Grant consent when prompted during sign-in.

4. Edit the local `.env`: set `MICROSOFT_CLIENT_ID` to the application (client) ID, `MICROSOFT_CLIENT_SECRET` to the secret **Value**, and `MICROSOFT_FIXED_SENDER_EMAIL` to the Outlook mailbox that will sign in and send mail. Someone using their own mailbox sets their own address here, even if they share the Entra registration. Using the owner's mailbox also requires signing in as that mailbox; the client ID and secret alone do not grant mailbox access. You do not need to edit `app/core/config.py`; it reads these values from `.env`. Keep `MICROSOFT_CALLBACK_URI=http://localhost:8000/auth/callback` unless you also change the Web redirect URI in Entra. `MICROSOFT_TENANT_ID` and `MICROSOFT_REDIRECT_URI` are retained for older integrations; this sign-in flow uses the `consumers` authority and `MICROSOFT_CALLBACK_URI`. Keep `.env` private.

5. Start the app with `.\.venv\Scripts\python.exe start_app.py`, then open `http://localhost:8000/auth/login` to sign in as the configured sender. The app creates `app_data/` and its SQLite database at startup. It creates `auth_data/` for the encrypted Microsoft token cache when sign-in starts. Both folders are ignored by Git and remain local to that installation. The token cache is protected for the Windows user who signed in; a different user or computer must sign in again.

## Upgrade your existing Windows project

1. Stop the app with **Ctrl+C**. Back up your current project, including `app_data/`, before applying the update.
2. Copy the contents of this package's `ai-email-automation` folder into your existing project folder. Replace matching source files. Keep your existing `.env`, `.venv/`, `data/`, `auth_data/`, and `app_data/` in that project.
3. In the activated virtual environment, run:

   ```powershell
   python -m pip install -r requirements.txt
   python -m pytest -q
   ```

4. Open your existing Microsoft Entra app registration. Under **API permissions → Add a permission → Microsoft Graph → Delegated permissions**, add **Mail.ReadWrite**. Keep **User.Read** and **Mail.Send**. Complete consent as required for the account.
5. Start the app:

   ```powershell
   python start_app.py
   ```

6. If Microsoft requests consent for the new permission, open `http://localhost:8000/auth/login` once and sign in with the configured sender account. MailFlow then keeps the encrypted session and renews access silently whenever Microsoft permits it; the header intentionally shows only the mailbox address and connection-status dot.

The update creates additional tables in the existing database on startup. Existing saved previews and send-job records are retained. The new mailbox queue owns its jobs; the old send endpoint cannot start a scheduled job early.

When running the app in a separate folder, provide your Excel workbook and configuration.

## Sending and drafts

- Click **Compose**, choose recipient routes, and enter subject/content.
- **Send now** opens the preview. Confirming creates a durable Outbox job; the scheduler picks it up within the polling interval.
- **Save as draft** opens a draft preview, including partial text. Confirming saves the draft without sending.
- **Schedule** opens the schedule panel. Set the starting local date/time, timezone, repetition, interval, and optional end date. Click **Schedule** again to preview, then **Confirm schedule**.
- Open an Outbox item to see the exact stored recipients and every route's result. Open a Draft to edit it.
- Inbox/Sent come from the connected Microsoft mailbox. Outbox and Drafts are managed by this app in SQLite. Sent mailbox copies may take a moment to appear after Graph accepts a submission.
- Search matches subjects and sender addresses in Microsoft folders, and subjects/content in local folders. It searches the current folder.

## Recurrence and restart behavior

Keep the Python application running and the computer awake for automatic sending. The browser can be closed. This is a single-user local application; `start_app.py` binds to localhost.

The recipient addresses, sender, subject, and body are saved when the preview is approved. Recurring sends use that saved snapshot. Later workbook edits cannot redirect an approved schedule. To change the recipients/content of a recurring series, pause/delete its pending Outbox occurrence and create a new schedule with a fresh preview.

- Repetition follows the selected timezone's local clock. A monthly schedule starting on the 31st uses the last available day in shorter months, then returns to the 31st when available.
- A starting time that does not exist during a spring clock change is rejected. Later nonexistent occurrences are skipped. During a repeated autumn hour, the first occurrence is used once.
- The end date is inclusive in the selected timezone.
- Jobs more than five minutes late are paused for review by default, including jobs missed while the application was closed or the PC was asleep. Resuming sends remaining eligible routes now, then continues the original recurrence at the next future occurrence. Missed occurrences are not replayed in a burst.
- Authentication failures preserve accepted routes. If the header status dot reports that the saved session needs attention, open `/auth/login` once, then resume the job from Outbox.
- A confirmed Microsoft 429 response is delayed according to Retry-After; accepted routes are skipped on the next attempt.
- A lost send response or application interruption during submission leaves an uncertain outcome for review. The app does not automatically resend that route. Check Microsoft Sent and the route results before composing any remaining email.
- Graph acceptance is not delivery confirmation. Delivery failures can still arrive later in Inbox.

Optional settings, with defaults:

```dotenv
SEND_JOB_DB_FILE=app_data/send_jobs.sqlite3
SCHEDULER_ENABLED=true
SCHEDULER_POLL_SECONDS=10
SCHEDULE_LATE_GRACE_SECONDS=300
```

Drafts, message snapshots, schedule history, and restore metadata live in `app_data/`. Retain this folder when upgrading or moving the installation. The existing encrypted Microsoft token cache stays in `auth_data/`.

## Delete and restore

The row trash icon or selection toolbar moves messages to Trash. Microsoft messages are moved into the actual Microsoft Deleted Items folder. The original folder is recorded before the move, using stable message identifiers, so restoring returns the message to its original mailbox folder.

Deleting an Outbox item cancels its future sends. An already submitted request can still finish; deleting cannot recall an email Microsoft has accepted. Restoring returns the item to Outbox in a paused state. Use **Resume remaining sends** after reviewing its results. A completed occurrence can change while a page is open; refresh Outbox to act on the next occurrence.

For messages deleted outside this app, the original folder may be unknown. The restore dialog lets you choose Inbox or Sent in that case. Drafts restore to Drafts. Moving a message to Trash can be undone immediately. In Trash, the row icon or **Delete selected** permanently deletes messages after an in-app confirmation; permanent deletion cannot be undone.

## Checks and boundaries

Automated tests cover queue concurrency, recurrence and daylight saving changes, authentication interruption, uncertain outcomes, throttling, cancellation, stale previews, draft conflicts, and Microsoft folder restoration. Email operations are mocked; the tests do not send real email.

The UI checks cover preview/save/reopen draft, scheduling, Outbox delete/restore, message reading, bulk Microsoft delete/restore, permanent Trash deletion, and responsive controls.

Live Microsoft sign-in, mailbox operations, and email delivery need to be verified with your account and tenant.

## Microsoft API references

- [List messages and pagination](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
- [Move messages and Mail.ReadWrite](https://learn.microsoft.com/en-us/graph/api/message-move?view=graph-rest-1.0)
- [Immutable message identifiers](https://learn.microsoft.com/en-us/graph/outlook-immutable-id)
- [sendMail and acceptance semantics](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
