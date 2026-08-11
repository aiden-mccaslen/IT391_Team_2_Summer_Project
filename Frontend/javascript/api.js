/* Shared backend access for every page.
 *
 * The Flask layer authenticates each chat/history request with the access token
 * handed out by /login:
 *     Authorization: Bearer <access_token>
 * so the token has to survive a page navigation. It lives in sessionStorage --
 * cleared when the tab closes, and never written to a cookie, so nothing is sent
 * automatically on cross-site requests.
 *
 * Every helper resolves to the parsed JSON body. Network failures are turned
 * into the same {success:false, message} shape the backend returns, so callers
 * only ever handle one thing.
 */

let API_BASE_URL;

if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
) {
    API_BASE_URL = "http://localhost:5000";
} else {
    API_BASE_URL = "https://it391-team-2-summer-project.onrender.com";
}

const TOKEN_KEY = "mb_access_token";
const USER_KEY = "mb_user_id";

const auth = {
    save(result) {
        sessionStorage.setItem(TOKEN_KEY, result.access_token);
        if (result.user_id) {
            sessionStorage.setItem(USER_KEY, result.user_id);
        }
    },

    token() {
        return sessionStorage.getItem(TOKEN_KEY);
    },

    userId() {
        return sessionStorage.getItem(USER_KEY);
    },

    isLoggedIn() {
        return Boolean(sessionStorage.getItem(TOKEN_KEY));
    },

    clear() {
        sessionStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(USER_KEY);
    },

    /* Guard for pages that need a session. Sends the user to login instead of
     * letting the page render and then fail every request with a 401. */
    require() {
        if (!auth.isLoggedIn()) {
            window.location.href = "login.html";
            return false;
        }
        return true;
    },
};

/* One request helper. `authed` adds the bearer header. */
async function request(path, { method = "GET", body = null, authed = false } = {}) {
    const headers = {};
    if (body) {
        headers["Content-Type"] = "application/json";
    }
    if (authed) {
        const token = auth.token();
        if (!token) {
            return { success: false, message: "Not logged in." };
        }
        headers["Authorization"] = `Bearer ${token}`;
    }

    try {
        const response = await fetch(`${API_BASE_URL}${path}`, {
            method,
            headers,
            body: body ? JSON.stringify(body) : undefined,
        });

        // The token expired or was rejected: drop it so the next page load
        // sends the user to login rather than looping on 401s.
        if (response.status === 401 && authed) {
            auth.clear();
        }

        // The server answered, so a parse failure here means it sent something
        // that is not our JSON -- an unhandled Flask traceback page, a proxy
        // error. Reporting that as "is the backend running?" would send anyone
        // debugging it in the wrong direction.
        try {
            return await response.json();
        } catch (parseError) {
            console.error(`Non-JSON response from ${path}:`, parseError);
            return {
                success: false,
                message: `The server returned an unexpected response (${response.status}).`,
            };
        }
    } catch (error) {
        console.error(`Request to ${path} failed:`, error);
        return {
            success: false,
            message: "Could not reach the server. Is the backend running?",
        };
    }
}

