import budget


def evaluate_purchase(income, expenses, purchase_amount, purchase_category):
    """
    Evaluates whether a purchase follows the user's budgeting rules.
    """
    reasons = []

    simulated_expenses = expenses.copy()

    simulated_expenses.append({
        "amount": purchase_amount,
        "category": purchase_category
    })

    new_budget = budget.calculate_budget(
    income,
    simulated_expenses
    )

    if new_budget["WantPercent"] > 30:
        reasons.append(
            "This purchase would push your Wants spending above the recommended 30%."
        )
    if new_budget["SavingsPercent"] < 20:
        reasons.append(
            "This purchase would reduce your savings below the recommended 20%."
        )

    if len(reasons) == 0:
        approved = True
    else:
        approved = False

    return {
        "approved": approved,
        "reasons": reasons,
        "updated_budget": new_budget
    }