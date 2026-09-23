"""Mailbox state layered on the project's existing saved-preview database."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

from app.schemas.mailbox import DraftInput, ScheduleRule
from app.services.recurrence import next_occurrence, occurrence
from app.services.send_job_service import initialize_send_job_store


class MailConflict(ValueError):
    pass


def now_utc():
    return datetime.now(UTC)


def stamp(value=None):
    return (value or now_utc()).astimezone(UTC).isoformat()


class MailStore:
    def __init__(self, path: Path):
        self.path = path
        initialize_send_job_store(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS mail_drafts (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    folder TEXT NOT NULL DEFAULT 'drafts', updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mail_queue (
                    job_id TEXT PRIMARY KEY REFERENCES send_jobs(job_id),
                    rule_json TEXT, series_id TEXT, occurrence_index INTEGER NOT NULL DEFAULT 0,
                    run_at TEXT NOT NULL, folder TEXT NOT NULL DEFAULT 'outbox',
                    original_folder TEXT NOT NULL DEFAULT 'outbox',
                    cancelled INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '',
                    UNIQUE(series_id, occurrence_index)
                );
                CREATE INDEX IF NOT EXISTS mail_queue_due ON mail_queue(folder, run_at);
                CREATE TABLE IF NOT EXISTS mail_trash_origins (
                    message_id TEXT PRIMARY KEY, folder_id TEXT NOT NULL,
                    folder_name TEXT NOT NULL, updated_at TEXT NOT NULL
                );
            """)
            if "revision" not in {
                r[1] for r in db.execute("PRAGMA table_info(mail_queue)")
            }:
                db.execute(
                    "ALTER TABLE mail_queue ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
                )

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def save_draft(self, payload: DraftInput, draft_id=None):
        data = payload.model_dump(mode="json", exclude={"revision"})
        draft_id = str(draft_id or uuid7())
        with self.connect(True) as db:
            old = db.execute(
                "SELECT * FROM mail_drafts WHERE id=?", (draft_id,)
            ).fetchone()
            if old:
                if old["folder"] != "drafts" or old["revision"] != payload.revision:
                    raise MailConflict(
                        "This draft changed in another window. Reopen it before saving."
                    )
                db.execute(
                    "UPDATE mail_drafts SET payload=?,revision=revision+1,updated_at=? WHERE id=?",
                    (json.dumps(data), stamp(), draft_id),
                )
            else:
                if payload.revision is not None:
                    raise MailConflict("This draft no longer exists.")
                db.execute(
                    "INSERT INTO mail_drafts(id,payload,updated_at) VALUES(?,?,?)",
                    (draft_id, json.dumps(data), stamp()),
                )
        return self.draft(draft_id)

    def draft(self, draft_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM mail_drafts WHERE id=?", (str(draft_id),)
            ).fetchone()
        if row is None:
            raise LookupError("Draft not found.")
        data = json.loads(row["payload"])
        return {
            **data,
            "id": row["id"],
            "kind": "draft",
            "folder": row["folder"],
            "revision": row["revision"],
            "date": row["updated_at"],
            "is_read": True,
            "sender": "Draft",
            "snippet": data["content"][:160],
            "status": "draft",
            "original_folder": "drafts",
        }

    def _insert_job(self, db, preview_id, due, rule_json=None, series_id=None, index=0):
        preview = db.execute(
            "SELECT * FROM email_previews WHERE preview_id=?", (preview_id,)
        ).fetchone()
        if preview is None:
            raise LookupError("Preview not found. Create a new preview.")
        job_id = str(uuid7())
        db.execute(
            "INSERT INTO send_jobs(job_id,preview_id,status,created_at) VALUES(?,?,'queued',?)",
            (job_id, preview_id, stamp()),
        )
        for i, route in enumerate(json.loads(preview["recipients_json"])):
            db.execute(
                "INSERT INTO send_job_routes VALUES(?,?,?,?,?,?,?)",
                (
                    job_id,
                    i,
                    route["source_row"],
                    route["name"],
                    "pending",
                    None,
                    stamp(),
                ),
            )
        db.execute(
            "INSERT INTO mail_queue(job_id,rule_json,series_id,occurrence_index,run_at) VALUES(?,?,?,?,?)",
            (job_id, rule_json, series_id, index, stamp(due)),
        )
        return job_id

    def enqueue(self, preview_id, rule=None, draft_id=None, draft_revision=None):
        preview_id = str(preview_id)
        rule_json = rule.model_dump_json() if rule else None
        with self.connect(True) as db:
            existing = db.execute(
                "SELECT j.job_id,q.rule_json FROM send_jobs j LEFT JOIN mail_queue q ON q.job_id=j.job_id WHERE j.preview_id=?",
                (preview_id,),
            ).fetchone()
            if existing:
                if existing["rule_json"] != rule_json:
                    raise MailConflict(
                        "This preview was already submitted with different scheduling options."
                    )
                job_id = existing["job_id"]
                if not db.execute(
                    "SELECT 1 FROM mail_queue WHERE job_id=?", (job_id,)
                ).fetchone():
                    raise MailConflict(
                        "This preview was already sent. Create a new preview for another email."
                    )
            else:
                preview = db.execute(
                    "SELECT created_at FROM email_previews WHERE preview_id=?",
                    (preview_id,),
                ).fetchone()
                if not preview:
                    raise LookupError("Preview not found.")
                if now_utc() - datetime.fromisoformat(
                    preview["created_at"]
                ) > timedelta(hours=24):
                    raise MailConflict("This preview expired. Review the email again.")
                due = occurrence(rule, 0) if rule else now_utc()
                if due is None or (rule and due <= now_utc()):
                    raise MailConflict("Choose a start time in the future.")
                if draft_id:
                    draft = db.execute(
                        "SELECT * FROM mail_drafts WHERE id=?", (str(draft_id),)
                    ).fetchone()
                    if (
                        not draft
                        or draft["folder"] != "drafts"
                        or draft["revision"] != draft_revision
                    ):
                        raise MailConflict(
                            "The draft changed. Reopen and preview it again."
                        )
                series_id = str(uuid7()) if rule and rule.frequency != "once" else None
                job_id = self._insert_job(db, preview_id, due, rule_json, series_id)
                if draft_id:
                    db.execute("DELETE FROM mail_drafts WHERE id=?", (str(draft_id),))
        return self.job(job_id)

    def _queue_row(self, db, job_id, current=False):
        row = db.execute(
            "SELECT q.*,j.status FROM mail_queue q JOIN send_jobs j ON j.job_id=q.job_id WHERE q.job_id=?",
            (str(job_id),),
        ).fetchone()
        if row is None:
            raise LookupError("Outbox item not found.")
        # Completed occurrences are history, not the controls for a live series.
        if current and row["folder"] == "sent" and row["series_id"]:
            series_id = row["series_id"]
            row = db.execute(
                """SELECT q.*,j.status FROM mail_queue q JOIN send_jobs j ON j.job_id=q.job_id
                WHERE q.series_id=? AND q.folder='outbox'
                ORDER BY q.occurrence_index DESC LIMIT 1""",
                (series_id,),
            ).fetchone()
            if row is None:
                row = db.execute(
                    """SELECT q.*,j.status FROM mail_queue q JOIN send_jobs j ON j.job_id=q.job_id
                    WHERE q.series_id=? ORDER BY q.occurrence_index DESC LIMIT 1""",
                    (series_id,),
                ).fetchone()
        return row

    def edit_schedule(self, job_id, rule, revision):
        with self.connect(True) as db:
            row = self._queue_row(db, job_id, current=True)
            job_id = row["job_id"]
            if row["revision"] != revision:
                raise MailConflict("This schedule changed. Reopen it before editing.")
            if row["folder"] != "outbox" or row["status"] not in {
                "queued",
                "paused",
                "retry",
                "authentication_required",
            }:
                raise MailConflict(
                    "This occurrence is sending, finished, or needs review. Refresh Outbox before editing."
                )
            states = [
                r[0]
                for r in db.execute(
                    "SELECT status FROM send_job_routes WHERE job_id=?", (str(job_id),)
                )
            ]
            if any(s in {"unknown", "failed", "sending"} for s in states) or all(
                s == "accepted" for s in states
            ):
                raise MailConflict(
                    "Review the recorded send outcomes before changing this schedule."
                )
            due = occurrence(rule, 0)
            if due is None or due <= now_utc():
                raise MailConflict("Choose a send time in the future.")
            # Editing creates a fresh series. This preserves sent history and
            # makes the edited occurrence the new recurrence anchor.
            series_id = str(uuid7()) if rule.frequency != "once" else None
            remains_paused = row["status"] in {"paused", "authentication_required"}
            db.execute(
                """UPDATE mail_queue SET rule_json=?,run_at=?,series_id=?,occurrence_index=0,
                cancelled=?,revision=revision+1,detail=? WHERE job_id=?""",
                (
                    rule.model_dump_json(),
                    stamp(due),
                    series_id,
                    1 if remains_paused else 0,
                    (
                        "Schedule updated. Remains paused."
                        if remains_paused
                        else "Schedule updated."
                    ),
                    str(job_id),
                ),
            )
            if row["status"] == "retry":
                db.execute(
                    "UPDATE send_jobs SET status='queued',completed_at=NULL WHERE job_id=?",
                    (str(job_id),),
                )
        return self.job(job_id)

    def job(self, job_id, current=False):
        with self.connect() as db:
            job_id = self._queue_row(db, job_id, current)["job_id"]
            row = db.execute(
                """SELECT q.*,j.status,j.preview_id,j.created_at,p.sender,p.subject,p.content,p.recipients_json
                FROM mail_queue q JOIN send_jobs j ON j.job_id=q.job_id
                JOIN email_previews p ON p.preview_id=j.preview_id WHERE q.job_id=?""",
                (str(job_id),),
            ).fetchone()
            if row is None:
                raise LookupError("Outbox item not found.")
            routes = db.execute(
                "SELECT route_index,source_row,name,status,detail FROM send_job_routes WHERE job_id=? ORDER BY route_index",
                (str(job_id),),
            ).fetchall()
        result = dict(row)
        result.update(
            id=result.pop("job_id"),
            kind="job",
            date=result["run_at"],
            is_read=True,
            snippet=result["content"][:160],
            recipients=json.loads(result.pop("recipients_json")),
            schedule=json.loads(result.pop("rule_json") or "null"),
            results=[dict(route) for route in routes],
        )
        return result

    def list_local(self, folder):
        with self.connect() as db:
            drafts = db.execute(
                "SELECT id FROM mail_drafts WHERE folder=? ORDER BY updated_at DESC",
                (folder,),
            ).fetchall()
            jobs = db.execute(
                "SELECT job_id FROM mail_queue WHERE folder=? ORDER BY run_at DESC",
                (folder,),
            ).fetchall()
        return [self.draft(row["id"]) for row in drafts] + [
            self.job(row["job_id"]) for row in jobs
        ]

    def local_action(self, kind, item_id, action):
        with self.connect(True) as db:
            if kind == "draft":
                row = db.execute(
                    "SELECT folder FROM mail_drafts WHERE id=?", (item_id,)
                ).fetchone()
                if row is None:
                    raise LookupError("Draft not found.")
                if action == "delete":
                    if row["folder"] != "trash":
                        raise MailConflict(
                            "Only trashed drafts can be permanently deleted."
                        )
                    db.execute("DELETE FROM mail_drafts WHERE id=?", (item_id,))
                    return
                if action not in {"trash", "restore"}:
                    raise MailConflict("This action is not available for a draft.")
                db.execute(
                    "UPDATE mail_drafts SET folder=?,revision=revision+1,updated_at=? WHERE id=?",
                    ("trash" if action == "trash" else "drafts", stamp(), item_id),
                )
                return
            row = self._queue_row(
                db, item_id, current=action in {"trash", "pause", "resume"}
            )
            item_id = row["job_id"]
            if action == "delete":
                if row["folder"] != "trash":
                    raise MailConflict(
                        "Only trashed messages can be permanently deleted."
                    )
                if row["status"] == "sending":
                    raise MailConflict(
                        "Cancellation is recorded. Wait for the in-flight request to finish before permanent deletion."
                    )
                db.execute("DELETE FROM mail_queue WHERE job_id=?", (item_id,))
                return item_id
            if action == "trash":
                if row["folder"] == "trash":
                    return item_id
                db.execute(
                    "UPDATE mail_queue SET original_folder=folder,folder='trash',cancelled=1,detail='Moved to Trash. Future sends cancelled.' WHERE job_id=?",
                    (item_id,),
                )
                if row["status"] != "sending":
                    db.execute(
                        "UPDATE send_jobs SET status='cancelled' WHERE job_id=?",
                        (item_id,),
                    )
            elif action == "restore":
                if row["folder"] != "trash":
                    return item_id
                db.execute(
                    "UPDATE mail_queue SET folder=original_folder,detail='Restored. Review and resume to send remaining routes.' WHERE job_id=?",
                    (item_id,),
                )
                if row["status"] != "sending":
                    db.execute(
                        "UPDATE send_jobs SET status='paused' WHERE job_id=?",
                        (item_id,),
                    )
            elif action == "pause":
                if row["folder"] != "outbox":
                    raise MailConflict("Only Outbox schedules can be paused.")

                db.execute(
                    "UPDATE mail_queue SET cancelled=1,detail='Schedule paused.' WHERE job_id=?",
                    (item_id,),
                )

                if row["status"] != "sending":
                    db.execute(
                        "UPDATE send_jobs SET status='paused' WHERE job_id=?",
                        (item_id,),
                    )

            elif action == "resume":
                if row["folder"] != "outbox" or row["status"] == "sending":
                    raise MailConflict("This item cannot be resumed right now.")

                states = [
                    r[0]
                    for r in db.execute(
                        "SELECT status FROM send_job_routes WHERE job_id=?",
                        (item_id,),
                    )
                ]

                if any(s in {"unknown", "failed", "sending"} for s in states) or all(
                    s == "accepted" for s in states
                ):
                    raise MailConflict(
                        "Review the recorded outcomes. This job cannot be automatically resent."
                    )

                resume_at = max(
                    datetime.fromisoformat(row["run_at"]),
                    now_utc(),
                )

                db.execute(
                    "UPDATE mail_queue SET cancelled=0,run_at=?,detail='' WHERE job_id=?",
                    (stamp(resume_at), item_id),
                )

                db.execute(
                    "UPDATE send_jobs SET status='queued',completed_at=NULL WHERE job_id=?",
                    (item_id,),
                )

            else:
                raise MailConflict("This action is not available for an Outbox item.")

            db.execute(
                "UPDATE mail_queue SET revision=revision+1 WHERE job_id=?",
                (item_id,),
            )
            return item_id

    def recover_interrupted(self):
        """Called only after obtaining the process-wide scheduler lock."""
        with self.connect(True) as db:
            jobs = db.execute(
                "SELECT j.job_id FROM send_jobs j JOIN mail_queue q ON q.job_id=j.job_id WHERE j.status='sending'"
            ).fetchall()
            for row in jobs:
                job_id = row["job_id"]
                db.execute(
                    "UPDATE send_job_routes SET status='unknown',detail='The application stopped during submission. Check Sent before taking action.',updated_at=? WHERE job_id=? AND status='sending'",
                    (stamp(), job_id),
                )
                db.execute(
                    "UPDATE send_jobs SET status='needs_review' WHERE job_id=?",
                    (job_id,),
                )
                db.execute(
                    "UPDATE mail_queue SET detail='Interrupted send. Review each route; no automatic resend.' WHERE job_id=?",
                    (job_id,),
                )

    def claim_due(self, now, grace_seconds):
        with self.connect(True) as db:
            row = db.execute(
                """SELECT j.job_id,j.status,q.run_at FROM send_jobs j JOIN mail_queue q ON q.job_id=j.job_id
                WHERE q.folder='outbox' AND q.cancelled=0 AND j.status IN ('queued','retry') AND q.run_at<=?
                ORDER BY q.run_at LIMIT 1""",
                (stamp(now),),
            ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            if (
                row["status"] == "queued"
                and (now - datetime.fromisoformat(row["run_at"])).total_seconds()
                > grace_seconds
            ):
                db.execute(
                    "UPDATE send_jobs SET status='paused' WHERE job_id=?", (job_id,)
                )
                db.execute(
                    "UPDATE mail_queue SET detail='Scheduled time was missed. Review and resume when ready.' WHERE job_id=?",
                    (job_id,),
                )
                return None
            db.execute(
                "UPDATE send_jobs SET status='sending',started_at=? WHERE job_id=?",
                (stamp(now), job_id),
            )
            db.execute(
                "UPDATE mail_queue SET revision=revision+1 WHERE job_id=?", (job_id,)
            )
        return self.job(job_id)

    def begin_route(self, job_id, index):
        with self.connect(True) as db:
            row = db.execute(
                "SELECT cancelled,folder FROM mail_queue WHERE job_id=?", (job_id,)
            ).fetchone()
            if not row or row["cancelled"] or row["folder"] != "outbox":
                return False
            return (
                db.execute(
                    "UPDATE send_job_routes SET status='sending',updated_at=? WHERE job_id=? AND route_index=? AND status IN ('pending','authentication_required','retry')",
                    (stamp(), job_id, index),
                ).rowcount
                == 1
            )

    def route_result(self, job_id, index, status, detail):
        with self.connect(True) as db:
            db.execute(
                "UPDATE send_job_routes SET status=?,detail=?,updated_at=? WHERE job_id=? AND route_index=? AND status!='accepted'",
                (status, detail, stamp(), job_id, index),
            )

    def stop_job(self, job_id, status, detail, retry_seconds=60):
        with self.connect(True) as db:
            q = self._queue_row(db, job_id)
            if q["cancelled"] or q["folder"] == "trash":
                status = "cancelled" if q["folder"] == "trash" else "paused"
                detail = q["detail"]
            db.execute("UPDATE send_jobs SET status=? WHERE job_id=?", (status, job_id))
            db.execute(
                "UPDATE mail_queue SET detail=?,revision=revision+1 WHERE job_id=?",
                (detail, job_id),
            )
            if status == "retry":
                db.execute(
                    "UPDATE mail_queue SET run_at=? WHERE job_id=?",
                    (stamp(now_utc() + timedelta(seconds=retry_seconds)), job_id),
                )

    def finish_job(self, job_id, now=None):
        now = now or now_utc()
        with self.connect(True) as db:
            current = db.execute(
                "SELECT status FROM send_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if current is None or current["status"] == "completed":
                return
            q = db.execute(
                "SELECT * FROM mail_queue WHERE job_id=?", (job_id,)
            ).fetchone()
            if q is None:
                return
            states = [
                r[0]
                for r in db.execute(
                    "SELECT status FROM send_job_routes WHERE job_id=?", (job_id,)
                )
            ]
            if q["folder"] == "trash":
                status = "cancelled"
            elif "unknown" in states or "sending" in states:
                status = "needs_review"
            elif states and all(s == "accepted" for s in states):
                status = "completed"
            elif q["cancelled"]:
                status = "paused"
            elif "failed" in states:
                status = "partial"
            else:
                status = "paused"
            db.execute(
                "UPDATE send_jobs SET status=?,completed_at=? WHERE job_id=?",
                (status, stamp(now), job_id),
            )
            db.execute(
                "UPDATE mail_queue SET revision=revision+1 WHERE job_id=?", (job_id,)
            )
            if status != "completed":
                return
            db.execute(
                "UPDATE mail_queue SET folder='sent',detail='Accepted by Microsoft. See Sent for mailbox copies.' WHERE job_id=?",
                (job_id,),
            )
            if not q["series_id"]:
                return
            rule = ScheduleRule.model_validate_json(q["rule_json"])
            following = next_occurrence(rule, q["occurrence_index"], now)
            if following is None:
                return
            index, due = following
            # A new immutable preview and unique occurrence are created in the same transaction.
            old = db.execute(
                "SELECT p.* FROM email_previews p JOIN send_jobs j ON j.preview_id=p.preview_id WHERE j.job_id=?",
                (job_id,),
            ).fetchone()
            preview_id = str(uuid7())
            db.execute(
                "INSERT INTO email_previews VALUES(?,?,?,?,?,?,?)",
                (
                    preview_id,
                    old["sender"],
                    old["subject"],
                    old["content"],
                    old["workbook_version"],
                    old["recipients_json"],
                    stamp(now),
                ),
            )
            next_job_id = self._insert_job(
                db, preview_id, due, q["rule_json"], q["series_id"], index
            )

            if q["cancelled"]:
                db.execute(
                    "UPDATE mail_queue SET cancelled=1,detail='Schedule paused.' WHERE job_id=?",
                    (next_job_id,),
                )
                db.execute(
                    "UPDATE send_jobs SET status='paused' WHERE job_id=?",
                    (next_job_id,),
                )

    def remember_origin(self, message_id, folder_id, folder_name):
        with self.connect(True) as db:
            db.execute(
                "INSERT INTO mail_trash_origins VALUES(?,?,?,?) ON CONFLICT(message_id) DO UPDATE SET folder_id=excluded.folder_id,folder_name=excluded.folder_name,updated_at=excluded.updated_at",
                (message_id, folder_id, folder_name, stamp()),
            )

    def origin(self, message_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM mail_trash_origins WHERE message_id=?", (message_id,)
            ).fetchone()
        return dict(row) if row else None

    def forget_origin(self, message_id):
        with self.connect(True) as db:
            db.execute(
                "DELETE FROM mail_trash_origins WHERE message_id=?", (message_id,)
            )
