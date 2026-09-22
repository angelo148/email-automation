let fixedSenderEmail = "";
let currentPayload = null;
let currentPreviewId = null;
let isSending = false;
let defaultAllSelectionActive = true;

const recipientPicker =
    document.getElementById(
        "recipient-picker"
    );

const lookupToggle =
    document.getElementById(
        "lookup-toggle"
    );

const searchInput =
    document.getElementById(
        "company-search"
    );

const selectedChips =
    document.getElementById(
        "selected-chips"
    );

const selectAllButton =
    document.getElementById(
        "select-all"
    );

const unselectAllButton =
    document.getElementById(
        "unselect-all"
    );

const selectedCount =
    document.getElementById(
        "selected-count"
    );

const noResults =
    document.getElementById(
        "no-results"
    );

const emailForm =
    document.getElementById(
        "email-form"
    );

const subjectInput =
    document.getElementById(
        "subject"
    );

const contentInput =
    document.getElementById(
        "content"
    );

const senderEmailDisplay =
    document.getElementById(
        "sender-email-display"
    );

const continueButton =
    document.getElementById(
        "continue-button"
    );

const formError =
    document.getElementById(
        "form-error"
    );

const previewModal =
    document.getElementById(
        "preview-modal"
    );

const previewClose =
    document.getElementById(
        "preview-close"
    );

const previewBack =
    document.getElementById(
        "preview-back"
    );

const previewSender =
    document.getElementById(
        "preview-sender"
    );

const previewCount =
    document.getElementById(
        "preview-count"
    );

const senderWarning =
    document.getElementById(
        "sender-warning"
    );

const previewRecipients =
    document.getElementById(
        "preview-recipients"
    );

const previewSubject =
    document.getElementById(
        "preview-subject"
    );

const previewContent =
    document.getElementById(
        "preview-content"
    );

const sendButton =
    document.getElementById(
        "send-button"
    );

const resultsModal =
    document.getElementById(
        "results-modal"
    );

const resultsClose =
    document.getElementById(
        "results-close"
    );

const resultsDone =
    document.getElementById(
        "results-done"
    );

const resultSummary =
    document.getElementById(
        "result-summary"
    );

const resultItems =
    document.getElementById(
        "result-items"
    );

const allOptions = Array.from(
    document.querySelectorAll(
        "[data-company-option]"
    )
);

const selectableOptions =
    allOptions.filter(
        (option) =>
            option.dataset.canEmail === "true"
    );

async function initializeMicrosoftAuth() {
    const response = await fetch(
        "/auth/status",
        {
            cache: "no-store",
        }
    );

    if (!response.ok) {
        throw new Error(
            "Microsoft authentication status could not be loaded."
        );
    }

    const status = await response.json();

    fixedSenderEmail =
        status.fixed_sender_email || "";

    senderEmailDisplay.textContent =
        fixedSenderEmail
        || "Fixed Outlook sender";

    const params =
        new URLSearchParams(
            window.location.search
        );

    const authError =
        params.get("auth_error");

    if (authError) {
        showError(authError);
        return;
    }

    if (!status.authenticated) {
        showError("Connect your Microsoft account from the mailbox before sending. Drafts can be saved now.");
    }
}

function isSelected(option) {
    return (
        option.dataset.selected === "true"
    );
}

function setSelected(
    option,
    selected
) {
    if (
        option.dataset.canEmail !== "true"
    ) {
        return;
    }

    option.dataset.selected =
        selected
            ? "true"
            : "false";

    option.classList.toggle(
        "selected",
        selected
    );

    const indicator =
        option.querySelector(
            ".selection-box"
        );

    indicator.textContent =
        selected
            ? "✓"
            : "";
}

function getSelectedOptions() {
    return selectableOptions.filter(
        isSelected
    );
}

function selectOnly(option) {
    selectableOptions.forEach(
        (item) => {
            setSelected(
                item,
                false
            );
        }
    );

    setSelected(
        option,
        true
    );
}

