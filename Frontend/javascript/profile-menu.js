/* The avatar/profile dropdown in the app header -- shared by any page that
 * ships the .profile markup (dashboard.html, expenses.html, chat.html).
 * Needs api.js loaded first: auth.clear() lives there.
 */

const avatarBtn = document.getElementById("avatarBtn");
const profileMenu = document.getElementById("profileMenu");
const logoutLink = document.getElementById("logoutLink");

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
        // login.html checks for this and shows the "you have signed out" message.
        window.location.href = "login.html?loggedOut=1";
    });
}
