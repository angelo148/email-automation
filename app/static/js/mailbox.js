"use strict";
const $ = (id) => document.getElementById(id);
const folderNames = {inbox: "Inbox", outbox: "Outbox", sent: "Sent", drafts: "Drafts", trash: "Trash"};
const descriptions = {inbox: "Incoming conversations", outbox: "Scheduled and pending messages", sent: "Your sent conversations", drafts: "Ideas waiting to be sent", trash: "Deleted messages · restore when needed"};
let folder = "inbox", messages = [], nextCursor = null, generation = 0, refreshing = false;
let searchTimer;
let editingSchedule = null;
const selected = new Set();
const pendingActions = new Set();
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
function notice(text) {
    const element = $("mail-notice");
    element.textContent = text || "";
    element.hidden = !text;
    element.classList.toggle("connection-warning", !!text);
}
function setConnection(connected, title) {
    const dot = $("connection-dot");
    dot.className = `connection-dot ${connected === null ? "checking" : connected ? "connected" : "offline"}`;
    dot.title = title; dot.setAttribute("aria-label", title);
}
let toastTimeout;
function toast(text, actionLabel, action, duration = 6000) {
    const element = $("toast"); element.replaceChildren(document.createTextNode(text));
    if (actionLabel && action) {
        const actionButton = document.createElement("button"); actionButton.type = "button"; actionButton.textContent = actionLabel;
        actionButton.addEventListener("click", async () => {actionButton.disabled = true; clearTimeout(toastTimeout); try {await action();} catch (error) {toast(error.message);}});
        element.append(actionButton);
    }
    element.hidden = false;
    clearTimeout(toastTimeout); toastTimeout = setTimeout(() => element.hidden = true, duration);
}
function confirmPermanentDelete(count) {
    const dialog = $("delete-confirm-dialog");
    $("delete-confirm-title").textContent = `Permanently delete ${count === 1 ? "message" : `${count} messages`}?`;
    dialog.returnValue = "cancel"; dialog.showModal();
    return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "delete"), {once:true}));
}
function confirmResumeSchedule() {
    const dialog = $("resume-confirm-dialog");
    dialog.returnValue = "cancel"; dialog.showModal();
    return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "resume"), {once:true}));
}
function actionResultMessage(action, total, failures, items = []) {
    const succeeded = total - failures.length;
    if (failures.length) {
        const verb = {trash:"moved",restore:"restored",delete:"deleted",read:"marked read",unread:"marked unread",pause:"paused",resume:"resumed"}[action] || "completed";
        return `${succeeded} ${verb}, ${failures.length} failed. ${failures[0].detail || "Try again."}`;
    }
    if (action === "restore") {
        const hasJobs = items.some(item => item.kind === "job");
        const hasOtherMessages = items.some(item => item.kind !== "job");
        if (hasJobs && hasOtherMessages) return "Messages restored. Outbox schedules remain paused until resumed.";
        if (hasJobs) return "Schedule restored. It remains paused until resumed.";
        return total === 1 ? "Message restored." : `${total} messages restored.`;
    }
    return {delete:"Permanently deleted.",pause:"Schedule paused.",resume:"Sending resumed.",read:"Marked as read.",unread:"Marked as unread."}[action];
}
async function undoTrash(items) {
    const itemKeys = items.map(key);
    if (itemKeys.some(itemKey => pendingActions.has(itemKey))) return;
    itemKeys.forEach(itemKey => pendingActions.add(itemKey));
    try {
        const result = await api("/mail/actions", "POST", {items: items.map(item => ({kind:item.kind,id:item.id,action:"restore"}))});
        const failure = result.results.find(entry => !entry.ok);
        if (failure) throw new Error(failure.detail || "The message could not be restored.");
        toast(items.length === 1 ? "Message restored." : `${items.length} messages restored.`);
        await loadFolder(false, true);
    } finally {
        itemKeys.forEach(itemKey => pendingActions.delete(itemKey));
    }
}
function dateLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "";
    return date.toDateString() === new Date().toDateString()
        ? date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
        : date.toLocaleDateString([], {day: "numeric", month: "short"});
}
function nextSendLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.valueOf())) return "Next send unavailable";
    return `Next: ${date.toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})}`;
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
    const selectedItems = messages.filter(item => selected.has(key(item)));
    const hasSelection = selectedItems.length > 0;
    $("selection-count").textContent = hasSelection ? `${selectedItems.length} selected` : "";
    $("delete-selected").hidden = !hasSelection || folder === "trash";
    $("restore-selected").hidden = !hasSelection || folder !== "trash";
    $("permanently-delete-selected").hidden = folder !== "trash";
    $("permanently-delete-selected").disabled = !hasSelection;
    const canMark = hasSelection && ["inbox", "sent"].includes(folder) && selectedItems.every(item => item.kind === "graph");
    $("mark-read-selected").hidden = !canMark || !selectedItems.some(item => !item.is_read);
    $("mark-unread-selected").hidden = !canMark || !selectedItems.some(item => item.is_read);
    $("clear-selection").hidden = !hasSelection;
    document.querySelector(".mail-toolbar").classList.toggle("selection-active", hasSelection);
    $("select-messages").checked = !!messages.length && messages.every(m => selected.has(key(m)));
    $("select-messages").indeterminate = !!selected.size && !$("select-messages").checked;
}
function render() {
    const list = $("message-list"); list.replaceChildren();
    for (const item of messages) {
        const row = document.createElement("div");
        row.className = `message-row${!item.is_read ? " unread" : ""}${selected.has(key(item)) ? " selected" : ""}`;
        row.dataset.messageKey = key(item);
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
            const scheduleKind = document.createElement("span");
            const recurring = item.schedule && item.schedule.frequency !== "once";
            scheduleKind.className = `schedule-kind${recurring ? " recurring" : ""}`;
            scheduleKind.textContent = recurring ? "Recurring" : item.schedule ? "One-time" : "Send now";
            row.append(scheduleKind);
            const status = document.createElement("span");
            status.className = "status-pill" + (["partial", "paused", "authentication_required", "needs_review"].includes(item.status) ? " problem" : "");
            status.textContent = item.status.replaceAll("_", " "); row.append(status);
        }
        const date = document.createElement("span"); date.className = `message-date${folder === "outbox" && item.kind === "job" ? " next-send" : ""}`; date.textContent = folder === "outbox" && item.kind === "job" ? nextSendLabel(item.date) : dateLabel(item.date); date.title = new Date(item.date).toLocaleString(); row.append(date);
        const actions = document.createElement("div"); actions.className = "row-actions";
        if (folder === "trash") {
            const restore = button("", () => act([item], "restore"), "icon-button");
            restore.innerHTML = restoreIcon; restore.title = "Restore"; restore.setAttribute("aria-label", restore.title);
            const permanentlyDelete = button("", () => act([item], "delete"), "icon-button permanent-delete");
            permanentlyDelete.innerHTML = trashIcon; permanentlyDelete.title = "Delete permanently"; permanentlyDelete.setAttribute("aria-label", permanentlyDelete.title);
            actions.append(restore, permanentlyDelete);
        } else {
            const remove = button("", () => act([item], "trash"), "icon-button");
            remove.innerHTML = trashIcon; remove.title = "Move to Trash"; remove.setAttribute("aria-label", remove.title);
            actions.append(remove);
        }
        row.append(actions); list.append(row);
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
        if (["inbox", "sent", "trash"].includes(folder)) {
            setConnection(!result.warning, result.warning ? "Microsoft Graph is temporarily unavailable" : "Microsoft mailbox connected");
        }
        notice(result.warning ? "Microsoft mailbox is temporarily unavailable. Local drafts and scheduled messages remain safe." : ""); render();
    } catch (error) {
        if (requestGeneration !== generation) return;
        if (["inbox", "sent", "trash"].includes(folder)) setConnection(false, "Microsoft Graph is unavailable");
        notice(error.status === 401 ? "The saved Microsoft session needs attention. Your local drafts and schedules remain safe." : "Microsoft mailbox is temporarily unavailable. Check your connection and try Refresh.");
        if (!quiet) {messages = []; nextCursor = null; render();}
    } finally {
        if (requestGeneration === generation) {refreshing = false; $("refresh-mail").disabled = false;}
    }
}
async function switchFolder(next) {
    folder = next; messages = []; nextCursor = null; selected.clear(); $("mail-search").value = "";
    $("folder-title").textContent = folderNames[folder]; $("folder-description").textContent = descriptions[folder];
    document.title = `${folderNames[folder]} · MailFlow`;
    document.querySelectorAll("[data-folder]").forEach(b => {b.classList.toggle("active", b.dataset.folder === folder); if (b.dataset.folder === folder) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");});
    updateSelection();
    await loadFolder();
}
async function act(items, action, destination) {
    if (!items.length) return;
    if (action === "restore" && items.some(i => i.kind === "graph" && !i.original_folder) && !destination) {
        await openItem(items.find(i => i.kind === "graph" && !i.original_folder));
        toast("Choose a destination for messages deleted outside this app."); return;
    }
    if (action === "resume" && !await confirmResumeSchedule()) return;
    if (action === "delete" && !await confirmPermanentDelete(items.length)) return;
    const itemKeys = items.map(key);
    if (itemKeys.some(itemKey => pendingActions.has(itemKey))) return;
    itemKeys.forEach(itemKey => pendingActions.add(itemKey));
    const optimistic = action === "trash" || action === "delete";
    const previousMessages = messages;
    const previousSelection = new Set(selected);
    if (optimistic) {
        const removed = new Set(itemKeys);
        document.querySelectorAll(".message-row").forEach(row => {if (removed.has(row.dataset.messageKey)) row.classList.add("removing");});
        await new Promise(resolve => setTimeout(resolve, 170));
        messages = messages.filter(item => !removed.has(key(item)));
        for (const itemKey of removed) selected.delete(itemKey);
        render();
    }
    const request = api("/mail/actions", "POST", {items: items.map(i => ({kind:i.kind,id:i.id,action,...(destination ? {destination} : {})}))});
    if (action === "trash") {
        toast(items.length === 1 ? "Message moved to Trash." : `${items.length} messages moved to Trash.`, "Undo", async () => {await request; await undoTrash(items);}, 5000);
    }
    let result;
    try {
        result = await request;
    } catch (error) {
        if (optimistic) {
            messages = previousMessages;
            selected.clear();
            for (const itemKey of previousSelection) selected.add(itemKey);
            render();
        }
        itemKeys.forEach(itemKey => pendingActions.delete(itemKey));
        throw error;
    }
    const failures = result.results.filter(r => !r.ok);
    if (action !== "trash" || failures.length) {
        toast(actionResultMessage(action, result.results.length, failures, items));
    }
    if (!failures.length && items.some(item => item.kind === "graph")) setConnection(true, "Microsoft mailbox connected");
    if (!failures.length) $("message-dialog").close();
    itemKeys.forEach(itemKey => pendingActions.delete(itemKey));
    if (!optimistic || failures.length) await loadFolder();
}
function scheduleText(item) {
    if (!item.schedule) return item.kind === "job" ? `Send now · Next attempt: ${new Date(item.date).toLocaleString()}` : "";
    const r = item.schedule;
    const unit = {daily:"day",weekly:"week",monthly:"month"}[r.frequency];
    const cadence = r.frequency === "once" ? "One-time send" : `Recurring · Every ${r.interval} ${unit}${r.interval === 1 ? "" : "s"}`;
    return `${cadence} · Next send: ${new Date(item.date).toLocaleString()} · ${r.timezone}${r.end_date ? ` · Ends ${r.end_date}` : ""}\nApproved recipient addresses are locked to this schedule.`;
}
function scheduleParts(schedule) {
    const start = String(schedule?.start || "");
    return {date: start.slice(0, 10), time: start.slice(11, 16)};
}
function updateScheduleEditFields() {
    const recurring = $("edit-frequency").value !== "once";
    $("edit-interval-wrap").hidden = !recurring;
    $("edit-end-date-wrap").hidden = !recurring;
    const interval = $("edit-interval");
    interval.disabled = !recurring;
    if (!recurring) interval.value = "1";
    const endDate = $("edit-end-date");
    endDate.disabled = !recurring;
    if (!recurring) endDate.value = "";
    updateScheduleEditSummary();
}
function updateScheduleEditSummary() {
    const date = $("edit-start-date").value;
    const time = $("edit-start-time").value;
    const timezone = $("edit-timezone").value.trim() || "the selected timezone";
    const frequency = $("edit-frequency").value;
    if (!date || !time) {$("edit-schedule-summary").textContent = "Choose a future date and time."; return;}
    const cadence = frequency === "once" ? "One-time send" : `Every ${$("edit-interval").value || 1} ${({daily:"day",weekly:"week",monthly:"month"}[frequency])}${Number($("edit-interval").value || 1) === 1 ? "" : "s"}`;
    $("edit-schedule-summary").textContent = `${cadence} · ${date} at ${time} · ${timezone}`;
}
function openScheduleEditor(data) {
    if (!data.schedule) return;
    editingSchedule = data;
    const parts = scheduleParts(data.schedule);
    $("edit-start-date").value = parts.date;
    $("edit-start-time").value = parts.time;
    $("edit-timezone").value = data.schedule.timezone || "Asia/Beirut";
    $("edit-frequency").value = data.schedule.frequency || "once";
    $("edit-interval").value = data.schedule.interval || 1;
    $("edit-end-date").value = data.schedule.end_date || "";
    updateScheduleEditFields();
    $("schedule-edit-dialog").showModal();
}
async function saveScheduleEdit() {
    if (!editingSchedule) return;
    const date = $("edit-start-date").value;
    const time = $("edit-start-time").value;
    const frequency = $("edit-frequency").value;
    if (!date || !time || !$("edit-timezone").value.trim()) {toast("Choose a date, time, and timezone."); return;}
    const schedule = {
        start: `${date}T${time}`,
        timezone: $("edit-timezone").value.trim(),
        frequency,
        interval: frequency === "once" ? 1 : Math.max(1, Number($("edit-interval").value || 1)),
        end_date: frequency === "once" || !$("edit-end-date").value ? null : $("edit-end-date").value,
    };
    const button = $("save-schedule-edit"); button.disabled = true;
    try {
        await api(`/mail/jobs/${editingSchedule.id}/schedule`, "PUT", {schedule, revision: editingSchedule.revision});
        $("schedule-edit-dialog").close(); $("message-dialog").close();
        toast("Schedule updated.");
        await loadFolder();
    } catch (error) {toast(error.message);}
    finally {button.disabled = false;}
}
async function openItem(item) {
    if (item.kind === "draft" && folder !== "trash") {openCompose(item.id); return;}
    let data = item;
    if (item.kind === "graph") data = {...item, ...await api(`/mail/message?id=${encodeURIComponent(item.id)}`)};
    if (item.kind === "job") {
        data = await api(`/mail/jobs/${item.id}?current=1`);

              if (data.id !== item.id) {
                  await loadFolder(false, true);
              }
    }
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
            if (data.schedule && ["queued", "paused", "retry", "authentication_required"].includes(data.status)) actions.append(button("Edit schedule", () => openScheduleEditor(data)));
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
$("permanently-delete-selected").addEventListener("click", () => act(messages.filter(i => selected.has(key(i))), "delete").catch(e => toast(e.message)));
$("mark-read-selected").addEventListener("click", () => act(messages.filter(i => selected.has(key(i)) && i.kind === "graph"), "read").then(() => {selected.clear(); updateSelection();}).catch(e => toast(e.message)));
$("mark-unread-selected").addEventListener("click", () => act(messages.filter(i => selected.has(key(i)) && i.kind === "graph"), "unread").then(() => {selected.clear(); updateSelection();}).catch(e => toast(e.message)));
$("clear-selection").addEventListener("click", () => {selected.clear(); render();});
$("compose-button").addEventListener("click", () => openCompose());
$("close-compose").addEventListener("click", closeCompose);
$("compose-dialog").addEventListener("cancel", e => {e.preventDefault(); closeCompose();});
$("close-message").addEventListener("click", () => $("message-dialog").close());
$("edit-frequency").addEventListener("change", updateScheduleEditFields);
["edit-start-date", "edit-start-time", "edit-timezone", "edit-interval", "edit-end-date"].forEach(id => $(id).addEventListener("input", updateScheduleEditSummary));
$("schedule-edit-form").addEventListener("submit", event => {event.preventDefault(); saveScheduleEdit();});
$("close-schedule-edit").addEventListener("click", () => $("schedule-edit-dialog").close());
$("cancel-schedule-edit").addEventListener("click", () => $("schedule-edit-dialog").close());
$("schedule-edit-dialog").addEventListener("click", event => {if (event.target === $("schedule-edit-dialog")) $("schedule-edit-dialog").close();});
$("delete-confirm-dialog").addEventListener("click", event => {if (event.target === $("delete-confirm-dialog")) $("delete-confirm-dialog").close("cancel");});
$("resume-confirm-dialog").addEventListener("click", event => {if (event.target === $("resume-confirm-dialog")) $("resume-confirm-dialog").close("cancel");});
window.addEventListener("message", e => {
    if(e.origin !== location.origin || e.source !== $("compose-frame").contentWindow || e.data?.type !== "mail-saved") return;
    $("compose-dialog").close(); $("compose-frame").src="about:blank";
    toast(e.data.folder === "drafts" ? "Draft saved." : "Email added to Outbox."); switchFolder(e.data.folder);
});
api("/auth/status").then(s => {$("account-state").textContent = s.fixed_sender_email || "Microsoft mailbox"; setConnection(s.authenticated, s.authenticated ? "Microsoft mailbox connected" : "Saved Microsoft session unavailable");}).catch(() => {$("account-state").textContent="Microsoft mailbox"; setConnection(false, "Microsoft connection status unavailable");});
loadFolder().then(() => {const error = new URLSearchParams(location.search).get("auth_error"); if(error) notice(error, true);});
setInterval(() => {if(!document.hidden && !refreshing && !selected.size && !$("compose-dialog").open && !$("message-dialog").open && !nextCursor) loadFolder(false,true);},30000);
