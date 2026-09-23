import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from app.schemas.email import (
    EmailJobResponse,
    EmailJobRouteResult,
    EmailJobStatus,
    EmailPreviewRecipient,
    EmailRouteStatus,
    SavedEmailPreview,
)


class PreviewNotFoundError(LookupError):
    """Raised when a requested saved preview does not exist."""


class SendJobNotFoundError(LookupError):
    """Raised when a requested send job does not exist."""


@dataclass(frozen=True)
class SendJobClaim:
    """Result of attempting to claim one preview for sending."""

    job_id: UUID
    claimed: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _serialize_datetime(value: datetime) -> str:
    return value.isoformat()


@contextmanager
def _connect(
    database_path: Path,
):
    database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        database_path,
        timeout=10.0,
    )

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_send_job_store(
    database_path: Path,
) -> None:
    """Create the local preview/job database if required."""

    with _connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS email_previews (
                preview_id TEXT PRIMARY KEY,
                sender TEXT,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                delivery_mode TEXT NOT NULL DEFAULT 'separate',
                workbook_version TEXT NOT NULL,
                recipients_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS send_jobs (
                job_id TEXT PRIMARY KEY,
                preview_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,

                FOREIGN KEY (preview_id)
                    REFERENCES email_previews(preview_id)
            );

            CREATE TABLE IF NOT EXISTS send_job_routes (
                job_id TEXT NOT NULL,
                route_index INTEGER NOT NULL,
                source_row INTEGER NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                updated_at TEXT NOT NULL,

                PRIMARY KEY (
                    job_id,
                    route_index
                ),

                FOREIGN KEY (job_id)
                    REFERENCES send_jobs(job_id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS
                idx_send_jobs_preview_id
            ON send_jobs(preview_id);

            CREATE INDEX IF NOT EXISTS
                idx_send_job_routes_job_id
            ON send_job_routes(job_id);
            """)

        preview_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(email_previews)")
        }
        if "delivery_mode" not in preview_columns:
            connection.execute(
                "ALTER TABLE email_previews ADD COLUMN delivery_mode TEXT NOT NULL DEFAULT 'separate'"
            )


def calculate_workbook_version(
    file_path: Path,
) -> str:
    """
    Calculate an immutable content fingerprint for the workbook.

    A SHA-256 content hash is deliberately used instead of only modification
    time so replacing the workbook cannot silently preserve the same version.
    """

    digest = hashlib.sha256()

    with file_path.open("rb") as workbook:
        while chunk := workbook.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def save_preview(
    *,
    database_path: Path,
    sender: str | None,
    subject: str,
    content: str,
    recipients: list[EmailPreviewRecipient],
    workbook_version: str,
) -> SavedEmailPreview:
    """Persist an immutable reviewed email preview."""

    initialize_send_job_store(database_path)

    preview_id = uuid4()
    created_at = _utc_now()

    recipients_json = json.dumps(
        [recipient.model_dump(mode="json") for recipient in recipients],
        separators=(",", ":"),
    )

    with _connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO email_previews (
                preview_id,
                sender,
                subject,
                content,
                workbook_version,
                recipients_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(preview_id),
                sender,
                subject,
                content,
                workbook_version,
                recipients_json,
                _serialize_datetime(created_at),
            ),
        )

    return SavedEmailPreview(
        preview_id=preview_id,
        sender=sender,
        subject=subject,
        content=content,
        workbook_version=workbook_version,
        recipient_count=len(recipients),
        recipients=recipients,
        created_at=created_at,
    )


def get_preview(
    *,
    database_path: Path,
    preview_id: UUID,
) -> SavedEmailPreview:
    """Retrieve one saved immutable preview."""

    initialize_send_job_store(database_path)

    with _connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT
                preview_id,
                sender,
                subject,
                content,
                delivery_mode,
                workbook_version,
                recipients_json,
                created_at
            FROM email_previews
            WHERE preview_id = ?
            """,
            (str(preview_id),),
        ).fetchone()

    if row is None:
        raise PreviewNotFoundError("The requested preview does not exist.")

    raw_recipients = json.loads(row["recipients_json"])

    recipients = [EmailPreviewRecipient.model_validate(item) for item in raw_recipients]

    return SavedEmailPreview(
        preview_id=UUID(row["preview_id"]),
        sender=row["sender"],
        subject=row["subject"],
        content=row["content"],
        delivery_mode=row["delivery_mode"],
        workbook_version=row["workbook_version"],
        recipient_count=len(recipients),
        recipients=recipients,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def claim_send_job(
    *,
    database_path: Path,
    preview_id: UUID,
) -> SendJobClaim:
    """
    Atomically claim a preview for sending.

    Exactly one send job may exist for a preview.

    A new preview creates a new job. A job waiting for Microsoft
    authentication may be atomically reclaimed so its unfinished routes
    can resume. All other repeated/concurrent requests receive the
    existing job without claiming it.
    """

    initialize_send_job_store(database_path)

    connection = sqlite3.connect(database_path, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        connection.execute("BEGIN IMMEDIATE")

        preview_row = connection.execute(
            """
            SELECT
                preview_id,
                recipients_json
            FROM email_previews
            WHERE preview_id = ?
            """,
            (str(preview_id),),
        ).fetchone()

        if preview_row is None:
            connection.rollback()

            raise PreviewNotFoundError("The requested preview does not exist.")

        existing_job = connection.execute(
            """
            SELECT
                job_id,
                status
            FROM send_jobs
            WHERE preview_id = ?
            """,
            (str(preview_id),),
        ).fetchone()

        if existing_job is not None:
            job_id = UUID(existing_job["job_id"])

            # Mailbox jobs are exclusively owned by the persistent scheduler.
            # The compatibility endpoint must never bypass a future due time.
            has_queue = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_queue'"
            ).fetchone()
            if (
                has_queue
                and connection.execute(
                    "SELECT 1 FROM mail_queue WHERE job_id=?", (str(job_id),)
                ).fetchone()
            ):
                connection.commit()
                return SendJobClaim(job_id=job_id, claimed=False)

            if existing_job["status"] == EmailJobStatus.AUTHENTICATION_REQUIRED.value:
                now = _utc_now()

                result = connection.execute(
                    """
                    UPDATE send_jobs
                    SET
                        status = ?,
                        started_at = ?,
                        completed_at = NULL
                    WHERE
                        job_id = ?
                        AND status = ?
                    """,
                    (
                        EmailJobStatus.SENDING.value,
                        _serialize_datetime(now),
                        str(job_id),
                        EmailJobStatus.AUTHENTICATION_REQUIRED.value,
                    ),
                )

                connection.commit()

                return SendJobClaim(
                    job_id=job_id,
                    claimed=result.rowcount == 1,
                )

            connection.commit()

            return SendJobClaim(
                job_id=job_id,
                claimed=False,
            )

        job_id = uuid4()
        now = _utc_now()

        connection.execute(
            """
            INSERT INTO send_jobs (
                job_id,
                preview_id,
                status,
                created_at,
                started_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(job_id),
                str(preview_id),
                EmailJobStatus.SENDING.value,
                _serialize_datetime(now),
                _serialize_datetime(now),
            ),
        )

        recipients = json.loads(preview_row["recipients_json"])

        for route_index, recipient in enumerate(recipients):
            connection.execute(
                """
                INSERT INTO send_job_routes (
                    job_id,
                    route_index,
                    source_row,
                    name,
                    status,
                    detail,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(job_id),
                    route_index,
                    recipient["source_row"],
                    recipient["name"],
                    EmailRouteStatus.PENDING.value,
                    None,
                    _serialize_datetime(now),
                ),
            )

        connection.commit()

        return SendJobClaim(
            job_id=job_id,
            claimed=True,
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def record_route_status(
    *,
    database_path: Path,
    job_id: UUID,
    route_index: int,
    status: EmailRouteStatus,
    detail: str | None = None,
) -> None:
    """Persist one route result immediately."""

    with _connect(database_path) as connection:
        result = connection.execute(
            """
            UPDATE send_job_routes
            SET
                status = ?,
                detail = ?,
                updated_at = ?
            WHERE
                job_id = ?
                AND route_index = ?
                AND status != ?
            """,
            (
                status.value,
                detail,
                _serialize_datetime(_utc_now()),
                str(job_id),
                route_index,
                EmailRouteStatus.ACCEPTED.value,
            ),
        )

    if result.rowcount == 0:
        return


def mark_pending_routes_authentication_required(
    *,
    database_path: Path,
    job_id: UUID,
) -> None:
    """Mark all unsent routes as waiting for Microsoft authentication."""

    now = _serialize_datetime(_utc_now())

    with _connect(database_path) as connection:
        connection.execute(
            """
            UPDATE send_job_routes
            SET
                status = ?,
                detail = ?,
                updated_at = ?
            WHERE
                job_id = ?
                AND status = ?
            """,
            (
                EmailRouteStatus.AUTHENTICATION_REQUIRED.value,
                "Microsoft sign-in is required before this route can continue.",
                now,
                str(job_id),
                EmailRouteStatus.PENDING.value,
            ),
        )

        connection.execute(
            """
            UPDATE send_jobs
            SET status = ?
            WHERE job_id = ?
            """,
            (
                EmailJobStatus.AUTHENTICATION_REQUIRED.value,
                str(job_id),
            ),
        )


def finalize_send_job(
    *,
    database_path: Path,
    job_id: UUID,
) -> None:
    """Derive and persist the overall job state from its route states."""

    response = get_send_job(
        database_path=database_path,
        job_id=job_id,
    )

    if response.authentication_required > 0:
        status = EmailJobStatus.AUTHENTICATION_REQUIRED

    elif response.unknown > 0:
        status = EmailJobStatus.NEEDS_REVIEW

    elif response.pending > 0:
        status = EmailJobStatus.SENDING

    elif response.accepted > 0 and response.failed > 0:
        status = EmailJobStatus.PARTIAL

    else:
        status = EmailJobStatus.COMPLETED

    completed_at = (
        None
        if status
        in {
            EmailJobStatus.SENDING,
            EmailJobStatus.AUTHENTICATION_REQUIRED,
        }
        else _serialize_datetime(_utc_now())
    )

    with _connect(database_path) as connection:
        connection.execute(
            """
            UPDATE send_jobs
            SET
                status = ?,
                completed_at = ?
            WHERE job_id = ?
            """,
            (
                status.value,
                completed_at,
                str(job_id),
            ),
        )


def get_send_job(
    *,
    database_path: Path,
    job_id: UUID,
) -> EmailJobResponse:
    """Return the current persisted state of one send job."""

    initialize_send_job_store(database_path)

    with _connect(database_path) as connection:
        job = connection.execute(
            """
            SELECT
                j.job_id,
                j.preview_id,
                j.status,
                j.created_at,
                j.started_at,
                j.completed_at,
                p.sender
            FROM send_jobs AS j
            JOIN email_previews AS p
                ON p.preview_id = j.preview_id
            WHERE j.job_id = ?
            """,
            (str(job_id),),
        ).fetchone()

        if job is None:
            raise SendJobNotFoundError("The requested send job does not exist.")

        route_rows = connection.execute(
            """
            SELECT
                route_index,
                source_row,
                name,
                status,
                detail
            FROM send_job_routes
            WHERE job_id = ?
            ORDER BY route_index
            """,
            (str(job_id),),
        ).fetchall()

    results = [
        EmailJobRouteResult(
            route_index=row["route_index"],
            source_row=row["source_row"],
            name=row["name"],
            status=EmailRouteStatus(row["status"]),
            detail=row["detail"],
        )
        for row in route_rows
    ]

    counts = {
        status: sum(result.status == status for result in results)
        for status in EmailRouteStatus
    }

    return EmailJobResponse(
        job_id=UUID(job["job_id"]),
        preview_id=UUID(job["preview_id"]),
        sender=job["sender"],
        status=EmailJobStatus(job["status"]),
        total=len(results),
        pending=counts[EmailRouteStatus.PENDING],
        accepted=counts[EmailRouteStatus.ACCEPTED],
        failed=counts[EmailRouteStatus.FAILED],
        unknown=counts[EmailRouteStatus.UNKNOWN],
        authentication_required=counts[EmailRouteStatus.AUTHENTICATION_REQUIRED],
        results=results,
        created_at=datetime.fromisoformat(job["created_at"]),
        started_at=(
            datetime.fromisoformat(job["started_at"]) if job["started_at"] else None
        ),
        completed_at=(
            datetime.fromisoformat(job["completed_at"]) if job["completed_at"] else None
        ),
    )


def get_send_job_for_preview(
    *,
    database_path: Path,
    preview_id: UUID,
) -> EmailJobResponse | None:
    """Return the existing send job for a preview, if one exists."""

    initialize_send_job_store(database_path)

    with _connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT job_id
            FROM send_jobs
            WHERE preview_id = ?
            """,
            (str(preview_id),),
        ).fetchone()

    if row is None:
        return None

    return get_send_job(
        database_path=database_path,
        job_id=UUID(row["job_id"]),
    )
