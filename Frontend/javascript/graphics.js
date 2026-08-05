const ctx = document.getElementById('myChart');
let myChart; // Instantiate the chart to be blank so that we can call it in setChartType and manipulate it
let budgetSummary; // instantiate the data { Need, Want, Savings, NeedPercent, WantPercent, SavingsPercent } so chart-type switches don't refetch

const API_BASE_URL = "http://localhost:5000";

// Canvas doesn't resolve CSS custom properties, so read them once into plain hex strings.
const rootStyles = getComputedStyle(document.documentElement);
const CATEGORY_COLORS = {
    Need: rootStyles.getPropertyValue('--needs-color').trim(),
    Want: rootStyles.getPropertyValue('--wants-color').trim(),
    Savings: rootStyles.getPropertyValue('--savings-color').trim()
};
const CHART_GRIDLINE_COLOR = rootStyles.getPropertyValue('--chart-gridline').trim();

window.addEventListener("DOMContentLoaded", loadDashboard);

async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE_URL}/budget`, {
            method: "GET",
            headers: {
                "Authorization": `Bearer ${localStorage.getItem("access_token")}`
            }
        });
        const result = await response.json();
        console.log("Budget response:", result);

        if (!result.success) {
            alert(result.message);
            return;
        }

        budgetSummary = result.budget;
        renderBreakdown(budgetSummary, result.warnings);
        createChart(budgetSummary, "bar");

        // Only safe to switch chart types once budgetSummary is actually populated.
        for (const button of document.querySelectorAll("#chartTypeToggle button")) {
            button.disabled = false;
        }
    } catch (error) {
        console.error("Failed to load budget data:", error);
    }
}

function renderBreakdown(budget, warnings) {
    const list = document.getElementById("breakdownList");
    list.innerHTML = "";

    const rows = [
        { label: `Needs (${budget.NeedPercent}%)`, amount: budget.Need, color: CATEGORY_COLORS.Need },
        { label: `Wants (${budget.WantPercent}%)`, amount: budget.Want, color: CATEGORY_COLORS.Want },
        { label: `Savings (${budget.SavingsPercent}%)`, amount: budget.Savings, color: CATEGORY_COLORS.Savings }
    ];

    for (const row of rows) {
        const item = document.createElement("li");

        const swatch = document.createElement("span");
        swatch.className = "legend-swatch";
        swatch.style.backgroundColor = row.color;

        const label = document.createElement("span");
        label.className = "legend-label";
        label.textContent = row.label;

        const amount = document.createElement("span");
        amount.className = "legend-amount";
        amount.textContent = `$${row.amount.toFixed(2)}`;

        item.append(swatch, label, amount);
        list.appendChild(item);
    }

    const warningsBox = document.getElementById("warningsList");
    warningsBox.innerHTML = "";
    for (const warning of warnings) {
        const chip = document.createElement("p");
        chip.className = "warning-chip";
        chip.textContent = warning;
        warningsBox.appendChild(chip);
    }
}

function setChartType(chartType) { // This function is overwriting the old chart with the same data but updated type
    if (!budgetSummary) {
        console.warn("Chart data hasn't loaded yet; ignoring chart-type change.");
        return;
    }
    if (myChart) {
        myChart.destroy();
    }
    createChart(budgetSummary, chartType);
}

function createChart(budget, type) {
    const labels = ["Needs", "Wants", "Savings"];
    const values = [budget.Need, budget.Want, budget.Savings];
    const colors = [CATEGORY_COLORS.Need, CATEGORY_COLORS.Want, CATEGORY_COLORS.Savings];

    myChart = new Chart(ctx, {
        type: type,
        data: {
            labels: labels,
            datasets: [{
                label: "Amount ($)",
                data: values,
                backgroundColor: colors,
                borderRadius: 4,
                borderSkipped: type === "bar" ? "bottom" : undefined,
                maxBarThickness: 24
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                // The breakdown card already serves as the legend (swatch + label + amount),
                // so Chart.js's own legend would just be a redundant single-entry box.
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (item) => `$${item.parsed.y ?? item.parsed}`
                    }
                }
            },
            scales: type === "pie" ? {} : {
                y: {
                    beginAtZero: true,
                    grid: { color: CHART_GRIDLINE_COLOR },
                    ticks: { callback: (value) => `$${value}` }
                },
                x: {
                    grid: { display: false }
                }
            }
        }
    });
}