//storing forms from HTML
const loginForm = document.getElementById("loginForm");
const signupForm = document.getElementById("signupForm");

//checks
console.log("loaded");
console.log(loginForm);
console.log(signupForm);

//backend URL
const API_BASE_URL = "http://localhost:8000";

//events
if (loginForm) {
    loginForm.addEventListener("submit", function(event) {
        event.preventDefault();

        const emailInput = document.getElementById("email");
        const email = emailInput.value;

        const passwordInput = document.getElementById("password");
        const password = passwordInput.value;

        //check
        console.log(email); 
        console.log(password);

        //backend package
        const loginData = {
            email: email,
            password: password
        };

        //check
        console.log(loginData);

        sendLoginRequest(loginData);
    });

}

//forms
if (signupForm) {
    signupForm.addEventListener("submit", function(event) {
        event.preventDefault();

        const nameInput = document.getElementById("fullName");
        const name = nameInput.value;

        const emailInput = document.getElementById("email");
        const email = emailInput.value;

        const passwordInput = document.getElementById("password");
        const password = passwordInput.value;

         const passwordConfirmationInput = document.getElementById("passwordConfirmation");
         const passwordConfirmation = passwordConfirmationInput.value;

        //validation
        if (password !== passwordConfirmation) {
            alert("Passwords do not match.");
            return;
        }

        //check
        console.log(name);
        console.log(email); 
        console.log(password);

        //backend package
        const signupData = {
            name: name,
            email: email,
            password: password
        };

        //check
        console.log(signupData);

        sendSignupRequest(signupData);
    });
}

//login request to backend
async function sendLoginRequest(loginData) {
    try {
        const response = await fetch(`${API_BASE_URL}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(loginData)
        });

        const result = await response.json();

        console.log("Login response:", result);
    } catch (error) {
        console.error("Login request failed:", error);
    }
}


//signup request to backend
async function sendSignupRequest(signupData) {
    try {
        const response = await fetch(`${API_BASE_URL}/signup`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(signupData)
        });

        const result = await response.json();

        console.log("Signup response:", result);
    } catch (error) {
        console.error("Signup request failed:", error);
    }
}