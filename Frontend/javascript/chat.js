//storing chat elements from HTML
const chatForm = document.getElementById("chatForm");
const chatInput = document.getElementById("chatInput");
const chatMessages = document.getElementById("chatMessages");

//check
console.log("chat loaded");

//backend URL
const API_BASE_URL = "http://localhost:5000"; // matches flask default api

//the full conversation so far. The model API is stateless, so we send the
//whole history to /chat every time. Each item is {role, content}.
const history = [];

//events
if (chatForm) {
    chatForm.addEventListener("submit", function(event) {
        event.preventDefault();

        const message = chatInput.value.trim();
        if (!message) {
            return;
        }

        //check
        console.log(message);

        //show the user's message and remember it
        addMessage("user", message);
        history.push({ role: "user", content: message });

        //clear the box for the next message
        chatInput.value = "";

        sendChatRequest();
    });
}

//adds a message bubble to the chat window and scrolls to the bottom
function addMessage(role, text) {
    const bubble = document.createElement("div");
    bubble.classList.add("chat-message", role); // role is "user" or "assistant"
    bubble.textContent = text;
    chatMessages.appendChild(bubble);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return bubble;
}

//chat request to backend
async function sendChatRequest() {
    //temporary "thinking" bubble while we wait for the coach
    const thinking = addMessage("assistant", "...");

    try {
        const response = await fetch(`${API_BASE_URL}/chat`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ history: history })
        });

        const result = await response.json();

        if (result.success) {
            thinking.textContent = result.message;
            history.push({ role: "assistant", content: result.message });
        }
        else
        {
            thinking.textContent = result.message;
        }

        console.log("Chat response:", result);
    } catch (error) {
        thinking.textContent = "Sorry, I could not reach the coach right now.";
        console.error("Chat request failed:", error);
    }
}
