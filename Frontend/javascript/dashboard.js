/* Dashboard behaviour: profile menu, the docked coach bar, and the AI health
 * check. The figures on the page are still placeholders -- there are no expense
 * or savings endpoints yet -- so nothing here invents numbers.
 */

const avatarBtn = document.getElementById("avatarBtn");
const profileMenu = document.getElementById("profileMenu");
const logoutLink = document.getElementById("logoutLink");
const dockForm = document.getElementById("dockForm");
const dockInput = document.getElementById("dockInput");
const reflectionForm = document.getElementById("reflectionForm");

/* A logged-out visitor gets sent to login rather than a page of 401s. */
auth.require();

/* Profile dropdown ------------------------------------------------------- */
if (avatarBtn && profileMenu) {
    avatarBtn.addEventListener("click", function (event) {
        event.stopPropagation();
        const isOpen = !profileMenu.hidden;
        profileMenu.hidden = isOpen;
        avatarBtn.setAttribute("aria-expanded", String(!isOpen));
    });

    // Click-away and Escape both close it, so it never traps focus.
    document.addEventListener("click", function () {
        profileMenu.hidden = true;
        avatarBtn.setAttribute("aria-expanded", "false");
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !profileMenu.hidden) {
            profileMenu.hidden = true;
            avatarBtn.setAttribute("aria-expanded", "false");
            avatarBtn.focus();
        }
    });

    profileMenu.addEventListener("click", function (event) {
        event.stopPropagation();
    });
}

if (logoutLink) {
    logoutLink.addEventListener("click", function (event) {
        event.preventDefault();
        auth.clear();
        window.location.href = "index.html";
    });
}

/* Docked coach bar ------------------------------------------------------- */
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

/* The weekly reflection card is a UI stub until there is somewhere to store
   the answer. Say so rather than silently dropping what the user typed. */
if (reflectionForm) {
    reflectionForm.addEventListener("submit", function (event) {
        event.preventDefault();
        alert("Saving weekly reflections is not wired up yet.");
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

/* Greeting --------------------------------------------------------------- */
(function greet() {
    const heading = document.getElementById("greeting");
    if (!heading) {
        return;
    }

    const hour = new Date().getHours();
    const partOfDay = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
    heading.textContent = `Good ${partOfDay}`;
})();
