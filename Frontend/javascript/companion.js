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
        const companionChatForm = document.getElementById("companionChatForm");
        const companionChatInput = document.getElementById("companionChatInput");
        const companionFeedBtn = document.getElementById("companionFeedBtn");
        const companionStatus = document.getElementById("companionStatus");
        const companionHappinessFill = document.getElementById("companionHappinessFill");
        const companionHappinessValue = document.getElementById("companionHappinessValue");
        const companionHungerFill = document.getElementById("companionHungerFill");
        const companionHungerValue = document.getElementById("companionHungerValue");

        // Hatch stage comes first, mood only picks the glyph within it -- an
        // egg means "not named yet", not "in a bad mood". Naming is what
        // hatches it, so a neglected-but-named companion should never look
        // unhatched again just because its stats dropped.
        const EGG_SPRITE = "\u{1F95A}";
        const CHICK_SPRITES = { positive: "\u{1F425}", neutral: "\u{1F423}", neglected: "\u{1F423}" };

        // Kept in sync by render() so the chat handler below can send it with
        // every message -- it's what lets the AI answer in character as this
        // companion instead of as the generic coach (see api.companionChat).
        let currentCompanionName = "";

        function showStatus(text) {
            if (companionStatus) {
                companionStatus.textContent = text;
                companionStatus.hidden = !text;
            }
        }

        function render(state) {
            companionWidget.hidden = false;
            companionWidget.dataset.mood = state.mood || "neutral";
            currentCompanionName = state.name || "";

            if (companionSprite) {
                companionSprite.textContent = state.name
                    ? (CHICK_SPRITES[state.mood] || CHICK_SPRITES.neutral)
                    : EGG_SPRITE;
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

            const happiness = Math.max(0, Math.min(100, Number(state.happiness) || 0));
            if (companionHappinessFill) {
                companionHappinessFill.style.width = `${happiness}%`;
            }
            if (companionHappinessValue) {
                companionHappinessValue.textContent = `${happiness}%`;
            }

            const hunger = Math.max(0, Math.min(100, Number(state.hunger) || 0));
            if (companionHungerFill) {
                companionHungerFill.style.width = `${hunger}%`;
            }
            if (companionHungerValue) {
                companionHungerValue.textContent = `${hunger}%`;
            }

            // Only pre-fill on first render -- never clobber what the user is
            // currently typing into the rename box.
            if (companionNameInput && !companionNameInput.value && state.name) {
                companionNameInput.value = state.name;
            }

            // Once named, the naming form's job is done -- that slot becomes the
            // chat input instead of staying a rename box.
            const named = Boolean(state.name);
            if (companionNameForm) {
                companionNameForm.hidden = named;
            }
            if (companionChatForm) {
                companionChatForm.hidden = !named;
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

        if (companionChatForm) {
            companionChatForm.addEventListener("submit", async function (event) {
                event.preventDefault();

                const message = companionChatInput.value.trim();
                if (!message) {
                    return;
                }

                companionChatInput.value = "";
                companionChatInput.disabled = true;
                companionChatForm.querySelector("button").disabled = true;
                showStatus("Thinking…");

                // companionChat (not chat()) is what answers in character as
                // this companion instead of as the generic coach. A fresh
                // conversation every time on purpose -- this is a quick poke
                // at your companion, not a threaded chat.
                const chatResult = await api.companionChat(message, currentCompanionName);

                companionChatInput.disabled = false;
                companionChatForm.querySelector("button").disabled = false;

                if (!chatResult.success) {
                    showStatus(chatResult.message);
                    return;
                }

                showStatus("");

                // The chat call already fed happiness/hunger server-side
                // (companion.record_chat_interaction) -- re-fetch so the bars
                // and mood/sprite catch up right away instead of waiting for
                // the next page load. render() would overwrite the dialogue
                // line with the canned mood text, though, so the actual reply
                // goes back in afterward -- it's more relevant right now than
                // a generic line would be.
                const refreshed = await api.companion();
                if (refreshed.success) {
                    render(refreshed.companion || {});
                }
                if (companionDialogue) {
                    companionDialogue.textContent = chatResult.message;
                }
            });
        }

        if (companionFeedBtn) {
            companionFeedBtn.addEventListener("click", async function () {
                companionFeedBtn.disabled = true;
                showStatus("Feeding…");

                const feedResult = await api.feedCompanion();

                companionFeedBtn.disabled = false;

                if (!feedResult.success) {
                    showStatus(feedResult.message);
                    return;
                }

                showStatus("");

                // feedCompanion() only returns {happiness, hunger} -- render()
                // needs the full state (name/mood/level/dialogue), so re-fetch
                // rather than passing that partial object straight to render().
                // Passing it directly would blank the name back to "Your
                // companion" and re-show the naming form, since render() reads
                // state.name to decide which form to display.
                const refreshed = await api.companion();
                if (refreshed.success) {
                    render(refreshed.companion || {});
                }
            });
        }
    })();
}
