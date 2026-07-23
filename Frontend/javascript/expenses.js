const expenseForm = document.getElementById("expenseForm");
const fundForm = document.getElementById("fundForm");

// const log = document.querySelector("#log");

const API_BASE_URL = "http://localhost:5000";

console.log(expenseForm)

if (expenseForm) {
    expenseForm.addEventListener("submit", function(event) {
        event.preventDefault();
        const data = new FormData(expenseForm);
        console.log("data: "+data);
        let amount;
        let date;
        let expenseType = "";
        for(const entry of data){
            console.log("entry: "+entry)

            if(entry[0] == "amount"){
                amount = entry[1];
                // const amount = amountInput.value;
                console.log(amount)
            }

            if(entry[0] == "date"){
                date = entry[1];
                console.log(date)
            }

            if(entry[0] == "expense"){
                expenseType = entry[1];
                console.log(expenseType)
            }

            
        }
        // testing
        console.log(amount); 
        console.log(date);
        console.log(expenseType);
        //backend package
        const expenseData = {
            amount: amount,
            date: date,
            expenseType: expenseType
        };
        // testing
        console.log(expenseData);

        sendExpenseRequest(expenseData);
    });

}

async function sendExpenseRequest(expenseData) {
    try {
        const response = await fetch(`${API_BASE_URL}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(expenseData)
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

if (fundForm) {
    fundForm.addEventListener("submit", function(event) {
        event.preventDefault();
        const fundData = new FormData(fundForm);
        const fund = fundData.get("amount");
        console.log("fund: "+ fund);
        sendFundRequest(fundData);
    });

}

async function sendFundRequest(fundData) {
    try {
        const response = await fetch(`${API_BASE_URL}/login`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
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