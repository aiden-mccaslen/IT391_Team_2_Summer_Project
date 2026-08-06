console.log("before expense form")
const expenseForm = document.getElementById("expenseForm");
console.log("before fundform")
const fundForm = document.getElementById("fundForm");

// console.log("before dumbshit")
// document.querySelector('form').onsubmit = e => {
//    e.target.submit();
//    e.target.reset();
//    return false;
// };

// const log = document.querySelector("#log");

let API_BASE_URL;

if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
) {
    API_BASE_URL = "http://localhost:5000";
} else {
    API_BASE_URL = "https://it391-team-2-summer-project.onrender.com";
}

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
console.log("before fund if")

if (fundForm) {
    fundForm.addEventListener("submit", function(event) {
        event.preventDefault();
        const fundData = new FormData(fundForm);
        // let amount;
        // let purchase_date;
        // let category = "";
        // for(const entry of data){
        //     console.log("entry: "+entry)

        //     if(entry[0] == "amount"){
        //         amount = entry[1];
        //         // const amount = amountInput.value;
        //         console.log(amount)
        //     }

        //     if(entry[0] == "account"){
        //         account = entry[1];
        //         console.log(category)
        //     }

            
        // }
        const fund = fundData.get("amount");
        const account = fundData.get("account")
        console.log("fund: "+ fund);
        console.log("account: "+ account);
        
        sendFundRequest({amount: fund, account: account});
    });

}

console.log("after fund if")
async function sendFundRequest(fundData) {
    console.log("before try");
    try {
        console.log("start-try");
        const response = await fetch(`${API_BASE_URL}/expenses`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("access_token")}`
            },
            body: JSON.stringify(fundData)
        });
        console.log("bulls");
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