const api = {
    login(email, password) {
        return request("/login", { method: "POST", body: { email, password } });
    },

    signup(name, email, password) {
        return request("/signup", { method: "POST", body: { name, email, password } });
    },

    /* One message plus the chat it belongs to (null starts a new one). The
     * backend loads the history itself -- the frontend does not replay it. */
    chat(message, conversationId) {
        return request("/chat", {
            method: "POST",
            authed: true,
            body: { message, conversation_id: conversationId || null },
        });
    },

    /* Same endpoint as chat(), but answered in character as the user's named
     * companion (see kakeibo_ai.COMPANION_SYSTEM) instead of as the coach.
     * Always a fresh conversation -- the companion widget is a quick check-in,
     * not a threaded chat. */
    companionChat(message, companionName) {
        return request("/chat", {
            method: "POST",
            authed: true,
            body: {
                message,
                conversation_id: null,
                companion: true,
                companion_name: companionName || "",
            },
        });
    },

    /* The 50/30/20 split of everything logged so far, plus any warnings about
     * being over 50/30 or under 20. Shape:
     *   {success, budget: {Need, Want, Savings, NeedPercent, WantPercent,
     *                      SavingsPercent}, warnings: [...]} */
    budget() {
        return request("/budget", { authed: true });
    },

    /* This week's coach question plus the answer if one is already saved:
     *   {success, reflection: {id, week_start, question, answer, answered_at}}
     * The question is generated on the first call of the week and stored, so
     * calling this on every dashboard load is cheap. */
    weeklyReflection() {
        return request("/weekly-reflection", { authed: true });
    },

    /* Save (or replace) this week's answer. */
    saveWeeklyReflection(answer) {
        return request("/weekly-reflection", {
            method: "POST",
            authed: true,
            body: { answer },
        });
    },

    conversations() {
        return request("/conversations", { authed: true });
    },

    messages(conversationId) {
        return request(`/conversations/${conversationId}/messages`, { authed: true });
    },


    /* POST /expenses tells an expense from a fund/credit entry by shape --
     * amount+purchase_date+category vs amount+account -- so these stay as two
     * named calls rather than one generic passthrough. */
    addExpense(amount, purchaseDate, category) {
        return request("/expenses", {
            method: "POST",
            authed: true,
            body: { amount, purchase_date: purchaseDate, category },
        });
    },

    addFund(amount, account) {
        return request("/expenses", {
            method: "POST",
            authed: true,
            body: { amount, account },
        });
    },

    /* No login needed. False means the coach is misconfigured server-side, and
     * the chat UI greys itself out instead of letting the user type into a void.
     *
     * Fails OPEN on purpose: if the health check itself cannot be reached, the
     * answer is unknown, and locking the composer over an unanswered question
     * is worse than letting the user try and get a real error back. */
    async aiAvailable() {
        const result = await request("/health/ai");
        return result.ai_available !== false;
    },

    /* This month's Kakeibo review as Markdown:
     *   {success, report: {month, title, markdown, generated}}
     * The backend keeps the document in Supabase Storage, so only the first call
     * of the month is slow -- `generated` says whether this call was that one.
     * Pass "YYYY-MM" to read an earlier month. */
    monthlyReport(month) {
        const query = month ? `?month=${encodeURIComponent(month)}` : "";
        return request(`/monthly-report${query}`, { authed: true });
    },

    /* Rewrite the review from the current expenses. POST rather than GET because
     * it costs a model call -- never fire it from a page load. */
    refreshMonthlyReport(month) {
        return request("/monthly-report", {
            method: "POST",
            authed: true,
            body: { month: month || null },
        });
    },

    /* Just email + name, for the profile page header. Not the same thing as
     * profile() below -- that's the AI-written interview summary. */
    account() {
        return request("/account", { authed: true });
    },

    /* The stored profile from the onboarding interview:
     *   {success, markdown}
     * `markdown` is null when the interview has not been done yet -- a normal
     * state, not an error. */
    profile() {
        return request("/profile", { authed: true });
    },

    /* Summarize an interview into a profile and store it. `transcript` is a
     * string or a list of Q&A lines. Running it again replaces the profile. */
    submitInterview(transcript) {
        return request("/profile/interview", {
            method: "POST",
            authed: true,
            body: { transcript },
        });
    },

    /* The dashboard companion's current mood/level, recomputed from real
     * expense/budget/reflection data on every call:
     *   {success, companion: {name, mood, level, stage, streak, dialogue,
     *                         last_interacted_at}}
     * Purely cosmetic -- nothing else on the page depends on this call. */
    companion() {
        return request("/companion", { authed: true });
    },

    /* Give the companion a name. Cosmetic only, same shape as companion(). */
    setCompanionName(name) {
        return request("/companion/name", {
            method: "POST",
            authed: true,
            body: { name },
        });
    },

    /* The plain feed button -- free, instant, no chat message needed.
     * Returns {success, companion: {happiness, hunger}}. */
    feedCompanion() {
        return request("/companion/feed", { method: "POST", authed: true });
    },

    /* No login needed. False means the companion widget is turned off
     * server-side (COMPANION_ENABLED=false, or the module was removed), and
     * the dashboard should render nothing for it.
     *
     * Fails OPEN on purpose, same as aiAvailable(): if the health check
     * itself cannot be reached, the answer is unknown, and hiding a harmless
     * cosmetic widget over an unanswered question is worse than trying and
     * letting a real error surface instead. */
    async companionAvailable() {
        const result = await request("/health/companion");
        return result.companion_available !== false;
    },
};
