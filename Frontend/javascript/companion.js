/* Dashboard companion widget: a cosmetic mood/level readout of the same
 * expense/budget/reflection data the rest of the dashboard already shows (see
 * Backend/companion.py). It never blocks or gates anything -- it only draws
 * itself, or does not.
 *
 * Self-guarding, same shape as every block in dashboard.js: if #companionWidget
 * is not on the page, or /health/companion says the feature is off, this file
 * renders nothing and touches nothing else on the page.
 */

const companionWidget = document.getElementById("companionWidget");

if (companionWidget) {
    (async function loadCompanion() {
        const available = await api.companionAvailable();
        if (!available) {
            return; // stays hidden -- the markup ships with the `hidden` attribute
        }

        const companionSprite = document.getElementById("companionSprite");
        const companionName = document.getElementById("companionName");
        const companionLevel = document.getElementById("companionLevel");
        const companionDialogue = document.getElementById("companionDialogue");
        const companionNameForm = document.getElementById("companionNameForm");
        const companionNameInput = document.getElementById("companionNameInput");
        const companionStatus = document.getElementById("companionStatus");

        // One glyph per mood -- a placeholder for real sprite art later.
        const SPRITES = { positive: "\u{1F425}", neutral: "\u{1F423}", neglected: "\u{1F95A}" };

        function showStatus(text) {
            if (companionStatus) {
                companionStatus.textContent = text;
                companionStatus.hidden = !text;
            }
        }

        function render(state) {
            companionWidget.hidden = false;
            companionWidget.dataset.mood = state.mood || "neutral";

            if (companionSprite) {
                companionSprite.textContent = SPRITES[state.mood] || SPRITES.neutral;
            }
            if (companionName) {
                companionName.textContent = state.name || "Your companion";
            }
            if (companionLevel) {
                companionLevel.textContent = `Level ${Number(state.level) || 0}`;
            }
            if (companionDialogue && state.dialogue) {
                companionDialogue.textContent = state.dialogue;
            }
            // Only pre-fill on first render -- never clobber what the user is
            // currently typing into the rename box.
            if (companionNameInput && !companionNameInput.value && state.name) {
                companionNameInput.value = state.name;
            }
        }

        const result = await api.companion();
        if (!result.success) {
            return; // stays hidden -- an outage here should not draw attention
        }
        render(result.companion || {});

        if (companionNameForm) {
            companionNameForm.addEventListener("submit", async function (event) {
                event.preventDefault();

                const name = companionNameInput.value.trim();
                if (!name) {
                    return;
                }

                companionNameInput.disabled = true;
                showStatus("Saving…");

                const saveResult = await api.setCompanionName(name);

                companionNameInput.disabled = false;

                if (saveResult.success) {
                    render(saveResult.companion || {});
                    showStatus("Saved.");
                } else {
                    showStatus(saveResult.message);
                }
            });
        }
    })();
}
