console.log("before expense form")
const expenseForm = document.getElementById("expenseForm");
console.log("before fundform")
const fundForm = document.getElementById("fundForm");

if (typeof api === "undefined") {
    console.error("script.js needs api.js -- add <script src=\"../javascript/api.js\"></script> before it.");
}

// const API_BASE_URL = "http://localhost:5000";
console.log("Before first log")
console.log(expenseForm)
console.log("if")
if (expenseForm) {
    console.log("in if")
    expenseForm.addEventListener("submit", function(event) {
        event.preventDefault();

        const data = new FormData(expenseForm);
        console.log("data: "+data);
        let amount;
        let purchase_date;
        let category = "";
        for(const entry of data){
            console.log("entry: "+entry)

            if(entry[0] == "amount"){
                amount = entry[1];
                // const amount = amountInput.value;
                console.log(amount)
            }

            if(entry[0] == "date"){
                purchase_date = entry[1];
                console.log(purchase_date)
            }

            if(entry[0] == "category"){
                category = entry[1];
                console.log(category)
            }

            
        }
        // testing
        console.log(amount); 
        console.log(purchase_date);
        console.log(category);
        //backend package
        const expenseData = {
            amount: amount,
            purchase_date: purchase_date,
            category: category
        };
        // testing
        console.log("Expense Data: ", expenseData);
        console.log("before call")
        sendExpenseRequest(expenseData);
    });
    console.log("after event listener")
}

async function sendExpenseRequest(expenseData) {
    console.log("try")
    try {
        console.log("top of try")
        const response = await fetch(`${API_BASE_URL}/expenses`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("access_token")}`
            },
            body: JSON.stringify(expenseData)
        });
        console.log("after fetch")
        const result = await response.json();
        console.log("after away")
        if (result.success) {
            window.location.href = "../html/expenses.html";
        }
        else
        {
            alert(result.message);
        }

        console.log("Expense response:", result);
    } catch (error) {
        console.error("Expense request failed:", error);
    }
}

if (fundForm) {
    fundForm.addEventListener("submit", function(event) {
        event.preventDefault();
        const fundData = new FormData(fundForm);
        const fund = fundData.get("amount");
        const account = fundData.get("account")
        console.log("fund: "+ fund);
        console.log("account: "+ account);
        
        sendFundRequest({amount: fund, account: account});
    });

}

async function sendFundRequest(fundData) {
    try {
        const response = await fetch(`${API_BASE_URL}/expenses`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("access_token")}`
            },
            body: JSON.stringify(fundData)
        });
        const result = await response.json();

        if (result.success) {
            window.location.href = "../html/expenses.html";
        }
        else
        {
            alert(result.message);
        }

        console.log("Expense response:", result);
    } catch (error) {
        console.error("Expense request failed:", error);
    }
}