function renderSelectedChips() {
    selectedChips.innerHTML =
        "";

    getSelectedOptions().forEach(
        (option) => {
            const chip =
                document.createElement(
                    "span"
                );

            chip.className =
                "recipient-chip";

            const name =
                document.createElement(
                    "span"
                );

            name.className =
                "recipient-chip-name";

            name.textContent =
                option.dataset.companyName;

            const remove =
                document.createElement(
                    "button"
                );

            remove.type =
                "button";

            remove.className =
                "chip-remove";

            remove.textContent =
                "×";

            remove.setAttribute(
                "aria-label",
                `Remove ${option.dataset.companyName}`
            );

            remove.addEventListener(
                "click",
                (event) => {
                    event.stopPropagation();

                    setSelected(
                        option,
                        false
                    );

                    defaultAllSelectionActive =
                        false;

                    updateSelectionUI();
                }
            );

            chip.appendChild(name);
            chip.appendChild(remove);
            selectedChips.appendChild(chip);
        }
    );
}

function updateGroupToggleStates() {
    document
        .querySelectorAll(
            "[data-third-party-group]"
        )
        .forEach(
            (group) => {
                const toggle =
                    group.querySelector(
                        "[data-group-toggle]"
                    );

                if (!toggle) {
                    return;
                }

                const groupOptions =
                    Array.from(
                        group.querySelectorAll(
                            '[data-company-option][data-can-email="true"]'
                        )
                    );

                const selectedCountInGroup =
                    groupOptions.filter(
                        isSelected
                    ).length;
                
                const groupCount =
                     toggle.querySelector(
                            "[data-group-count]"
                    );

                if (groupCount) {
                        groupCount.textContent =
                            `${selectedCountInGroup} / ${groupOptions.length}`;
                }

                const allSelected =
                    groupOptions.length > 0
                    && selectedCountInGroup
                        === groupOptions.length;

                const partiallySelected =
                    selectedCountInGroup > 0
                    && !allSelected;

                toggle.disabled =
                    groupOptions.length === 0;

                toggle.classList.toggle(
                    "selected",
                    allSelected
                );

                toggle.classList.toggle(
                    "partial",
                    partiallySelected
                );

                toggle.setAttribute(
                    "aria-pressed",
                    allSelected
                        ? "true"
                        : "false"
                );
            }
        );
}

function updateSelectionUI() {
    const selected =
        getSelectedOptions();

    selectedCount.textContent =
        `${selected.length} / ${selectableOptions.length} selected`;

    renderSelectedChips();
    updateGroupToggleStates();
}

function buildPayload() {
    return {
        selected_company_rows:
            getSelectedOptions().map(
                (option) =>
                    Number(
                        option.dataset.sourceRow
                    )
            ),

        subject:
            subjectInput.value,

        content:
            contentInput.value,
    };
}

function showError(message) {
    formError.textContent =
        message;

    formError.style.display =
        "block";
}

function clearError() {
    formError.textContent =
        "";

    formError.style.display =
        "none";
}

function openRecipientPicker() {
    recipientPicker.classList.add(
        "open"
    );

    searchInput.setAttribute(
        "aria-expanded",
        "true"
    );
}

function closeRecipientPicker() {
    recipientPicker.classList.remove(
        "open"
    );

    searchInput.setAttribute(
        "aria-expanded",
        "false"
    );
}

function openModal(modal) {
    modal.classList.add(
        "open"
    );

    modal.setAttribute(
        "aria-hidden",
        "false"
    );

    document.body.classList.add(
        "modal-open"
    );
}

function closeModal(modal) {
    modal.classList.remove(
        "open"
    );

    modal.setAttribute(
        "aria-hidden",
        "true"
    );

    if (
        !previewModal.classList.contains("open")
        && !resultsModal.classList.contains("open")
    ) {
        document.body.classList.remove(
            "modal-open"
        );
    }
}

