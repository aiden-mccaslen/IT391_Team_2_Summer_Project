/* The docked "Ask your Kakeibo guide" bar -- shared by any page that ships
 * the .chat-dock markup (currently dashboard.html and expenses.html).
 * Needs api.js loaded first: it owns the token and the actual fetch calls.
 */

const dockForm = document.getElementById("dockForm");
const dockInput = document.getElementById("dockInput");

if (dockForm) {
    dockForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const message = dockInput.value.trim();
        if (!message) {
            return;
        }

        const button = dockForm.querySelector("button");
        button.disabled = true;
        button.textContent = "Sending…";

        const result = await api.chat(message, null);

        button.disabled = false;
        button.textContent = "Send";

        if (result.success) {
            // Hand the new conversation to the full chat view, which loads the
            // transcript from the backend -- the reply is never held in memory.
            dockInput.value = "";
            window.location.href =
                `chat.html?conversation=${encodeURIComponent(result.conversation_id)}`;
            return;
        }

        // Rate limits, a coach outage, an expired session -- all arrive as a
        // plain sentence the backend already made safe to display.
        alert(result.message);
    });
}

/* Coach availability ----------------------------------------------------- */
(async function checkCoach() {
    const available = await api.aiAvailable();
    if (!available && dockForm) {
        dockInput.disabled = true;
        dockInput.placeholder = "The coach is unavailable right now.";
        dockForm.querySelector("button").disabled = true;
    }
})();
