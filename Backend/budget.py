# Maps each expense category to one of the 50/30/20 budget groups.
# Needs are food, clothing and shelter related stuff, all other things are wants
# Might want to consider car payment and insurance as Needs
CATEGORY_MAP = {
    "Rent/Mortgage": "Need",
    "Utilities": "Need",
    "Groceries": "Need",

    "Car Payment": "Want",
    "Car Insurance": "Want",
    "Streaming Services": "Want",
    "Personal": "Want",
    "Unexpected": "Want",

    "Savings": "Savings" # must match a key of `totals` in calculate_totals
}

# expenses is the result from expenses.py's get_expenses function
def calculate_totals(expenses):
    """
    Calculates total spending for Needs, Wants, and Savings.
    """

    totals = {
        "Need": 0.0,
        "Want": 0.0,
        "Savings": 0.0
    }

    for expense in expenses:

        category = expense["category"]
        amount = float(expense["amount"])

        budget_type = CATEGORY_MAP.get(category)

        if budget_type:
            totals[budget_type] += amount

    return totals

# expenses is the result from expenses.py's get_expenses function
# income is the result from expenses.py's get_funds function
def calculate_budget(income, expenses):
    """
    Calculates spending totals and percentages for the 50/30/20 rule.
    """

    totals = calculate_totals(expenses)

    if income <= 0:
        return {
            "Need": totals["Need"],
            "Want": totals["Want"],
            "Savings": totals["Savings"],
            "NeedPercent": 0,
            "WantPercent": 0,
            "SavingsPercent": 0
        }

    return {
        "Need": totals["Need"],
        "Want": totals["Want"],
        "Savings": totals["Savings"],

        "NeedPercent": round((totals["Need"] / income) * 100, 2),
        "WantPercent": round((totals["Want"] / income) * 100, 2),
        "SavingsPercent": round((totals["Savings"] / income) * 100, 2)
    }

def evaluate_budget(summary):

    warnings = []

    if summary["NeedPercent"] > 50:
        warnings.append(
            "Your spending on needs exceeds the recommended 50%."
        )

    if summary["WantPercent"] > 30:
        warnings.append(
            "Your spending on wants exceeds the recommended 30%."
        )

    if summary["SavingsPercent"] < 20:
        warnings.append(
            "You are saving less than the recommended 20%."
        )

    return warnings
