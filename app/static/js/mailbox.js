"use strict";
const $ = (id) => document.getElementById(id);
const folderNames = {inbox: "Inbox", outbox: "Outbox", sent: "Sent", drafts: "Drafts", trash: "Trash"};
const descriptions = {inbox: "Incoming conversations", outbox: "Scheduled and pending messages", sent: "Your sent conversations", drafts: "Ideas waiting to be sent", trash: "Deleted messages · restore when needed"};
let folder = "inbox", messages = [], nextCursor = null, generation = 0, refreshing = false;
let searchTimer;
const selected = new Set();
const key = (item) => `${item.kind}:${item.id}`;
const trashIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18 M9 6V3h6v3 M6 6l1 15h10l1-15 M10 10v7 M14 10v7"/></svg>';
const restoreIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9a8 8 0 1 1 0 8 M4 3v6h6"/></svg>';

async function api(url, method = "GET", body) {
    const response = await fetch(url, {method, cache: "no-store", headers: {"Content-Type": "application/json", "X-Mail-Client": "1"}, body: body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) {
        const error = new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
        error.status = response.status;
        throw error;
    }
    return data;
}
function notice(text, connect = false) {
    const element = $("mail-notice");
    element.textContent = text || "";
    element.hidden = !text;
    if (connect) {
        const a = document.createElement("a");
        a.href = "/auth/login"; a.textContent = "Connect Microsoft";
        element.append(a);
    }
}
let toastTimeout;
function toast(text) {
    $("toast").textContent = text; $("toast").hidden = false;
    clearTimeout(toastTimeout); toastTimeout = setTimeout(() => $("toast").hidden = true, 6000);
}
function dateLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "";
    return date.toDateString() === new Date().toDateString()
        ? date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
        : date.toLocaleDateString([], {day: "numeric", month: "short"});
}
function button(text, action, className = "") {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = text; b.className = className;
    b.addEventListener("click", async (event) => {
        event.stopPropagation(); b.disabled = true;
        try { await action(); } catch (error) { toast(error.message); }
        finally { b.disabled = false; }
    });
    return b;
}
function updateSelection() {
    $("selection-count").textContent = selected.size ? `${selected.size} selected` : "";
    $("delete-selected").hidden = !selected.size || folder === "trash";
    $("restore-selected").hidden = !selected.size || folder !== "trash";
    $("select-messages").checked = !!messages.length && messages.every(m => selected.has(key(m)));
    $("select-messages").indeterminate = !!selected.size && !$("select-messages").checked;
}
function render() {
    const list = $("message-list"); list.replaceChildren();
    for (const item of messages) {
        const row = document.createElement("div");
        row.className = `message-row${!item.is_read ? " unread" : ""}${selected.has(key(item)) ? " selected" : ""}`;
        const check = document.createElement("input"); check.type = "checkbox";
        check.setAttribute("aria-label", `Select ${item.subject || "untitled draft"}`);
        check.checked = selected.has(key(item));
        check.addEventListener("change", () => {check.checked ? selected.add(key(item)) : selected.delete(key(item)); row.classList.toggle("selected", check.checked); updateSelection();});
        const open = button("", () => openItem(item), "row-open");
        const sender = document.createElement("span"); sender.className = "message-sender";
        sender.textContent = item.kind === "job" ? item.recipients.map(r => r.name).join(", ") : folder === "sent" && item.to?.length ? `To: ${item.to.join(", ")}` : item.sender;
        const text = document.createElement("span"); text.className = "message-text";
        const subject = document.createElement("span"); subject.className = "message-subject"; subject.textContent = item.subject || "(No subject)";
        const snippet = document.createElement("span"); snippet.className = "message-snippet"; snippet.textContent = `— ${item.snippet || ""}`;
        text.append(subject, snippet); open.append(sender, text);
        row.append(check, open);
        if (item.kind === "job") {
            const status = document.createElement("span");
            status.className = "status-pill" + (["partial", "paused", "authentication_required", "needs_review"].includes(item.status) ? " problem" : "");
            status.textContent = item.status.replaceAll("_", " "); row.append(status);
        }
        const date = document.createElement("span"); date.className = "message-date"; date.textContent = dateLabel(item.date); date.title = new Date(item.date).toLocaleString(); row.append(date);
        const actions = document.createElement("div"); actions.className = "row-actions";
        const action = folder === "trash" ? "restore" : "trash";
        const remove = button("", () => act([item], action), "icon-button");
        remove.innerHTML = action === "restore" ? restoreIcon : trashIcon;
        remove.title = action === "restore" ? "Restore" : "Move to Trash"; remove.setAttribute("aria-label", remove.title);
        actions.append(remove); row.append(actions); list.append(row);
    }
    $("message-count").textContent = `${messages.length}${nextCursor ? "+" : ""} ${messages.length === 1 ? "message" : "messages"}`;
    $("mail-empty").hidden = !!messages.length;
    $("empty-title").textContent = $("mail-search").value ? "No matching messages" : {inbox:"Your inbox is clear",outbox:"Nothing waiting to send",sent:"No sent messages yet",drafts:"A little space for your next idea",trash:"Trash is empty"}[folder];
    $("empty-description").textContent = {inbox:"Incoming messages appear here when your Microsoft account is connected.",outbox:"Compose an email and choose a one-time or recurring schedule.",sent:"Sent messages from your connected Microsoft mailbox appear here.",drafts:"Save a draft to come back to it later.",trash:"Deleted emails can be restored to their original folder."}[folder];
    $("load-more").hidden = !nextCursor;
    updateSelection();
}
async function loadFolder(append = false, quiet = false) {
    clearTimeout(searchTimer);
    const requestGeneration = ++generation;
    refreshing = true;
    if (!quiet) {$("refresh-mail").disabled = true; $("message-count").textContent = "Loading…";}
    try {
        const params = new URLSearchParams({q: $("mail-search").value.trim()});
        if (append && nextCursor) params.set("cursor", nextCursor);
        const result = await api(`/mail/folders/${folder}?${params}`);
        if (requestGeneration !== generation) return;
        messages = append ? [...messages, ...result.items.filter(i => !messages.some(m => key(m) === key(i)))] : result.items;
        nextCursor = result.next_cursor;
        const currentKeys = new Set(messages.map(key));
        for (const id of selected) if (!currentKeys.has(id)) selected.delete(id);
        notice(result.warning, !!result.warning); render();
    } catch (error) {
        if (requestGeneration !== generation) return;
        notice(error.message, error.status === 401);
        if (!quiet) {messages = []; nextCursor = null; render();}
    } finally {
        if (requestGeneration === generation) {refreshing = false; $("refresh-mail").disabled = false;}
    }
}
async function switchFolder(next) {
    folder = next; messages = []; nextCursor = null; selected.clear(); $("mail-search").value = "";
    $("folder-title").textContent = folderNames[folder]; $("folder-description").textContent = descriptions[folder];
    document.title = `${folderNames[folder]} · AI Email Automation`;
    document.querySelectorAll("[data-folder]").forEach(b => {b.classList.toggle("active", b.dataset.folder === folder); if (b.dataset.folder === folder) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");});
    await loadFolder();
}
async function act(items, action, destination) {
    if (!items.length) return;
    if (action === "restore" && items.some(i => i.kind === "graph" && !i.original_folder) && !destination) {
        await openItem(items.find(i => i.kind === "graph" && !i.original_folder));
        toast("Choose a destination for messages deleted outside this app."); return;
    }
    if (action === "resume" && !confirm("Send the remaining eligible routes now and resume this recurring schedule? Accepted routes will be skipped.")) return;
    const result = await api("/mail/actions", "POST", {items: items.map(i => ({kind:i.kind,id:i.id,action,...(destination ? {destination} : {})}))});
    const failures = result.results.filter(r => !r.ok);
    toast(failures.length ? `${result.results.length - failures.length} completed. ${failures[0].detail}` : {trash:"Moved to Trash. Pending sends are cancelled.",restore:"Restored. Outbox schedules remain paused until resumed.",pause:"Schedule paused.",resume:"Sending resumed.",read:"Marked as read.",unread:"Marked as unread."}[action]);
    if (!failures.length) $("message-dialog").close();
    await loadFolder();
}
function scheduleText(item) {
    if (!item.schedule) return item.kind === "job" ? `Send time: ${new Date(item.date).toLocaleString()}` : "";
    const r = item.schedule;
    return `${r.frequency === "once" ? "One-time send" : `Every ${r.interval} ${r.frequency === "daily" ? "day(s)" : r.frequency === "weekly" ? "week(s)" : "month(s)"}`} · ${r.start.replace("T", " ")} · ${r.timezone}${r.end_date ? ` · Ends ${r.end_date}` : ""}\nApproved recipients are saved with this schedule.`;
}
async function openItem(item) {
    if (item.kind === "draft" && folder !== "trash") {openCompose(item.id); return;}
    let data = item;
    if (item.kind === "graph") data = {...item, ...await api(`/mail/message?id=${encodeURIComponent(item.id)}`)};
    if (item.kind === "job") data = await api(`/mail/jobs/${item.id}`);
    $("message-title").textContent = data.subject || "(No subject)";
    $("message-meta").textContent = `${data.sender || "Draft"}${data.sender_address ? ` <${data.sender_address}>` : ""}\n${new Date(data.date).toLocaleString()}${data.to?.length ? `\nTo: ${data.to.join(", ")}` : ""}${data.cc?.length ? `\nCC: ${data.cc.join(", ")}` : ""}`;
    $("message-schedule").textContent = scheduleText(data);
    $("message-body").textContent = data.content || "";
    $("message-results").replaceChildren();
    if (data.detail) {const p = document.createElement("p"); p.textContent = data.detail; $("message-results").append(p);}
    for (const route of data.results || []) {
        const r = document.createElement("div"); const recipient = data.recipients?.[route.route_index];
        r.textContent = `${route.name} · ${route.status.replaceAll("_", " ")}${recipient ? `\nTo: ${recipient.to.join(", ")} · CC: ${recipient.cc.join(", ") || "None"}` : ""}\n${route.detail || "Waiting for submission."}`;
        r.style.whiteSpace = "pre-wrap"; $("message-results").append(r);
    }
    const actions = $("message-actions"); actions.replaceChildren();
    if (folder === "trash") {
        let select;
        if (data.kind === "graph" && !data.original_folder) {
            select = document.createElement("select"); select.setAttribute("aria-label", "Restore destination");
            for (const [value, label] of [["inbox","Restore to Inbox"],["sentitems","Restore to Sent"]]) {const o = document.createElement("option"); o.value=value; o.textContent=label; select.append(o);}
            actions.append(select);
        }
        actions.append(button(data.original_folder ? `Restore to ${data.original_folder}` : "Restore", () => act([data], "restore", select?.value)));
    } else {
        if (data.kind === "job") {
            if (["queued", "sending", "retry"].includes(data.status)) actions.append(button("Pause schedule", () => act([data], "pause")));
            else if (["paused", "authentication_required", "needs_review"].includes(data.status)) actions.append(button("Resume remaining sends", () => act([data], "resume")));
        }
        if (data.kind === "graph") actions.append(button(data.is_read ? "Mark unread" : "Mark read", () => act([data], data.is_read ? "unread" : "read")));
        actions.append(button("Move to Trash", () => act([data], "trash")));
    }
    $("message-dialog").showModal();
    if (data.kind === "graph" && !data.is_read) {
        try {await api("/mail/actions", "POST", {items:[{kind:"graph",id:data.id,action:"read"}]}); item.is_read=true; render();}
        catch (error) {toast(error.message);}
    }
}
function openCompose(draftId) {
    $("compose-title").textContent = draftId ? "Edit draft" : "New message";
    $("compose-frame").src = `/compose?embedded=1${draftId ? `&draft=${encodeURIComponent(draftId)}` : ""}`;
    $("compose-dialog").showModal();
}
function closeCompose() {
    const frame = $("compose-frame").contentWindow;
    if (frame?.mailComposeCanClose && !frame.mailComposeCanClose()) return;
    $("compose-dialog").close(); $("compose-frame").src = "about:blank";
}
document.querySelectorAll("[data-folder]").forEach(b => b.addEventListener("click", () => switchFolder(b.dataset.folder)));
$("refresh-mail").addEventListener("click", () => loadFolder());
$("load-more").addEventListener("click", () => loadFolder(true));
function searchFolder(immediate = false) {
    clearTimeout(searchTimer);
    // Invalidate old responses as soon as the text changes, before the next fetch.
    generation += 1;
    refreshing = true;
    selected.clear();
    nextCursor = null;
    updateSelection();
    $("load-more").hidden = true;
    $("message-count").textContent = "Searching…";
    if (immediate || !$("mail-search").value.trim()) {
        loadFolder();
    } else {
        searchTimer = setTimeout(() => loadFolder(), 250);
    }
}
$("mail-search").addEventListener("input", () => searchFolder());
$("mail-search-form").addEventListener("submit", e => {e.preventDefault(); searchFolder(true);});
$("clear-search").addEventListener("click", () => {$("mail-search").value=""; searchFolder(true); $("mail-search").focus();});
$("select-messages").addEventListener("change", e => {selected.clear(); if(e.target.checked) messages.forEach(i => selected.add(key(i))); render();});
$("delete-selected").addEventListener("click", () => act(messages.filter(i => selected.has(key(i))), "trash").catch(e => toast(e.message)));
$("restore-selected").addEventListener("click", () => act(messages.filter(i => selected.has(key(i))), "restore").catch(e => toast(e.message)));
$("compose-button").addEventListener("click", () => openCompose());
$("close-compose").addEventListener("click", closeCompose);
$("compose-dialog").addEventListener("cancel", e => {e.preventDefault(); closeCompose();});
$("close-message").addEventListener("click", () => $("message-dialog").close());
window.addEventListener("message", e => {
    if(e.origin !== location.origin || e.source !== $("compose-frame").contentWindow || e.data?.type !== "mail-saved") return;
    $("compose-dialog").close(); $("compose-frame").src="about:blank";
    toast(e.data.folder === "drafts" ? "Draft saved." : "Email added to Outbox."); switchFolder(e.data.folder);
});
api("/auth/status").then(s => {$("account-state").textContent = s.fixed_sender_email || "Microsoft mailbox"; $("connect-account").textContent = s.authenticated ? "Reconnect" : "Connect Microsoft";}).catch(() => {$("account-state").textContent="Not connected";});
loadFolder().then(() => {const error = new URLSearchParams(location.search).get("auth_error"); if(error) notice(error, true);});
setInterval(() => {if(!document.hidden && !refreshing && !selected.size && !$("compose-dialog").open && !$("message-dialog").open && !nextCursor) loadFolder(false,true);},30000);
