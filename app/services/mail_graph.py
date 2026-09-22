"""Microsoft mailbox access. External email content is returned as plain text."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import httpx

from app.services.graph_service import GRAPH_BASE_URL, GRAPH_TIMEOUT_SECONDS

FOLDERS = {"inbox": "inbox", "sent": "sentitems", "trash": "deleteditems"}


class MailGraphError(RuntimeError):
    def __init__(self, message, status=502, retry_after=60, uncertain=False):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.uncertain = uncertain


def retry_delay(value):
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        try:
            seconds = int(
                (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            )
        except (TypeError, ValueError, OverflowError):
            seconds = 60
    return max(1, seconds)


async def request(token, method, path, *, params=None, payload=None, send=False):
    url = GRAPH_BASE_URL + path
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
    }
    async with httpx.AsyncClient(timeout=GRAPH_TIMEOUT_SECONDS) as client:
        try:
            response = await client.request(
                method, url, headers=headers, params=params, json=payload
            )
        except httpx.RequestError as exc:
            raise MailGraphError(
                (
                    "Submission outcome is unknown. Check Sent before sending again."
                    if send
                    else "Microsoft could not be reached. Refresh before retrying this action."
                ),
                uncertain=send,
            ) from exc
    if response.status_code in {401, 403}:
        raise MailGraphError(
            "Sign in to Microsoft again and allow Mail.ReadWrite and Mail.Send.", 401
        )
    if response.status_code == 429:
        raise MailGraphError(
            "Microsoft is limiting requests. Sending will retry after the requested delay.",
            429,
            retry_delay(response.headers.get("Retry-After")),
        )
    if response.status_code == 404:
        raise MailGraphError(
            "This message no longer exists in that location. Refresh the folder.", 404
        )
    if not response.is_success:
        raise MailGraphError(
            "Microsoft could not complete this request.",
            uncertain=send and response.status_code >= 500,
        )
    if send:
        if response.status_code != 202:
            raise MailGraphError(
                "Unexpected send response. Check Sent before retrying.", uncertain=True
            )
        return {}
    if response.status_code == 204:
        return {}
    return response.json()


def message_summary(message):
    sender = message.get("from", {}).get("emailAddress", {})
    return {
        "id": message["id"],
        "kind": "graph",
        "subject": message.get("subject") or "(No subject)",
        "sender": sender.get("name") or sender.get("address") or "Unknown sender",
        "sender_address": sender.get("address", ""),
        "snippet": message.get("bodyPreview", ""),
        "date": (
            message.get("sentDateTime")
            if message.get("isDraft")
            else message.get("receivedDateTime") or message.get("sentDateTime")
        ),
        "is_read": message.get("isRead", True),
        "parent_folder_id": message.get("parentFolderId"),
        "to": [
            r.get("emailAddress", {}).get("address", "")
            for r in message.get("toRecipients", [])
        ],
        "cc": [
            r.get("emailAddress", {}).get("address", "")
            for r in message.get("ccRecipients", [])
        ],
        "has_attachments": message.get("hasAttachments", False),
        "content": message.get("body", {}).get("content", ""),
    }


async def list_messages(token, folder, cursor=None, search=""):
    path = f"/me/mailFolders/{FOLDERS[folder]}/messages"
    params = {
        "$top": "50",
        "$select": "id,subject,from,toRecipients,ccRecipients,bodyPreview,receivedDateTime,sentDateTime,isRead,parentFolderId,hasAttachments",
        "$orderby": "receivedDateTime desc",
    }
    if search:
        # OData contains with escaped single quotes; sorting is done locally for search.
        term = search.replace("'", "''")
        params.pop("$orderby")
        params["$filter"] = (
            f"contains(subject,'{term}') or contains(from/emailAddress/address,'{term}')"
        )
    if cursor:
        parsed = urlsplit(cursor)
        # Never forward an access token to a supplied host or another Graph API.
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != "/v1.0" + path
            or parsed.fragment
        ):
            raise ValueError("Invalid mailbox page cursor.")
        path += "?" + parsed.query
        params = None
    data = await request(token, "GET", path, params=params)
    return {
        "items": [message_summary(m) for m in data.get("value", [])],
        "next_cursor": data.get("@odata.nextLink"),
    }


async def get_message(token, message_id):
    data = await request(
        token,
        "GET",
        "/me/messages/" + quote(message_id, safe=""),
        params={
            "$select": "id,subject,from,toRecipients,ccRecipients,body,bodyPreview,receivedDateTime,sentDateTime,isRead,parentFolderId,hasAttachments"
        },
    )
    return message_summary(data)


async def move_message(token, message_id, destination):
    return await request(
        token,
        "POST",
        "/me/messages/" + quote(message_id, safe="") + "/move",
        payload={"destinationId": destination},
    )


async def mark_read(token, message_id, read):
    return await request(
        token,
        "PATCH",
        "/me/messages/" + quote(message_id, safe=""),
        payload={"isRead": read},
    )


async def folder_info(token, folder):
    return await request(
        token,
        "GET",
        "/me/mailFolders/" + quote(folder, safe=""),
        params={"$select": "id,displayName,totalItemCount,unreadItemCount"},
    )


async def send_route(token, subject, content, recipient):
    from app.services.graph_service import _build_message_payload

    payload = _build_message_payload(
        subject=subject,
        content=content,
        to_addresses=recipient["to"],
        cc_addresses=recipient["cc"],
    )
    return await request(token, "POST", "/me/sendMail", payload=payload, send=True)
