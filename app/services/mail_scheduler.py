"""One local scheduler per database; never retry an ambiguous send."""

import asyncio
import logging
import os
from contextlib import suppress

from app.services import graph_service, mail_graph, microsoft_auth_service
from app.services.mail_store import MailStore, now_utc

logger = logging.getLogger(__name__)


class WorkerLock:
    """OS lock is released after a crash, without expiring under a live worker."""

    def __init__(self, path):
        self.path = path
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.seek(0, 2) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.file = handle
        return True

    def close(self):
        if self.file:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            self.file = None


async def process_job(store, job, settings):
    job_id = job["id"]
    try:
        token = await asyncio.to_thread(
            microsoft_auth_service.acquire_access_token_silent
        )
        sender = await graph_service.get_sender_email(
            access_token=token,
            expected_sender_email=settings.microsoft_fixed_sender_email,
        )
        if sender.casefold() != (job["sender"] or "").casefold():
            store.stop_job(
                job_id,
                "needs_review",
                "The configured sender changed. Create a new preview.",
            )
            return
    except (
        microsoft_auth_service.MicrosoftAuthenticationRequired,
        microsoft_auth_service.MicrosoftAuthConfigurationError,
        graph_service.GraphAuthenticationError,
    ):
        store.stop_job(
            job_id,
            "authentication_required",
            "Sign in to Microsoft, then resume this item.",
        )
        return
    except graph_service.GraphRequestError:
        store.stop_job(
            job_id,
            "retry",
            "Sender could not be checked. Retrying before any submission.",
        )
        return
    eligible = {"pending", "authentication_required", "retry"}
    for result, recipient in zip(job["results"], job["recipients"], strict=True):
        index = result["route_index"]
        if result["status"] not in eligible:
            continue
        if not store.begin_route(job_id, index):
            break
        try:
            await mail_graph.send_route(
                token, job["subject"], job["content"], recipient
            )
        except mail_graph.MailGraphError as exc:
            if exc.status == 401:
                store.route_result(job_id, index, "authentication_required", str(exc))
                store.stop_job(
                    job_id,
                    "authentication_required",
                    "Sign in, then resume. Accepted routes will be skipped.",
                )
                return
            if exc.status == 429:
                store.route_result(job_id, index, "retry", str(exc))
                store.stop_job(job_id, "retry", str(exc), exc.retry_after)
                return
            store.route_result(
                job_id, index, "unknown" if exc.uncertain else "failed", str(exc)
            )
            if exc.uncertain:
                break
        else:
            store.route_result(
                job_id,
                index,
                "accepted",
                "Accepted by Microsoft Graph; delivery is not yet confirmed.",
            )
    store.finish_job(job_id)


async def scheduler_loop(store, settings):
    lock = WorkerLock(settings.send_job_db_file.with_suffix(".worker.lock"))
    if not lock.acquire():
        logger.info("Another process owns the mail scheduler.")
        return
    try:
        store.recover_interrupted()
        while True:
            job = None
            try:
                job = store.claim_due(now_utc(), settings.schedule_late_grace_seconds)
                if job:
                    await process_job(store, job, settings)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                # Preserve durable in-flight state. Recovery will require review, never resend.
                logger.exception("Mail scheduler paused an unexpected failure.")
                if job:
                    store.recover_interrupted()
            await asyncio.sleep(settings.scheduler_poll_seconds)
    finally:
        lock.close()


async def start_scheduler(app, settings):
    store = MailStore(settings.send_job_db_file)
    app.state.mail_store = store
    app.state.scheduler_task = None
    if settings.scheduler_enabled and settings.environment != "test":
        app.state.scheduler_task = asyncio.create_task(scheduler_loop(store, settings))


async def stop_scheduler(app):
    task = getattr(app.state, "scheduler_task", None)
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
