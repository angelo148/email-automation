import asyncio
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.routing import APIRoute

from app.core.config import get_settings
from app.schemas.mailbox import (
    BulkAction,
    DraftInput,
    MessageAction,
    ScheduleEdit,
    SubmitPreview,
)
from app.services import mail_graph, microsoft_auth_service
from app.services.mail_store import MailConflict, MailStore
from app.services.send_job_service import calculate_workbook_version, get_preview


class MailRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def checked(request):
            try:
                return await handler(request)
            except mail_graph.MailGraphError as exc:
                raise HTTPException(
                    exc.status,
                    str(exc),
                    headers=(
                        {"Retry-After": str(exc.retry_after)}
                        if exc.status == 429
                        else None
                    ),
                ) from exc
            except MailConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

        return checked


async def browser_request(request: Request):
    if request.method not in {"GET", "HEAD"}:
        if request.headers.get("X-Mail-Client") != "1":
            raise HTTPException(403, "Use the mailbox interface for this action.")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-origin mailbox actions are not allowed.")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site mailbox actions are not allowed.")


router = APIRouter(
    prefix="/mail",
    tags=["Mailbox"],
    route_class=MailRoute,
    dependencies=[Depends(browser_request)],
)


def get_store(request: Request):
    if not hasattr(request.app.state, "mail_store"):
        request.app.state.mail_store = MailStore(get_settings().send_job_db_file)
    return request.app.state.mail_store


async def get_token():
    try:
        return await asyncio.to_thread(
            microsoft_auth_service.acquire_access_token_silent
        )
    except (
        microsoft_auth_service.MicrosoftAuthenticationRequired,
        microsoft_auth_service.MicrosoftAuthConfigurationError,
    ) as exc:
        raise HTTPException(
            401, "Connect your Microsoft account to open this folder."
        ) from exc


Store = Annotated[MailStore, Depends(get_store)]


@router.get("/folders/{folder}")
async def list_folder(
    folder: Literal["inbox", "outbox", "sent", "drafts", "trash"],
    store: Store,
    q: str = Query(default="", max_length=200),
    cursor: str | None = Query(default=None, max_length=8000),
):
    local = []
    if folder in {"outbox", "drafts", "trash"} and not cursor:
        local = store.list_local(folder)
        if q:
            local = [
                m
                for m in local
                if q.casefold() in (m["subject"] + " " + m["content"]).casefold()
            ]
    result = {"items": [], "next_cursor": None}
    warning = None
    if folder in mail_graph.FOLDERS:
        try:
            token = await get_token()
            result = await mail_graph.list_messages(token, folder, cursor, q)
        except (HTTPException, mail_graph.MailGraphError) as exc:
            if folder != "trash":
                raise
            warning = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
    for message in result["items"]:
        message["folder"] = folder
        if folder == "trash":
            origin = store.origin(message["id"])
            message["original_folder"] = origin["folder_name"] if origin else None
    items = sorted(
        local + result["items"], key=lambda m: m.get("date") or "", reverse=True
    )
    return {"items": items, "next_cursor": result["next_cursor"], "warning": warning}


@router.get("/message")
async def open_message(id: str = Query(min_length=1, max_length=2048)):
    token = await get_token()
    return await mail_graph.get_message(token, id)


@router.get("/drafts/{draft_id}")
def open_draft(draft_id: UUID, store: Store):
    return store.draft(draft_id)


@router.post("/drafts")
def new_draft(payload: DraftInput, store: Store):
    return store.save_draft(payload)


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: UUID, payload: DraftInput, store: Store):
    return store.save_draft(payload, draft_id)


@router.get("/jobs/{job_id}")
def open_job(job_id: UUID, store: Store, current: bool = False):
    return store.job(job_id, current=current)


@router.put("/jobs/{job_id}/schedule")
def edit_schedule(job_id: UUID, payload: ScheduleEdit, store: Store):
    return store.edit_schedule(job_id, payload.schedule, payload.revision)


@router.post("/submit", status_code=202)
def submit_preview(payload: SubmitPreview, store: Store):
    # Repeated submissions return the same queue item, even if the workbook later changes.
    with store.connect() as db:
        exists = db.execute(
            "SELECT 1 FROM send_jobs WHERE preview_id=?", (str(payload.preview_id),)
        ).fetchone()
    if not exists:
        preview = get_preview(database_path=store.path, preview_id=payload.preview_id)
        try:
            current = calculate_workbook_version(get_settings().companies_file)
        except FileNotFoundError as exc:
            raise HTTPException(
                409, "The recipient workbook is missing. Restore it and preview again."
            ) from exc
        if current != preview.workbook_version:
            raise MailConflict(
                "Recipient data changed. Create a new preview before submitting."
            )
        if (
            str(preview.sender) if preview.sender else ""
        ).casefold() != get_settings().microsoft_fixed_sender_email.casefold():
            raise MailConflict("The sender changed. Create a new preview.")
    return store.enqueue(
        payload.preview_id, payload.schedule, payload.draft_id, payload.draft_revision
    )


async def apply_action(item: MessageAction, store, token=None):
    if item.kind != "graph":
        return store.local_action(item.kind, item.id, item.action) or item.id
    token = token or await get_token()
    if item.action in {"read", "unread"}:
        await mail_graph.mark_read(token, item.id, item.action == "read")
        return
    if item.action not in {"trash", "restore", "delete"}:
        raise MailConflict("This action is not available for a Microsoft message.")
    message = await mail_graph.get_message(token, item.id)
    deleted = await mail_graph.folder_info(token, "deleteditems")
    if item.action == "delete":
        if message["parent_folder_id"] != deleted["id"]:
            raise MailConflict("Only messages in Trash can be permanently deleted.")
        await mail_graph.delete_message(token, item.id)
        store.forget_origin(item.id)
        return
    if item.action == "trash":
        if message["parent_folder_id"] == deleted["id"]:
            return
        original = await mail_graph.folder_info(token, message["parent_folder_id"])
        store.remember_origin(item.id, original["id"], original["displayName"])
        await mail_graph.move_message(token, item.id, "deleteditems")
    else:
        origin = store.origin(item.id)
        target = origin["folder_id"] if origin else item.destination
        if not target:
            raise MailConflict(
                "This message was deleted outside this app. Choose Inbox or Sent when restoring."
            )
        if message["parent_folder_id"] != deleted["id"]:
            # A repeated restore must not move an already-restored item again.
            return
        await mail_graph.move_message(token, item.id, target)


@router.post("/actions")
async def perform_actions(payload: BulkAction, store: Store):
    results = []
    token = None
    for item in payload.items:
        try:
            if item.kind == "graph" and token is None:
                token = await get_token()
            effective_id = await apply_action(item, store, token) or item.id
            results.append({"id": item.id, "effective_id": effective_id, "ok": True})
        except (
            MailConflict,
            LookupError,
            mail_graph.MailGraphError,
            HTTPException,
        ) as exc:
            detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
            results.append({"id": item.id, "ok": False, "detail": detail})
    return {"results": results}
