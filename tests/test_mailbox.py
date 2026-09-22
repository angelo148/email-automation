# Schedule inputs intentionally use local times with a separate timezone.
# ruff: noqa: DTZ001

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.routes import mailbox as routes
from app.schemas.email import EmailPreviewRecipient
from app.schemas.mailbox import DraftInput, ScheduleRule
from app.services import graph_service, mail_graph, mail_scheduler
from app.services.mail_scheduler import WorkerLock, process_job
from app.services.mail_store import MailConflict, MailStore, now_utc
from app.services.recurrence import local_to_utc, next_occurrence, occurrence
from app.services.send_job_service import claim_send_job, save_preview


@pytest.fixture
def store(tmp_path):
    return MailStore(tmp_path / "send_jobs.sqlite3")


def preview(store, count=2):
    return save_preview(
        database_path=store.path,
        sender="sender@example.com",
        subject="Service update",
        content="Predefined content",
        workbook_version="fingerprint",
        recipients=[
            EmailPreviewRecipient(
                source_row=i + 2,
                module="Service",
                name=f"Route {i}",
                third_party_group="Partner",
                to=[f"recipient{i}@example.com"],
                cc=["copy@example.com"],
            )
            for i in range(count)
        ],
    )


@pytest.fixture
def client(store):
    app = create_app()
    app.dependency_overrides[routes.get_store] = lambda: store
    return TestClient(app, headers={"X-Mail-Client": "1"})


@pytest.fixture
def fake_sender(monkeypatch):
    monkeypatch.setattr(
        mail_scheduler.microsoft_auth_service,
        "acquire_access_token_silent",
        lambda: "fake-token",
    )

    async def sender(**kwargs):
        return "sender@example.com"

    monkeypatch.setattr(graph_service, "get_sender_email", sender)
    return Settings(
        environment="test", microsoft_fixed_sender_email="sender@example.com"
    )


def test_inbox_shell_does_not_require_workbook(client):
    response = client.get("/")
    assert response.status_code == 200
    for folder in ("inbox", "outbox", "sent", "drafts", "trash"):
        assert f'data-folder="{folder}"' in response.text
    assert 'id="compose-button"' in response.text
    assert 'id="delete-confirm-dialog"' in response.text
    assert 'id="permanently-delete-selected"' in response.text
    assert "Delete selected" in response.text


