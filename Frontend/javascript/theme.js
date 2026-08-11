/* Site-wide dark/light theme.
 *
 * Loaded first, in <head>, right after the stylesheet -- applying the stored
 * preference here (before the body has a chance to paint) is what avoids a
 * flash of the wrong theme on page load. Self-contained: no dependency on
 * api.js, so it can run before that too.
 */

const THEME_KEY = "mb_theme";

const theme = {
    get() {
        return localStorage.getItem(THEME_KEY) ||
            (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    },

    apply(name) {
        document.documentElement.setAttribute("data-theme", name);
    },

    set(name) {
        localStorage.setItem(THEME_KEY, name);
        theme.apply(name);
    },

    toggle() {
        theme.set(theme.get() === "dark" ? "light" : "dark");
    },
};

theme.apply(theme.get());
