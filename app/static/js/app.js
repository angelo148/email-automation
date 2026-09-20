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
        window.location.replace(
            "/auth/login"
        );
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

function renderResults(data) {
    resultItems.innerHTML =
        "";

    resultSummary.innerHTML =
        "";

    const title =
        document.createElement(
            "div"
        );

    title.className =
        "result-summary-title";

    if (data.failed === 0) {
        title.textContent =
            "All emails completed successfully.";
    } else if (
        data.successful === 0
    ) {
        title.textContent =
            "Email sending failed.";
    } else {
        title.textContent =
            "Email sending completed with some failures.";
    }

    const summary =
        document.createElement(
            "div"
        );

    summary.className =
        "result-summary-text";

    summary.textContent =
        `Sender: ${data.sender} | Total: ${data.total} | Successful: ${data.successful} | Failed: ${data.failed}`;

    resultSummary.appendChild(title);
    resultSummary.appendChild(summary);

    data.results.forEach(
        (result) => {
            const card =
                document.createElement(
                    "div"
                );

            card.className =
                result.success
                    ? "result-card success"
                    : "result-card failure";

            const status =
                document.createElement(
                    "div"
                );

            status.className =
                "result-status";

            status.textContent =
                result.success
                    ? "SENT"
                    : "FAILED";

            const name =
                document.createElement(
                    "div"
                );

            name.className =
                "result-title";

            name.textContent =
                result.name;

            const detail =
                document.createElement(
                    "div"
                );

            detail.className =
                "result-detail";

            detail.textContent =
                result.detail;

            card.appendChild(status);
            card.appendChild(name);
            card.appendChild(detail);
            resultItems.appendChild(card);
        }
    );
}

async function requestPreview() {
    currentPayload =
        buildPayload();

    continueButton.disabled =
        true;

    continueButton.textContent =
        "Preparing Preview...";

    clearError();

    try {
        const response =
            await fetch(
                "/email/preview",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify(
                        currentPayload
                    ),
                }
            );

        const data =
            await response.json();

        if (!response.ok) {
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "Could not create email preview."
            );
        }
        currentPreviewId =
        data.preview_id;

        previewSender.textContent =
            fixedSenderEmail
            || data.sender
            || "Fixed Outlook sender";

        previewCount.textContent =
            `${data.recipient_count} route${data.recipient_count === 1 ? "" : "s"}`;

        senderWarning.textContent =
            "";

        sendButton.disabled =
            false;

        previewSubject.textContent =
            data.subject;

        previewContent.textContent =
            data.content;

        renderRecipients(
            data.recipients
        );

        closeRecipientPicker();

        openModal(
            previewModal
        );

    } catch (error) {
        console.error(
            "Email preview failed.",
            error
        );

        showError(
            error.message
            || "Could not create email preview."
        );

    } finally {
        continueButton.disabled =
            false;

        continueButton.innerHTML =
            'Preview Email <span>→</span>';
    }
}

function convertJobToUiResult(job) {
    return {
        sender:
            job.sender
            || fixedSenderEmail,

        total:
            job.total,

        successful:
            job.accepted,

        failed:
            job.total
            - job.accepted,

        results:
            job.results.map(
                (result) => ({
                    source_row:
                        result.source_row,

                    name:
                        result.name,

                    success:
                        result.status
                        === "accepted",

                    detail:
                        result.detail
                        || (
                            result.status
                            === "accepted"
                                ? "Email accepted by Microsoft Graph."
                                : result.status
                                    === "authentication_required"
                                    ? "Microsoft sign-in is required before this route can continue."
                                    : result.status
                                        === "unknown"
                                        ? "Email outcome is unknown and requires review."
                                        : result.status
                                            === "pending"
                                            ? "Email is pending."
                                            : "Email was not accepted."
                        ),
                })
            ),
    };
}

async function sendEmails() {
    if (
        !currentPreviewId
        || isSending
    ) {
        return;
    }

    isSending = true;

    sessionStorage.setItem(
        "pending_send_preview_id",
        currentPreviewId
    );

    sendButton.disabled =
        true;

    previewBack.disabled =
        true;

    previewClose.disabled =
        true;

    sendButton.textContent =
        "Sending...";

    senderWarning.textContent =
        "";

    try {
        const response =
            await fetch(
                "/email/send-persistent",
                {
                    method: "POST",
                    headers: {
                        "Content-Type":
                            "application/json",
                    },
                    body: JSON.stringify({
                        preview_id:
                            currentPreviewId,
                    }),
                }
            );

        if (
            response.status === 401
        ) {
            window.location.replace(
                "/auth/login"
            );

            return;
        }

        const data =
            await response.json();

        if (!response.ok) {
            if (
                response.status === 404
                || response.status === 409
                || response.status === 422
            ) {
                sessionStorage.removeItem(
                    "pending_send_preview_id"
                );
            }

            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : "Email sending failed."
            );
        }

        sessionStorage.removeItem(
            "pending_send_preview_id"
        );

        const uiResult =
            convertJobToUiResult(
                data
            );

        renderResults(
            uiResult
        );

        closeModal(
            previewModal
        );

        openModal(
            resultsModal
        );

    } catch (error) {
        console.error(
            "Email sending failed.",
            error
        );

        senderWarning.textContent =
            error.message
            || "Email sending failed.";

    } finally {
        isSending = false;

        previewBack.disabled =
            false;

        previewClose.disabled =
            false;

        sendButton.textContent =
            "Send Emails";

        sendButton.disabled =
            false;
    }
}

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