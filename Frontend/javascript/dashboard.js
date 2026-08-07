/* Dashboard behaviour: greeting and the 50/30/20 figures from GET /budget.
 * The profile dropdown lives in profile-menu.js and the docked coach bar in
 * chat-dock.js -- both shared with expenses.html and chat.html.
 *
 * There is no historical spending series behind /budget, so this page states
 * current totals rather than drawing a trend it would have to invent.
 */

const reflectionForm = document.getElementById("reflectionForm");

/* A logged-out visitor gets sent to login rather than a page of 401s. */
auth.require();

/* The weekly reflection card is a UI stub until there is somewhere to store
   the answer. Say so rather than silently dropping what the user typed. */
if (reflectionForm) {
    reflectionForm.addEventListener("submit", function (event) {
        event.preventDefault();
        alert("Saving weekly reflections is not wired up yet.");
    });
}

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
