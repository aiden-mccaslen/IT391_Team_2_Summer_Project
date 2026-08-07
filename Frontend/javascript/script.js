/* Login and signup.
 *
 * Handles the forms on login.html, signup.html and the landing page. Needs
 * api.js loaded first -- that is where the backend calls and token storage live.
 *
 * The important part: /login hands back an access_token, and every chat and
 * history endpoint requires it as "Authorization: Bearer <token>". If it is not
 * saved here, the coach can never authenticate. auth.save() puts it in
 * sessionStorage for the rest of the session.
 */

const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");
const formMessage = document.getElementById("formMessage");

if (typeof api === "undefined") {
    console.error("script.js needs api.js -- add <script src=\"../javascript/api.js\"></script> before it.");
}

/* Feedback. Uses the inline message element where the page has one, and falls
   back to alert() on the older pages that do not. */
function showMessage(text, kind) {
    if (!formMessage) {
        alert(text);
        return;
    }
    formMessage.textContent = text;
    formMessage.className = `form-message is-${kind}`;
}

function clearMessage() {
    if (formMessage) {
        formMessage.textContent = "";
        formMessage.className = "form-message";
    }
}

// Logging out redirects here with ?loggedOut=1
if (new URLSearchParams(window.location.search).get("loggedOut")) {
    showMessage("You have signed out.", "success");
}

function setBusy(form, busy, label) {
    const button = form.querySelector("button[type=submit]");
    if (!button) {
        return;
    }
    button.disabled = busy;
    if (busy) {
        button.dataset.idleLabel = button.textContent;
        button.textContent = label;
    } else if (button.dataset.idleLabel) {
        button.textContent = button.dataset.idleLabel;
    }
}

/* Login ------------------------------------------------------------------ */
if (loginForm) {
    loginForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        clearMessage();

        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;

        setBusy(loginForm, true, "Logging in…");
        const result = await api.login(email, password);
        setBusy(loginForm, false);

        if (!result.success) {
            showMessage(result.message, "error");
            return;
        }

        // Without this the session is anonymous and /chat returns 401.
        auth.save(result);
        window.location.href = "dashboard.html";
    });
}

/* Signup ----------------------------------------------------------------- */
if (signupForm) {
    signupForm.addEventListener("submit", async function (event) {
        event.preventDefault();
        clearMessage();

        const name = document.getElementById("fullName").value.trim();
        const email = document.getElementById("email").value.trim();
        const password = document.getElementById("password").value;
        const confirmationField = document.getElementById("passwordConfirmation");

        if (confirmationField && password !== confirmationField.value) {
            showMessage("Those passwords do not match. Give it another try.", "error");
            return;
        }

        if (password.length < 8) {
            showMessage("Passwords need to be at least 8 characters.", "error");
            return;
        }

        setBusy(signupForm, true, "Creating your account…");
        const result = await api.signup(name, email, password);
        setBusy(signupForm, false);

        if (!result.success) {
            showMessage(result.message, "error");
            return;
        }

        // Signup does not return tokens -- the user logs in as a separate step.
        showMessage("Account created. Taking you to the login page…", "success");
        setTimeout(function () {
            window.location.href = "login.html";
        }, 1200);
    });
}
