# AI Email Automation — mailbox update

Built on the supplied `New WinRAR ZIP archive(3).zip` project. Python/FastAPI, Microsoft Graph, SQLite, and the existing Excel recipient picker.

## What is included

- Gmail-style mailbox, opening to Inbox, with Inbox / Outbox / Sent / Drafts / Trash.
- Compose at the bottom right. The existing grouped recipient picker, select/unselect controls, disabled unavailable routes, To/CC separation, fixed sender, content validation, and preview are retained.
- Send now, Schedule, and Save as draft at the bottom right of Compose. Every action has a confirmation preview; incomplete drafts can be saved.
- One-time, daily, weekly, and monthly schedules; adjustable interval, IANA timezone, and optional end date.
- Persistent drafts with edit conflict detection; persistent queue with per-route progress and a single scheduler owner.
- Microsoft Inbox and Sent, message reading, read/unread controls, folder search, 50-message remote pages, bulk delete, and restoration to the recorded original folder.
- Local Outbox/draft deletion and restoration. Restored Outbox jobs stay paused until explicitly resumed.

## Upgrade your existing Windows project

1. Stop the app with **Ctrl+C**. Back up your current project, including `app_data/`, before applying the update.
2. Copy the contents of this package's `ai-email-automation` folder into your existing project folder. Replace matching source files. Keep your existing `.env`, `.venv/`, `data/`, `auth_data/`, and `app_data/` in that project.
3. In the activated virtual environment, run:

   ```powershell
   python -m pip install -r requirements-dev.txt
   python -m pytest -q
   ```

4. Open your existing Microsoft Entra app registration. Under **API permissions → Add a permission → Microsoft Graph → Delegated permissions**, add **Mail.ReadWrite**. Keep **User.Read** and **Mail.Send**. Complete consent as required for the account.
5. Start the app:

   ```powershell
   python start_app.py
   ```

6. In the new mailbox, click **Reconnect** or **Connect Microsoft** and sign in with the configured sender account so the new permission is granted.

The update creates additional tables in the existing database on startup. Existing saved previews and send-job records are retained. The new mailbox queue owns its jobs; the old send endpoint cannot start a scheduled job early.

The package is an update for your existing installation. Supply your existing Excel workbook and configuration when running it in a separate folder.

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
- Authentication failures preserve accepted routes. Reconnect, then resume the job from Outbox.
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

For messages deleted outside this app, the original folder may be unknown. The restore dialog lets you choose Inbox or Sent in that case. Drafts restore to Drafts. This release uses recoverable deletion only.

## Checks and boundaries

The automated suite includes the uploaded project's existing tests and new checks for queue concurrency, recurrence/DST, authentication interruption, uncertain outcomes, throttling, cancellation, stale previews, draft conflicts, and Microsoft folder restoration. Live HTTP calls are blocked in pytest; email operations use mocks.

The UI was exercised in Chromium using a synthetic mailbox: preview/save/reopen draft, schedule, Outbox delete/restore, message reading, bulk Microsoft delete/restore, and mobile width. See `CHECKS.md` for the recorded results. Preview screenshots contain synthetic data.

Validation was performed on Linux with Python 3.12. Windows DPAPI sign-in, real tenant/account consent, live Microsoft mailbox behavior, and real email delivery require a check in your installation. Existing FastAPI/AnyIO test-client deprecation warnings remain.

## Microsoft API references

- [List messages and pagination](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0)
- [Move messages and Mail.ReadWrite](https://learn.microsoft.com/en-us/graph/api/message-move?view=graph-rest-1.0)
- [Immutable message identifiers](https://learn.microsoft.com/en-us/graph/outlook-immutable-id)
- [sendMail and acceptance semantics](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0)