function renderRecipients(
    recipients
) {
    previewRecipients.innerHTML =
        "";

    const groupedRecipients =
        new Map();

    recipients.forEach(
        (recipient) => {
            const groupName =
                recipient.third_party_group;

            if (
                !groupedRecipients.has(
                    groupName
                )
            ) {
                groupedRecipients.set(
                    groupName,
                    []
                );
            }

            groupedRecipients
                .get(groupName)
                .push(recipient);
        }
    );

    groupedRecipients.forEach(
        (
            groupRecipients,
            groupName
        ) => {
            const group =
                document.createElement(
                    "div"
                );

            group.className =
                "preview-group";

            const groupTitle =
                document.createElement(
                    "div"
                );

            groupTitle.className =
                "preview-group-title";

            const groupNameElement =
                document.createElement(
                    "span"
                );

            groupNameElement.textContent =
                groupName;

            const groupCount =
                document.createElement(
                    "span"
                );

            groupCount.className =
                "preview-group-count";

            groupCount.textContent =
                groupRecipients.length;

            groupTitle.appendChild(
                groupNameElement
            );

            groupTitle.appendChild(
                groupCount
            );

            group.appendChild(
                groupTitle
            );

            groupRecipients.forEach(
                (recipient) => {
                    const route =
                        document.createElement(
                            "div"
                        );

                    route.className =
                        "preview-route";

                    const routeHeader =
                        document.createElement(
                            "div"
                        );

                    routeHeader.className =
                        "preview-route-header";

                    const routeName =
                        document.createElement(
                            "div"
                        );

                    routeName.className =
                        "preview-route-name";

                    routeName.textContent =
                        recipient.name;

                    const routeModule =
                        document.createElement(
                            "div"
                        );

                    routeModule.className =
                        "preview-route-module";

                    routeModule.textContent =
                        recipient.module;

                    routeHeader.appendChild(
                        routeName
                    );

                    routeHeader.appendChild(
                        routeModule
                    );

                    const toLine =
                        document.createElement(
                            "div"
                        );

                    toLine.className =
                        "preview-route-address";

                    const toLabel =
                        document.createElement(
                            "span"
                        );

                    toLabel.className =
                        "preview-route-address-label";

                    toLabel.textContent =
                        "To:";

                    const toValue =
                        document.createElement(
                            "span"
                        );

                    toValue.className =
                        "preview-route-address-value";

                    toValue.textContent =
                        recipient.to.join(", ");

                    toLine.appendChild(toLabel);
                    toLine.appendChild(toValue);

                    const ccLine =
                        document.createElement(
                            "div"
                        );

                    ccLine.className =
                        "preview-route-address";

                    const ccLabel =
                        document.createElement(
                            "span"
                        );

                    ccLabel.className =
                        "preview-route-address-label";

                    ccLabel.textContent =
                        "CC:";

                    const ccValue =
                        document.createElement(
                            "span"
                        );

                    ccValue.className =
                        "preview-route-address-value";

                    ccValue.textContent =
                        recipient.cc.length > 0
                            ? recipient.cc.join(", ")
                            : "None";

                    ccLine.appendChild(ccLabel);
                    ccLine.appendChild(ccValue);

                    route.appendChild(routeHeader);
                    route.appendChild(toLine);
                    route.appendChild(ccLine);
                    group.appendChild(route);
                }
            );

            previewRecipients.appendChild(
                group
            );
        }
    );
}

let composeIntent = "send", currentSchedule = null, draftId = null, draftRevision = null;
let composeDirty = false, previewBusy = false, previewCache = null, previewSignature = "";

