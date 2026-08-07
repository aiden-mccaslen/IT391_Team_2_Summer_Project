/* The initial interview.
 *
 * Five fixed questions, asked one at a time, collected into a transcript and
 * sent once to POST /profile/interview. The backend summarizes it into the
 * profile it stores for this user.
 *
 * The questions are hardcoded on purpose: they are the same for everybody, so
 * generating them would be paying the model to produce a constant. The single
 * model call happens at the end, on the transcript.
 */

const QUESTIONS = [
    "What are you hoping money will let you do in the next year or two?",
    "What does your money usually get spent on that you would call worth it?",
    "Where does your money go that you later wish it had not?",
    "When you think about your finances, what worries you most?",
    "What would 'doing well with money' look like for you six months from now?",
];

const interviewLocked = document.getElementById("interviewLocked");
const interviewForm = document.getElementById("interviewForm");
const interviewResult = document.getElementById("interviewResult");
const interviewProgress = document.getElementById("interviewProgress");
const interviewQuestion = document.getElementById("interviewQuestion");
const interviewStatus = document.getElementById("interviewStatus");
const answerForm = document.getElementById("answerForm");
const answerInput = document.getElementById("answerInput");
const answerBtn = document.getElementById("answerBtn");
const profileBody = document.getElementById("profileBody");
const retakeLink = document.getElementById("retakeLink");

const answers = [];
let step = 0;

function showStatus(text) {
    if (interviewStatus) {
        interviewStatus.textContent = text || "";
        interviewStatus.hidden = !text;
    }
}

function showQuestion() {
    interviewProgress.textContent = `Question ${step + 1} of ${QUESTIONS.length}`;
    interviewQuestion.textContent = QUESTIONS[step];
    answerBtn.textContent = step === QUESTIONS.length - 1 ? "Finish" : "Next";
    answerInput.value = "";
    answerInput.focus();
}

function showProfile(markdown) {
    profileBody.innerHTML = renderMarkdown(markdown);
    interviewForm.hidden = true;
    interviewLocked.hidden = true;
    interviewResult.hidden = false;
}

function startInterview() {
    answers.length = 0;
    step = 0;
    interviewResult.hidden = true;
    interviewLocked.hidden = true;
    interviewForm.hidden = false;
    showStatus("");
    showQuestion();
}

/* On load: a signed-out visitor gets the sign-up nudge, someone who has already
 * done this gets their profile back, and everyone else starts at question one. */
(async function init() {
    if (!auth.isLoggedIn()) {
        interviewLocked.hidden = false;
        return;
    }

    const result = await api.profile();

    if (result.success && result.markdown) {
        showProfile(result.markdown);
        return;
    }

    startInterview();

    // A profile that could not be READ is not the same as not having one. The
    // interview is still offered, but the reason is on screen -- otherwise this
    // looks exactly like a first visit and the user retakes it for nothing.
    if (!result.success) {
        showStatus(result.message);
    }
})();

if (answerForm) {
    answerForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const answer = answerInput.value.trim();
        if (!answer) {
            return;
        }

        answers.push(`Q: ${QUESTIONS[step]}\nA: ${answer}`);
        step += 1;

        if (step < QUESTIONS.length) {
            showQuestion();
            return;
        }

        // Last answer in: summarize the whole thing.
        answerBtn.disabled = true;
        answerInput.disabled = true;
        showStatus("Your coach is reading your answers…");

        const result = await api.submitInterview(answers.join("\n\n"));

        answerBtn.disabled = false;
        answerInput.disabled = false;

        if (!result.success) {
            // Keep the answers: the transcript is still in memory, so a retry
            // does not mean typing all five again.
            step -= 1;
            answers.pop();
            showStatus(result.message);
            showQuestion();
            return;
        }

        showProfile(result.markdown);
    });
}

if (retakeLink) {
    retakeLink.addEventListener("click", function (event) {
        event.preventDefault();
        startInterview();
    });
}
