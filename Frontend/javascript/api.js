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

    /* The 50/30/20 split of everything logged so far, plus any warnings about
     * being over 50/30 or under 20. Shape:
     *   {success, budget: {Need, Want, Savings, NeedPercent, WantPercent,
     *                      SavingsPercent}, warnings: [...]} */
    budget() {
        return request("/budget", { authed: true });
    },

    conversations() {
        return request("/conversations", { authed: true });
    },

    messages(conversationId) {
        return request(`/conversations/${conversationId}/messages`, { authed: true });
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
};