async function composeApi(url, method = "GET", body) {
    const response = await fetch(url, {method, cache:"no-store", headers:{"Content-Type":"application/json", "X-Mail-Client":"1"}, body:body === undefined ? undefined : JSON.stringify(body)});
    const data = await response.json();
    if (!response.ok) {
        const detail = Array.isArray(data.detail) ? data.detail.map(e => e.msg).join(" ") : data.detail;
        throw new Error(typeof detail === "string" ? detail : "The request could not be completed.");
    }
    return data;
}
function restoreScheduleTime(start) {
    const hour24 = Number(start.slice(11, 13));
    document.getElementById("schedule-start").value = start.slice(0, 10);
    document.getElementById("schedule-hour").value = String(hour24 % 12 || 12);
    document.getElementById("schedule-minute").value = start.slice(14, 16);
    document.getElementById("schedule-period").value = hour24 >= 12 ? "PM" : "AM";
}
function readSchedule() {
    const date = document.getElementById("schedule-start").value;
    if (!date) throw new Error("Choose a send date.");
    const hour = Number(document.getElementById("schedule-hour").value);
    const minute = document.getElementById("schedule-minute").value;
    const period = document.getElementById("schedule-period").value;
    if (!Number.isInteger(hour) || hour < 1 || hour > 12 || !/^[0-5][0-9]$/.test(minute) || !["AM", "PM"].includes(period)) {
        throw new Error("Choose a valid time, including AM or PM.");
    }
    const hour24 = (hour % 12) + (period === "PM" ? 12 : 0);
    const start = `${date}T${String(hour24).padStart(2, "0")}:${minute}`;
    return {start, timezone:document.getElementById("schedule-timezone").value.trim(),
        frequency:document.getElementById("schedule-frequency").value,
        interval:document.getElementById("schedule-frequency").value === "once" ? 1 : Number(document.getElementById("schedule-interval").value),
        end_date:document.getElementById("schedule-frequency").value === "once" ? null : (document.getElementById("schedule-end").value || null)};
}
function draftPreview(payload) {
    return {sender:fixedSenderEmail, subject:payload.subject || "(No subject)", content:payload.content || "(No content yet)",
        recipient_count:payload.selected_company_rows.length,
        recipients:getSelectedOptions().map(o => ({source_row:Number(o.dataset.sourceRow), name:o.dataset.companyName,
            module:o.dataset.moduleName, third_party_group:o.dataset.groupName,
            to:JSON.parse(o.dataset.to || "[]"), cc:JSON.parse(o.dataset.cc || "[]")}))};
}
async function requestPreview() {
    if (isSending || previewBusy) return;
    previewBusy = true; continueButton.disabled = true; clearError();
    try {
        currentPayload = buildPayload();
        currentSchedule = composeIntent === "schedule" ? readSchedule() : null;
        let data;
        if (composeIntent === "draft") {
            data = draftPreview(currentPayload);
        } else {
            const signature = JSON.stringify(currentPayload);
            if (previewCache && previewSignature === signature) data = previewCache;
            else {
                data = await composeApi("/email/preview", "POST", currentPayload);
                previewCache = data; previewSignature = signature;
            }
            currentPreviewId = data.preview_id;
        }
        previewSender.textContent = data.sender || fixedSenderEmail;
        previewCount.textContent = `${data.recipient_count} route${data.recipient_count === 1 ? "" : "s"}`;
        previewSubject.textContent = data.subject; previewContent.textContent = data.content;
        senderWarning.textContent = ""; sendButton.disabled = false;
        sendButton.textContent = {send:"Send now",schedule:"Confirm schedule",draft:"Save draft"}[composeIntent];
        document.getElementById("preview-schedule").textContent = currentSchedule
            ? `${currentSchedule.frequency === "once" ? "One time" : `Repeat ${currentSchedule.frequency}, every ${currentSchedule.interval}`} · Starts ${currentSchedule.start.replace("T"," ")} · ${currentSchedule.timezone}${currentSchedule.end_date ? ` · Ends ${currentSchedule.end_date}` : ""}. These exact recipient addresses will be used for every occurrence.`
            : composeIntent === "draft" ? "Save this message for later. Saving a draft does not send it." : "Send these exact recipients and content now.";
        renderRecipients(data.recipients); closeRecipientPicker(); openModal(previewModal); sendButton.focus();
    } catch(error) {showError(error.message);}
    finally {previewBusy=false; continueButton.disabled=false;}
}
async function sendEmails() {
    if (isSending || !currentPayload) return;
    isSending = true; sendButton.disabled=true; previewBack.disabled=true; previewClose.disabled=true;
    senderWarning.textContent="";
    try {
        if (composeIntent === "draft") {
            const payload = {...currentPayload, revision:draftRevision};
            if (!document.getElementById("schedule-panel").hidden && document.getElementById("schedule-start").value) payload.schedule = readSchedule();
            const saved = await composeApi(draftId ? `/mail/drafts/${draftId}` : "/mail/drafts", draftId ? "PUT" : "POST", payload);
            draftId=saved.id; draftRevision=saved.revision;
        } else {
            if (!currentPreviewId) throw new Error("Create a preview first.");
            await composeApi("/mail/submit", "POST", {preview_id:currentPreviewId, schedule:currentSchedule, draft_id:draftId, draft_revision:draftRevision});
        }
        composeDirty=false;
        closeModal(previewModal);
        const destination = composeIntent === "draft" ? "drafts" : "outbox";
        if (window.parent !== window) window.parent.postMessage({type:"mail-saved",folder:destination},location.origin);
        else location.assign("/");
    } catch(error) {senderWarning.textContent=error.message;}
    finally {isSending=false; sendButton.disabled=false; previewBack.disabled=false; previewClose.disabled=false;}
}
window.mailComposeCanClose = () => {
    if (isSending || previewBusy) return false;
    if (composeDirty && !confirm("Close this unsaved message? Choose Cancel to return and save it as a draft.")) return false;
    composeDirty = false;
    return true;
};