def test_draft_roundtrip_and_optimistic_edit(client, store):
    response = client.post(
        "/mail/drafts",
        json={"subject": "Draft", "content": "", "selected_company_rows": [2, 2]},
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["selected_company_rows"] == [2]
    payload = {"subject": "Revised", "revision": draft["revision"]}
    assert client.put(f'/mail/drafts/{draft["id"]}', json=payload).status_code == 200
    assert client.put(f'/mail/drafts/{draft["id"]}', json=payload).status_code == 409
    store.local_action("draft", draft["id"], "trash")
    assert store.list_local("drafts") == []
    store.local_action("draft", draft["id"], "restore")
    assert store.list_local("drafts")[0]["subject"] == "Revised"
    assert MailStore(store.path).draft(draft["id"])["content"] == ""


def test_trashed_draft_can_be_permanently_deleted(store):
    draft = store.save_draft(DraftInput(subject="Delete me"))
    store.local_action("draft", draft["id"], "trash")
    store.local_action("draft", draft["id"], "delete")
    with pytest.raises(LookupError):
        store.draft(draft["id"])


def test_mailbox_rejects_cross_origin_mutation(client):
    assert (
        client.post(
            "/mail/drafts", json={}, headers={"Origin": "https://unrelated.example"}
        ).status_code
        == 403
    )
    client.headers.pop("X-Mail-Client")
    assert client.post("/mail/drafts", json={}).status_code == 403


def test_enqueue_is_atomic_and_legacy_claim_cannot_send_early(store):
    saved = preview(store)
    rule = ScheduleRule(
        start=datetime(2028, 1, 1, 12), timezone="UTC", frequency="daily"
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = list(pool.map(lambda _: store.enqueue(saved.preview_id, rule), range(4)))
    assert len({job["id"] for job in jobs}) == 1
    assert len(store.list_local("outbox")) == 1
    assert not claim_send_job(
        database_path=store.path, preview_id=saved.preview_id
    ).claimed
    assert store.claim_due(datetime(2027, 1, 1, tzinfo=UTC), 300) is None


def test_deleted_job_cannot_run_and_restore_stays_paused(store):
    job = store.enqueue(preview(store).preview_id)
    store.local_action("job", job["id"], "trash")
    assert store.claim_due(now_utc(), 300) is None
    store.local_action("job", job["id"], "restore")
    assert store.job(job["id"])["folder"] == "outbox"
    assert store.job(job["id"])["status"] == "paused"
    assert store.claim_due(now_utc(), 300) is None
    store.local_action("job", job["id"], "resume")
    assert store.claim_due(now_utc(), 300)["id"] == job["id"]


def test_late_job_does_not_send_after_unattended_restart(store):
    job = store.enqueue(preview(store).preview_id)
    assert store.claim_due(now_utc() + timedelta(hours=1), 300) is None
    assert store.job(job["id"])["status"] == "paused"


def test_calendar_month_end_uses_original_anchor():
    rule = ScheduleRule(
        start=datetime(2027, 1, 31, 9), timezone="UTC", frequency="monthly"
    )
    assert occurrence(rule, 1) == datetime(2027, 2, 28, 9, tzinfo=UTC)
    assert occurrence(rule, 2) == datetime(2027, 3, 31, 9, tzinfo=UTC)


def test_dst_keeps_wall_clock_and_skips_missing_hour():
    rule = ScheduleRule(
        start=datetime(2027, 3, 13, 9), timezone="America/New_York", frequency="daily"
    )
    assert occurrence(rule, 0).hour == 14
    assert occurrence(rule, 1).hour == 13
    with pytest.raises(ValueError, match="does not exist"):
        local_to_utc(datetime(2027, 3, 14, 2, 30), "America/New_York")
    missing = ScheduleRule(
        start=datetime(2027, 3, 13, 2, 30),
        timezone="America/New_York",
        frequency="daily",
    )
    assert next_occurrence(missing, 0, occurrence(missing, 0))[0] == 2
    repeated = local_to_utc(datetime(2027, 11, 7, 1, 30), "America/New_York")
    assert repeated == datetime(2027, 11, 7, 5, 30, tzinfo=UTC)


def test_recurrence_skips_backlog_and_obeys_end_date():
    rule = ScheduleRule(
        start=datetime(2027, 1, 1, 9),
        timezone="UTC",
        frequency="weekly",
        interval=2,
        end_date="2027-03-01",
    )
    index, due = next_occurrence(rule, 0, datetime(2027, 2, 1, tzinfo=UTC))
    assert index == 3 and due == datetime(2027, 2, 12, 9, tzinfo=UTC)
    assert next_occurrence(rule, index, datetime(2027, 3, 1, tzinfo=UTC)) is None


def test_auth_resume_keeps_accepted_routes(store, fake_sender, monkeypatch):
    job = store.enqueue(preview(store).preview_id)
    job = store.claim_due(now_utc(), 300)
    sent = []

    async def send(token, subject, content, recipient):
        sent.append(recipient["to"][0])
        if len(sent) == 2:
            raise mail_graph.MailGraphError("Sign in", 401)

    monkeypatch.setattr(mail_graph, "send_route", send)
    asyncio.run(process_job(store, job, fake_sender))
    current = store.job(job["id"])
    assert current["status"] == "authentication_required"
    assert current["results"][0]["status"] == "accepted"
    store.local_action("job", job["id"], "resume")
    asyncio.run(process_job(store, store.claim_due(now_utc(), 300), fake_sender))
    assert sent == [
        "recipient0@example.com",
        "recipient1@example.com",
        "recipient1@example.com",
    ]
    assert store.job(job["id"])["status"] == "completed"


def test_uncertain_send_is_not_retried(store, fake_sender, monkeypatch):
    job = store.enqueue(preview(store).preview_id)

    async def send(*args):
        raise mail_graph.MailGraphError("Response lost", uncertain=True)

    monkeypatch.setattr(mail_graph, "send_route", send)
    asyncio.run(process_job(store, store.claim_due(now_utc(), 300), fake_sender))
    assert store.job(job["id"])["results"][0]["status"] == "unknown"
    assert store.job(job["id"])["results"][1]["status"] == "pending"
    with pytest.raises(MailConflict):
        store.local_action("job", job["id"], "resume")
    assert store.claim_due(now_utc(), 300) is None


def test_429_is_delayed_and_preserves_prior_acceptance(store, fake_sender, monkeypatch):
    job = store.enqueue(preview(store).preview_id)
    calls = []

    async def send(*args):
        calls.append(args[-1]["to"][0])
        if len(calls) == 2:
            raise mail_graph.MailGraphError("Throttled", 429, retry_after=120)

    monkeypatch.setattr(mail_graph, "send_route", send)
    asyncio.run(process_job(store, store.claim_due(now_utc(), 300), fake_sender))
    assert store.job(job["id"])["status"] == "retry"
    assert store.claim_due(now_utc(), 300) is None
    asyncio.run(
        process_job(
            store, store.claim_due(now_utc() + timedelta(seconds=121), 300), fake_sender
        )
    )
    assert calls == [
        "recipient0@example.com",
        "recipient1@example.com",
        "recipient1@example.com",
    ]


def test_crash_marks_inflight_unknown_and_does_not_resend(store):
    job = store.enqueue(preview(store).preview_id)
    store.claim_due(now_utc(), 300)
    assert store.begin_route(job["id"], 0)
    store.recover_interrupted()
    current = store.job(job["id"])
    assert current["status"] == "needs_review"
    assert current["results"][0]["status"] == "unknown"
    assert store.claim_due(now_utc(), 300) is None


def test_recurring_completion_creates_exactly_one_next_occurrence(
    store, fake_sender, monkeypatch
):
    rule = ScheduleRule(
        start=datetime(2028, 1, 1, 9), timezone="UTC", frequency="daily"
    )
    job = store.enqueue(preview(store).preview_id, rule)

    async def send(*args):
        pass

    monkeypatch.setattr(mail_graph, "send_route", send)
    asyncio.run(
        process_job(
            store,
            store.claim_due(datetime(2028, 1, 1, 9, tzinfo=UTC), 300),
            fake_sender,
        )
    )
    queued = store.list_local("outbox")
    assert len(queued) == 1
    assert queued[0]["id"] != job["id"]
    assert queued[0]["recipients"] == job["recipients"]
    assert queued[0]["schedule"] == job["schedule"]
    store.finish_job(job["id"])
    assert len(store.list_local("outbox")) == 1
    active = store.job(job["id"], current=True)

    assert active["folder"] == "outbox"

    store.local_action("job", active["id"], "trash")

    assert store.job(active["id"])["folder"] == "trash"
    assert store.claim_due(now_utc(), 300) is None


def test_pause_during_send_stops_remaining_routes(store, fake_sender, monkeypatch):
    job = store.enqueue(preview(store).preview_id)
    sent = []

    async def send(*args):
        sent.append(args[-1]["to"][0])
        store.local_action("job", job["id"], "trash")

    monkeypatch.setattr(mail_graph, "send_route", send)
    asyncio.run(process_job(store, store.claim_due(now_utc(), 300), fake_sender))
    assert len(sent) == 1
    assert store.job(job["id"])["folder"] == "trash"
    assert store.job(job["id"])["results"][0]["status"] == "accepted"


def test_worker_lock_is_exclusive_and_released(tmp_path):
    a, b = WorkerLock(tmp_path / "worker.lock"), WorkerLock(tmp_path / "worker.lock")
    assert a.acquire()
    assert not b.acquire()
    a.close()
    assert b.acquire()
    b.close()


def test_graph_trash_and_restore_keep_original_folder(client, store, monkeypatch):
    parent = {"id": "sent-id"}
    moves = []

    async def token():
        return "fake"

    async def message(*args):
        return {"parent_folder_id": parent["id"]}

    async def folder(token, id):
        return {"id": "trash-id" if id == "deleteditems" else id, "displayName": "Sent"}

    async def move(token, id, target):
        moves.append(target)
        parent["id"] = "trash-id" if target == "deleteditems" else target

    monkeypatch.setattr(routes, "get_token", token)
    monkeypatch.setattr(mail_graph, "get_message", message)
    monkeypatch.setattr(mail_graph, "folder_info", folder)
    monkeypatch.setattr(mail_graph, "move_message", move)
    for action in ["trash", "trash", "restore", "restore"]:
        r = client.post(
            "/mail/actions",
            json={"items": [{"kind": "graph", "id": "immutable-id", "action": action}]},
        )
        assert r.json()["results"][0]["ok"]
    assert moves == ["deleteditems", "sent-id"]
    assert store.origin("immutable-id")["folder_name"] == "Sent"


def test_graph_message_can_be_permanently_deleted_from_trash(
    client, store, monkeypatch
):
    deleted = []

    async def token():
        return "fake"

    async def message(*args):
        return {"parent_folder_id": "trash-id"}

    async def folder(*args):
        return {"id": "trash-id", "displayName": "Deleted Items"}

    async def delete(token, message_id):
        deleted.append(message_id)

    monkeypatch.setattr(routes, "get_token", token)
    monkeypatch.setattr(mail_graph, "get_message", message)
    monkeypatch.setattr(mail_graph, "folder_info", folder)
    monkeypatch.setattr(mail_graph, "delete_message", delete)
    response = client.post(
        "/mail/actions",
        json={"items": [{"kind": "graph", "id": "immutable-id", "action": "delete"}]},
    )
    assert response.json()["results"][0]["ok"]
    assert deleted == ["immutable-id"]


def test_cursor_cannot_exfiltrate_token():
    with pytest.raises(ValueError):
        asyncio.run(
            mail_graph.list_messages(
                "secret", "inbox", "https://unrelated.example/v1.0/me/messages"
            )
        )


@pytest.mark.parametrize(
    "status,uncertain", [(202, False), (503, True), (400, False), (429, False)]
)
def test_graph_response_classification(monkeypatch, status, uncertain):
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Retry-After": "123"}, json={})

    monkeypatch.setattr(
        mail_graph.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    if status == 202:
        asyncio.run(mail_graph.request("token", "POST", "/me/sendMail", send=True))
    else:
        with pytest.raises(mail_graph.MailGraphError) as error:
            asyncio.run(mail_graph.request("token", "POST", "/me/sendMail", send=True))
        assert error.value.uncertain == uncertain
        if status == 429:
            assert error.value.retry_after == 123
    assert 'IdType="ImmutableId"' in requests[0].headers["Prefer"]


def test_network_timeout_after_submission_is_unknown(monkeypatch):
    original = httpx.AsyncClient

    def handler(request):
        raise httpx.ReadTimeout("response lost", request=request)

    monkeypatch.setattr(
        mail_graph.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(mail_graph.MailGraphError) as error:
        asyncio.run(mail_graph.request("token", "POST", "/me/sendMail", send=True))
    assert error.value.uncertain


def test_submit_api_rejects_changed_workbook_and_is_idempotent(
    client, store, monkeypatch
):
    saved = preview(store)
    monkeypatch.setattr(routes, "calculate_workbook_version", lambda path: "changed")
    settings = Settings(
        environment="test", microsoft_fixed_sender_email="sender@example.com"
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    payload = {"preview_id": str(saved.preview_id)}
    assert client.post("/mail/submit", json=payload).status_code == 409
    assert not store.list_local("outbox")
    monkeypatch.setattr(
        routes, "calculate_workbook_version", lambda path: "fingerprint"
    )
    first = client.post("/mail/submit", json=payload)
    assert first.status_code == 202
    monkeypatch.setattr(
        routes, "calculate_workbook_version", lambda path: "changed-again"
    )
    second = client.post("/mail/submit", json=payload)
    assert second.json()["id"] == first.json()["id"]


def test_draft_consumed_atomically_with_submit(store):
    draft = store.save_draft(DraftInput(subject="Draft", content="Body"))
    saved = preview(store)
    with pytest.raises(MailConflict):
        store.enqueue(saved.preview_id, draft_id=draft["id"], draft_revision=999)
    assert not store.list_local("outbox")
    job = store.enqueue(
        saved.preview_id, draft_id=draft["id"], draft_revision=draft["revision"]
    )
    assert job["status"] == "queued"
    assert not store.list_local("drafts")
    # A browser retry succeeds even though the draft was already consumed.
    assert (
        store.enqueue(saved.preview_id, draft_id=draft["id"], draft_revision=1)["id"]
        == job["id"]
    )


def test_concurrent_workers_cannot_claim_same_job(store):
    job = store.enqueue(preview(store).preview_id)
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: store.claim_due(now_utc(), 300), range(4)))
    assert [j["id"] for j in claimed if j] == [job["id"]]


def test_past_schedule_and_invalid_timezone_are_rejected(client, store, monkeypatch):
    saved = preview(store)
    monkeypatch.setattr(
        routes, "calculate_workbook_version", lambda path: "fingerprint"
    )
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: Settings(
            environment="test", microsoft_fixed_sender_email="sender@example.com"
        ),
    )
    payload = {
        "preview_id": str(saved.preview_id),
        "schedule": {
            "start": "2000-01-01T09:00",
            "timezone": "UTC",
            "frequency": "daily",
        },
    }
    assert client.post("/mail/submit", json=payload).status_code == 409
    payload["schedule"]["timezone"] = "Invalid/Zone"
    assert client.post("/mail/submit", json=payload).status_code == 422
    assert not store.list_local("outbox")
