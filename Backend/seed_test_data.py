# Program that AI generated to create random purchases to have data in an account for testing

import random
from datetime import date, timedelta

import user as user_file
import expenses

TEST_EMAIL = "testemail@gmail.com"
TEST_PASSWORD = "Testpassword1"

CATEGORIES = [
    "Rent/Mortgage",
    "Utilities",
    "Car Payment",
    "Car Insurance",
    "Streaming services",
    "Groceries",
    "Personal",
    "Unexpected",
]


def get_access_token():
    success, result = user_file.login(TEST_EMAIL, TEST_PASSWORD)
    if success:
        return result


def seed_fund(access_token, amount=3000):
    success, result = expenses.report_fund(access_token, amount, "checking")
    print(f"[{'OK' if success else 'FAILED'}] income ${amount} -> {result}")


def seed_expenses(access_token, count=15):
    today = date.today()
    for _ in range(count):
        category = random.choice(CATEGORIES)
        amount = round(random.uniform(10, 300), 2)
        purchase_date = (today - timedelta(days=random.randint(0, 60))).isoformat()

        success, result = expenses.report_expense(access_token, amount, purchase_date, category)
        print(f"[{'OK' if success else 'FAILED'}] {category}: ${amount} on {purchase_date} -> {result}")


if __name__ == "__main__":
    token = get_access_token()
    print(f"Logged in as {TEST_EMAIL}")
    print(f"Access token (paste into localStorage.access_token to view in the browser):\n{token}\n")

    seed_fund(token)
    seed_expenses(token)
    print("Done seeding test data.")