function filterRecipientOptions() {
    const query =
        searchInput.value
            .trim()
            .toLowerCase();

    let visibleOptions =
        0;

    document
        .querySelectorAll(
            "[data-third-party-group]"
        )
        .forEach(
            (group) => {
                const groupOptions =
                    Array.from(
                        group.querySelectorAll(
                            "[data-company-option]"
                        )
                    );

                let visibleInGroup =
                    0;

                groupOptions.forEach(
                    (option) => {
                        const companyName =
                            option.dataset
                                .companyName
                                .toLowerCase();

                        const groupName =
                            option.dataset
                                .groupName
                                .toLowerCase();

                        const moduleName =
                            option.dataset
                                .moduleName
                                .toLowerCase();

                        const matches =
                            !query
                            || companyName.includes(
                                query
                            )
                            || groupName.includes(
                                query
                            )
                            || moduleName.includes(
                                query
                            );

                        option.style.display =
                            matches
                                ? ""
                                : "none";

                        if (matches) {
                            visibleInGroup +=
                                1;

                            visibleOptions +=
                                1;
                        }
                    }
                );

                group.style.display =
                    visibleInGroup > 0
                        ? ""
                        : "none";
            }
        );

    noResults.style.display =
        visibleOptions === 0
            ? "block"
            : "none";
}

selectableOptions.forEach(
    (option) => {
        option.addEventListener(
            "click",
            () => {
                if (
                    defaultAllSelectionActive
                ) {
                    selectOnly(
                        option
                    );

                    defaultAllSelectionActive =
                        false;

                    updateSelectionUI();

                    return;
                }

                setSelected(
                    option,
                    !isSelected(option)
                );

                updateSelectionUI();
            }
        );
    }
);

document
    .querySelectorAll(
        "[data-group-toggle]"
    )
    .forEach(
        (toggle) => {
            toggle.addEventListener(
                "click",
                (event) => {
                    event.stopPropagation();

                    const group =
                        toggle.closest(
                            "[data-third-party-group]"
                        );

                    if (!group) {
                        return;
                    }

                    const groupOptions =
                        Array.from(
                            group.querySelectorAll(
                                '[data-company-option][data-can-email="true"]'
                            )
                        );

                    if (
                        groupOptions.length === 0
                    ) {
                        return;
                    }

                    if (
                        defaultAllSelectionActive
                    ) {
                        selectableOptions.forEach(
                            (option) => {
                                setSelected(
                                    option,
                                    false
                                );
                            }
                        );

                        groupOptions.forEach(
                            (option) => {
                                setSelected(
                                    option,
                                    true
                                );
                            }
                        );

                        defaultAllSelectionActive =
                            false;

                        updateSelectionUI();

                        return;
                    }

                    const allSelected =
                        groupOptions.every(
                            isSelected
                        );

                    groupOptions.forEach(
                        (option) => {
                            setSelected(
                                option,
                                !allSelected
                            );
                        }
                    );

                    updateSelectionUI();
                }
            );
        }
    );

selectAllButton.addEventListener(
    "click",
    () => {
        selectableOptions.forEach(
            (option) => {
                setSelected(
                    option,
                    true
                );
            }
        );

        defaultAllSelectionActive =
            true;

        updateSelectionUI();
    }
);

unselectAllButton.addEventListener(
    "click",
    () => {
        selectableOptions.forEach(
            (option) => {
                setSelected(
                    option,
                    false
                );
            }
        );

        defaultAllSelectionActive =
            false;

        updateSelectionUI();
    }
);

searchInput.addEventListener(
    "click",
    () => {
        const isOpen =
            recipientPicker.classList.contains(
                "open"
            );

        if (isOpen) {
            closeRecipientPicker();
        } else {
            openRecipientPicker();
        }
    }
);

searchInput.addEventListener(
    "input",
    () => {
        filterRecipientOptions();
    }
);

document.addEventListener(
    "click",
    (event) => {
        if (
            !recipientPicker.contains(
                event.target
            )
        ) {
            closeRecipientPicker();
        }
    }
);

emailForm.addEventListener(
    "keydown",
    (event) => {
        if (
            event.key === "Enter"
            && event.target.tagName !== "TEXTAREA"
        ) {
            event.preventDefault();
        }
    }
);

