/* The Kakeibo coach conversation.
 *
 * Matches the Flask contract in Backend/app.py:
 *   POST /chat  {message, conversation_id}  + Authorization: Bearer <token>
 *              -> {success, message, conversation_id}
 * The backend owns the transcript. We send ONE message and the id of the chat
 * it belongs to (null starts a new one); we never replay the history ourselves.
 *
 * On failure the backend rolls the turn back -- the stored user message is
 * deleted, and a brand-new conversation is removed entirely -- so the retry
 * button can re-send the identical text without duplicating it.
 *
 * Works on any page that provides #chatForm, #chatInput and #chatMessages.
 */

const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");
const chatbot = document.getElementById("chatbot");

// The id of the chat we are in. Null until the first reply comes back.
let conversationId = null;

/* api.js has to load first. Say so plainly instead of throwing a
   ReferenceError that only shows up in the console. */
if (typeof api === "undefined") {
    console.error("chat.js needs api.js -- add <script src=\"../javascript/api.js\"></script> before it.");
} else if (chatForm && chatInput && chatMessages) {
    startChat();
}

function startChat() {
    chatForm.addEventListener("submit", function (event) {
        event.preventDefault();

        const message = chatInput.value.trim();
        if (!message) {
            return;
        }

        chatInput.value = "";
        send(message);
    });

    // Reopening a chat from the dashboard dock: ?conversation=<uuid>
    const requested = new URLSearchParams(window.location.search).get("conversation");
    if (requested) {
        conversationId = requested;
        loadTranscript(requested);
    }

    checkCoachHealth();
    loadBudgetSidebar();
}

/* Rendering -------------------------------------------------------------- */
function addMessage(role, text) {
    // The opening nudge only belongs on an empty transcript.
    const empty = document.getElementById("chatEmpty");
    if (empty) {
        empty.remove();
    }

    const bubble = document.createElement("div");
    bubble.classList.add("chat-message", role);
    bubble.textContent = text;
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return bubble;
}

/* An error the user can act on: the same text, one click away from being
   re-sent, because the backend already undid the failed turn. */
function addError(text, retryMessage) {
    const box = document.createElement("div");
    box.classList.add("chat-message", "is-error");
    box.textContent = text;

    if (retryMessage) {
        const retry = document.createElement("button");
        retry.type = "button";
        retry.textContent = "Try again";
        retry.addEventListener("click", function () {
            box.remove();
            send(retryMessage);
        });
        box.appendChild(retry);
    }

    chatMessages.appendChild(box);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

/* Sending ---------------------------------------------------------------- */
async function send(message) {
    if (!auth.isLoggedIn()) {
        addError("Please log in to talk to your coach.");
        return;
    }

    const sent = addMessage("user", message);

    const pending = addMessage("assistant", "…");
    pending.classList.add("is-pending");

    setFormEnabled(false);
    const result = await api.chat(message, conversationId);
    setFormEnabled(true);

    pending.remove();

    if (result.success) {
        conversationId = result.conversation_id;
        addMessage("assistant", result.message);
        return;
    }

    // Mirror the backend's rollback: it deleted its copy of this message, so
    // the bubble goes too. Without this, retrying re-adds the text and the
    // transcript shows it twice for a single send.
    sent.remove();

    // Everything the backend rejects -- rate limit, coach outage, expired
    // session -- arrives as a sentence that is already safe to show.
    addError(result.message, message);
}

function setFormEnabled(enabled) {
    chatInput.disabled = !enabled;
    const button = chatForm.querySelector("button");
    if (button) {
        button.disabled = !enabled;
    }
    if (enabled) {
        chatInput.focus();
    }
}

/* Reopening an existing chat --------------------------------------------- */
async function loadTranscript(id) {
    const result = await api.messages(id);

    if (!result.success) {
        // The id in the URL is unusable -- gone, or somebody else's. Forget it,
        // otherwise every later message is sent against it and fails the same
        // way, with no way out but editing the address bar.
        conversationId = null;
        addError(result.message);
        return;
    }

    result.messages.forEach(function (entry) {
        addMessage(entry.role, entry.content);
    });
}

/* Budget sidebar ----------------------------------------------------------
 * Optional: only the dedicated chat page has it. Same GET /budget the dashboard
 * uses, so the coach and the sidebar never disagree about the numbers.
 * ------------------------------------------------------------------------- */
async function loadBudgetSidebar() {
    if (!document.getElementById("sideNeeds") || !auth.isLoggedIn()) {
        return;
    }

    const result = await api.budget();
    const note = document.getElementById("sideNote");

    if (!result.success) {
        if (note) {
            note.textContent = result.message;
        }
        return;
    }

    const money = new Intl.NumberFormat(undefined, {
        style: "currency", currency: "USD", maximumFractionDigits: 0,
    });

    const budget = result.budget;
    const rows = [
        { key: "sideNeeds", amount: Number(budget.Need) || 0, percent: budget.NeedPercent, target: 50 },
        { key: "sideWants", amount: Number(budget.Want) || 0, percent: budget.WantPercent, target: 30 },
        { key: "sideSavings", amount: Number(budget.Savings) || 0, percent: budget.SavingsPercent, target: 20 },
    ];

    rows.forEach(function (row) {
        const label = document.getElementById(row.key);
        if (label) {
            label.textContent = `${money.format(row.amount)} spent`;
        }

        const fill = document.getElementById(`${row.key}Fill`);
        if (fill) {
            // Share of that category's own target, capped at the track width.
            const used = Math.min(100, ((Number(row.percent) || 0) / row.target) * 100);
            fill.style.width = `${used}%`;
        }
    });

    if (note && result.warnings && result.warnings.length) {
        note.textContent = result.warnings.join(" ");
    }
}

/* Coach availability ------------------------------------------------------ */
async function checkCoachHealth() {
    const available = await api.aiAvailable();
    if (!available && chatbot) {
        // Greys out the composer and reveals the .ai-offline notice.
        chatbot.classList.add("is-offline");
    }
}
