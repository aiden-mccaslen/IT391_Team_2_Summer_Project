/* The monthly Kakeibo review.
 *
 * GET /monthly-report returns the document as Markdown, generating it only if
 * this month has not been written yet. Rendering is markdown.js; this file is
 * just load, show, and the regenerate button.
 */

const reportTitle = document.getElementById("reportTitle");
const reportSubtitle = document.getElementById("reportSubtitle");
const reportBody = document.getElementById("reportBody");
const refreshBtn = document.getElementById("refreshBtn");
const refreshNote = document.getElementById("refreshNote");

/* A logged-out visitor gets sent to login rather than a page of 401s. */
auth.require();

function show(result) {
    if (!result.success) {
        // "No expenses logged yet" arrives here too. It is a real answer, not a
        // failure, so it reads as a sentence rather than an error state.
        reportSubtitle.textContent = "";
        reportBody.innerHTML = `<p>${result.message}</p>`;
        refreshBtn.hidden = true;
        return;
    }

    const report = result.report || {};

    if (report.title) {
        reportTitle.textContent = `Monthly review — ${report.title}`;
    }

    // The stored document opens with its own "# Monthly review — August 2026" so
    // that the .md file stands alone. On this page the heading above already says
    // that, so the document's copy is dropped rather than printed twice.
    const body = String(report.markdown || "").replace(/^#\s+.*\r?\n+/, "");
    reportBody.innerHTML = renderMarkdown(body);

    reportSubtitle.textContent = report.generated
        ? "Written just now by your coach."
        : "Saved earlier this month. Press the button below to write it again.";

    refreshBtn.hidden = false;
}

(async function load() {
    show(await api.monthlyReport());
})();

if (refreshBtn) {
    refreshBtn.addEventListener("click", async function () {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "Writing…";
        refreshNote.hidden = false;
        refreshNote.textContent = "This one takes a few seconds.";

        const result = await api.refreshMonthlyReport();

        refreshBtn.disabled = false;
        refreshBtn.textContent = "Write it again";
        refreshNote.hidden = true;

        show(result);
    });
}
