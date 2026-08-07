const expenseForm = document.getElementById("expenseForm");
const fundForm = document.getElementById("fundForm");

if (typeof api === "undefined") {
    console.error("expenses.js needs api.js -- add <script src=\"../javascript/api.js\"></script> before it.");
}

auth.require();

if (expenseForm) {
    expenseForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const data = new FormData(expenseForm);
        const amount = data.get("amount");
        const purchaseDate = data.get("date");
        const category = data.get("category");

        const result = await api.addExpense(amount, purchaseDate, category);

        if (result.success) {
            // Redirecting back to the same page resets the form
            window.location.href = "expenses.html";
        } else {
            alert(result.message);
        }
    });
}

if (fundForm) {
    fundForm.addEventListener("submit", async function (event) {
        event.preventDefault();

        const data = new FormData(fundForm);
        const amount = data.get("amount");
        const account = data.get("account");

        const result = await api.addFund(amount, account);

        if (result.success) {
            window.location.href = "expenses.html";
        } else {
            alert(result.message);
        }
    });
}
