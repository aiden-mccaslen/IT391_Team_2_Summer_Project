/* profile.html behaviour: account details and the dark mode toggle.
 * Needs api.js (for the account call) and theme.js (for the toggle itself),
 * both loaded before this.
 */

auth.require();

/* Account -------------------------------------------------------------- */
(async function loadAccount() {
    const result = await api.account();
    const status = document.getElementById("accountStatus");
    const details = document.getElementById("accountDetails");

    if (!result.success) {
        status.textContent = result.message;
        return;
    }

    const account = result.account;
    document.getElementById("accountName").textContent = account.name || "Not set";
    document.getElementById("accountEmail").textContent = account.email;

    status.hidden = true;
    details.hidden = false;
})();

/* Dark mode -------------------------------------------------------------- */
const darkModeToggle = document.getElementById("darkModeToggle");
if (darkModeToggle) {
    darkModeToggle.checked = theme.get() === "dark";

    darkModeToggle.addEventListener("change", function () {
        theme.set(darkModeToggle.checked ? "dark" : "light");
    });
}
