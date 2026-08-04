const ctx = document.getElementById('myChart');
let myChart; // Instantiate the chart to be blank so that we can call it in setChartType and manipulate it
let jsonData; // Instantiate the jsonData so that we don't have to call for it multiple times if we choose to update it.


const API_BASE_URL = "http://localhost:5000";

async function onClickGraph(){
    console.log("Button cliked to create user graph");
    const response = await fetch(`${API_BASE_URL}/graphics`, {
            method: "GET",
            headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${localStorage.getItem("access_token")}`
            },
        });
    const result = await response.json();
    console.log("Response: ", result);

    if (result.success) {
        jsonData = result.data;
        createChart(jsonData, "bar");
    } else {
        alert(result.message);
    }
}

function setChartType(chartType) { // This function is overwriting the old chart with the same data but updated type
    myChart.destroy();
    createChart(jsonData, chartType);
}

// Maybe make this function async to wait and show only when pressing which graph you want to see in the html
// I need to pass JSON data with 'purchase_date' and 'amount'
function createChart(data, type){ // Data is the JSON data, type is the type of chart        maybe -> , dataCol is the data being graph (e.g. am)
    myChart = new Chart(ctx, {
    type: type, // type of graph
    data: {
        labels: data.map(row => row.purchase_date),
        datasets: [{
        label: 'Amount by Purchase Date',
        data: data.map(row => row.amount),
        borderWidth: 1 // Sets the top of the graph 1 higher than max index
        }]
    },
    options: {
        scales: {
        y: {
            beginAtZero: true
        },
        },
        maintainApectRatio: true
    }
    });
}