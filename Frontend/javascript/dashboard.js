/* Dashboard behaviour: profile menu, the docked coach bar, the AI health check,
 * and the 50/30/20 figures from GET /budget.
 *
 * There is no historical spending series behind /budget, so this page states
 * current totals rather than drawing a trend it would have to invent.
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
        window.location.href = "home.html";
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

/* Weekly reflection ------------------------------------------------------
 * One coach question per week from GET /weekly-reflection, and the answer goes
 * back with POST. Submitting is Enter in the input -- the card has no button.
 * ------------------------------------------------------------------------- */
const reflectionInput = document.getElementById("reflectionInput");
const reflectionQuestion = document.getElementById("reflectionQuestion");
const reflectionStatus = document.getElementById("reflectionStatus");

function showReflectionStatus(text) {
    if (reflectionStatus) {
        reflectionStatus.textContent = text;
        reflectionStatus.hidden = !text;
    }
}

if (reflectionForm) {
    (async function loadReflection() {
        const result = await api.weeklyReflection();

        if (!result.success) {
            if (reflectionQuestion) {
                reflectionQuestion.textContent =
                    "This week's question could not be loaded.";
            }
            reflectionInput.disabled = true;
            showReflectionStatus(result.message);
            return;
        }

        const reflection = result.reflection || {};
        if (reflectionQuestion && reflection.question) {
            reflectionQuestion.textContent = `"${reflection.question}"`;
        }

        // Coming back later in the same week shows what was written, editable --
        // saving again replaces it.
        if (reflection.answer) {
            reflectionInput.value = reflection.answer;
            showReflectionStatus("Saved. Press Enter to update it.");
        }
    })();

    reflectionForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const answer = reflectionInput.value.trim();
        if (!answer) {
            return;
        }

        reflectionInput.disabled = true;
        showReflectionStatus("Saving…");

        const result = await api.saveWeeklyReflection(answer);

        reflectionInput.disabled = false;
        showReflectionStatus(result.success
            ? "Saved. Press Enter to update it."
            : result.message);
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
    if (heading) {
        const hour = new Date().getHours();
        const partOfDay = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
        heading.textContent = `Good ${partOfDay}`;
    }

    const monthName = document.getElementById("monthName");
    if (monthName) {
        monthName.textContent = new Date().toLocaleString(undefined, { month: "long" });
    }
})();

/* Budget ------------------------------------------------------------------
 * Everything on this page comes from GET /budget. The 50/30/20 targets are
 * fixed; the amounts and percentages are whatever the user has logged.
 * ------------------------------------------------------------------------- */
const money = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
});

function setText(id, text) {
    const node = document.getElementById(id);
    if (node) {
        node.textContent = text;
    }
}

(async function loadBudget() {
    const result = await api.budget();

    if (!result.success) {
        setText("barsDesc", "Your spending could not be loaded.");
        setText("spendSplit", result.message);
        return;
    }

    const budget = result.budget;
    const needs = Number(budget.Need) || 0;
    const wants = Number(budget.Want) || 0;
    const savings = Number(budget.Savings) || 0;
    const total = needs + wants + savings;

    setText("dashboardTotal", money.format(total));
    setText("savedAmount", money.format(savings));

    // Bars are drawn against the largest category, not against income: with no
    // income logged every percentage is 0, and three flat bars would say less
    // than three bars in proportion to each other.
    const tallest = Math.max(needs, wants, savings, 1);
    const rows = [
        { key: "needs", label: "Needs", amount: needs, percent: budget.NeedPercent },
        { key: "wants", label: "Wants", amount: wants, percent: budget.WantPercent },
        { key: "savings", label: "Savings and debt", amount: savings, percent: budget.SavingsPercent },
    ];

    rows.forEach(function (row) {
        const bar = document.getElementById(`${row.key}Bar`);
        if (bar) {
            // Floor at 2% so a non-zero category is never an invisible sliver.
            const height = row.amount > 0
                ? Math.max(2, (row.amount / tallest) * 100)
                : 0;
            bar.style.height = `${height}%`;
        }

        setText(`${row.key}Value`, money.format(row.amount));
        setText(`${row.key}Amount`, money.format(row.amount));
        setText(`${row.key}Cell`, money.format(row.amount));
        setText(`${row.key}PctCell`, `${Number(row.percent) || 0}%`);
    });

    setText("barsDesc", rows.map(function (row) {
        return `${row.label} ${money.format(row.amount)}`;
    }).join(", ") + ".");

    if (total > 0) {
        setText("spendSplit",
            `Needs ${budget.NeedPercent}% · Wants ${budget.WantPercent}% · ` +
            `Savings ${budget.SavingsPercent}% of your income.`);
    }

    // Savings bar is progress toward the 20% target, capped so overshooting
    // reads as "done" rather than overflowing the track.
    const savingsPercent = Number(budget.SavingsPercent) || 0;
    const towardTarget = Math.min(100, (savingsPercent / 20) * 100);
    const fill = document.getElementById("savingsFill");
    if (fill) {
        fill.style.width = `${towardTarget}%`;
    }

    const track = document.getElementById("savingsTrack");
    if (track) {
        track.setAttribute("aria-label",
            `${Math.round(towardTarget)} percent of the way to the 20 percent savings target`);
    }

    if (savingsPercent > 0) {
        setText("savingsNote",
            `${savingsPercent}% of your income, against a 20% target.`);
    }

    // Warnings are the app's nudge, not an alarm -- they are phrased by the
    // backend and shown as plain text.
    const warningBox = document.getElementById("budgetWarnings");
    if (warningBox && result.warnings && result.warnings.length) {
        warningBox.textContent = result.warnings.join(" ");
        warningBox.hidden = false;
    }
})();