emailForm.addEventListener(
    "submit",
    async (event) => {
        event.preventDefault();

        if (
            getSelectedOptions().length === 0
        ) {
            showError(
                "Select at least one recipient route."
            );

            searchInput.focus();
            openRecipientPicker();
            return;
        }

        if (
            !subjectInput.value.trim()
        ) {
            showError(
                "Subject is required."
            );

            subjectInput.focus();
            return;
        }

        if (
            !contentInput.value.trim()
        ) {
            showError(
                "Email content is required."
            );

            contentInput.focus();
            return;
        }

        composeIntent = "send";
        await requestPreview();
    }
);

previewClose.addEventListener(
    "click",
    () => {
        if (isSending) {
            return;
        }

        closeModal(
            previewModal
        );
    }
);

previewBack.addEventListener(
    "click",
    () => {
        if (isSending) {
            return;
        }

        closeModal(
            previewModal
        );
    }
);

resultsClose.addEventListener(
    "click",
    () => {
        closeModal(
            resultsModal
        );
    }
);

resultsDone.addEventListener(
    "click",
    () => {
        closeModal(
            resultsModal
        );
    }
);

document.addEventListener(
    "keydown",
    (event) => {
        if (event.key === "Escape") {
            if (isSending) {
                return;
            }

            closeRecipientPicker();
            closeModal(previewModal);
            closeModal(resultsModal);
        }
    }
);

sendButton.addEventListener(
    "click",
    sendEmails
);

updateSelectionUI();

initializeMicrosoftAuth()
    .catch((error) => {
        console.error(
            "Microsoft authentication initialization failed:",
            error
        );

        senderEmailDisplay.textContent =
            "Sender unavailable";

        showError(
            "Microsoft authentication could not be initialized."
        );
    });
emailForm.addEventListener("input", () => {composeDirty=true;});
recipientPicker.addEventListener("click", () => {composeDirty=true;});
window.addEventListener("beforeunload", event => {if (composeDirty) {event.preventDefault(); event.returnValue="";}});
document.getElementById("draft-action").addEventListener("click", () => {composeIntent="draft"; requestPreview();});
document.getElementById("schedule-action").addEventListener("click", () => {
    const panel=document.getElementById("schedule-panel");
    if(panel.hidden) {panel.hidden=false; panel.scrollIntoView({block:"center"}); document.getElementById("schedule-start").focus({preventScroll:true}); return;}
    if(!emailForm.reportValidity()) return;
    composeIntent="schedule"; requestPreview();
});
function updateScheduleFields() {
    const frequency = document.getElementById("schedule-frequency").value;
    const recurring = frequency !== "once";
    const interval = document.getElementById("schedule-interval");
    document.getElementById("schedule-interval-field").hidden = !recurring;
    document.getElementById("schedule-end-field").hidden = !recurring;
    interval.disabled = !recurring;
    document.getElementById("schedule-end").disabled = !recurring;
    const unit = {daily: "day", weekly: "week", monthly: "month"}[frequency] || "day";
    document.getElementById("schedule-unit").textContent = unit + (Number(interval.value) === 1 ? "" : "s");
}
document.getElementById("schedule-frequency").addEventListener("change", updateScheduleFields);
document.getElementById("schedule-interval").addEventListener("input", updateScheduleFields);
updateScheduleFields();
document.getElementById("schedule-timezone").value=Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Beirut";
(async () => {
    const id=new URLSearchParams(location.search).get("draft");
    if(!id) return;
    try {
        const d=await composeApi(`/mail/drafts/${encodeURIComponent(id)}`);
        if(d.folder !== "drafts") throw new Error("Restore this draft from Trash before editing.");
        draftId=d.id; draftRevision=d.revision; subjectInput.value=d.subject; contentInput.value=d.content;
        selectableOptions.forEach(o => setSelected(o,d.selected_company_rows.includes(Number(o.dataset.sourceRow))));
        defaultAllSelectionActive=false; updateSelectionUI();
        const missing=d.selected_company_rows.filter(row => !selectableOptions.some(o => Number(o.dataset.sourceRow)===row));
        if(missing.length) showError("Some saved recipient rows are no longer available. Review recipients before sending.");
        if(d.schedule) {
            document.getElementById("schedule-panel").hidden=false;
            restoreScheduleTime(d.schedule.start);
            document.getElementById("schedule-timezone").value=d.schedule.timezone;
            document.getElementById("schedule-frequency").value=d.schedule.frequency;
            document.getElementById("schedule-interval").value=d.schedule.interval;
            document.getElementById("schedule-end").value=d.schedule.end_date || "";
            updateScheduleFields();
        }
        composeDirty=false;
    } catch(error) {showError(error.message);}
})();
