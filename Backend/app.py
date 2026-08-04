# route logout back to signup (and add the "you have logged out popup")

from  flask import Flask, request, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file
import kakeibo_ai
import expenses
import budget
import fee_monitor
import purchase_rules

app = Flask(__name__, static_folder="../Frontend", static_url_path="")
CORS(app) # change this to restrict endpoints later

'''
@app.route("/test", methods=["POST"])
# /test is an endpoint in flask e.g https://5500/test and "/" is the deafult page e.g https://5500
# HTTP Methods (CRUD)
# GET    - Retrieve/read data from the server.
# POST   - Send data to create a new resource or perform an action.
# PUT    - Replace an existing resource with new data.
# PATCH  - Update specific fields of an existing resource.
# DELETE - Remove a resource from the server.
def signup(): # can only have 1 function per flask route
    data = request.get_json() # reads the JSON data sent in the HTTP request body and converts it into a Python dictionary.
    status = user_file.signup(data["name"], data["email"], data["password"])
    # status returns a tuple (true or false depending on suscessful login, error message)
    return jsonify ({
        "success": status[0],
        "message": status[1]
    })
'''

@app.route("/")
def home(): # This needs to be fixed maybe? If we run the app then run the liveserver, it errors.
    return redirect("/html/home.html")

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() # turn what javascript sends to python dictionary
    status = user_file.login(data["email"], data["password"]) 
    # status returns a tuple (true or false, and either an access_token on success or an error message on failure)
    if status[0]:
        return jsonify({
            "success": True,
            "access_token": status[1]
        })
    return jsonify({
        "success": False,
        "message": status[1]
    })

@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json()
    status = user_file.signup(data["name"], data["email"], data["password"])
    # status returns a tuple (true or false depending on suscessful login, error message)
    return jsonify ({
        "success": status[0],
        "message": status[1]
    })

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json() # turn what javascript sends to python dictionary
    # history is the full conversation so far: [{"role": "user"/"assistant", "content": "..."}]
    # The model API is stateless, so the frontend sends the whole thing each time.
    history = data["history"]
    status = kakeibo_ai.ask_coach(history)
    # status returns a tuple (true or false depending on success, reply text or error message)
    return jsonify ({
        "success": status[0],
        "message": status[1]
    })

@app.route("/logout")
def logout():
    user_file.logout()

@app.route("/expenses", methods=["POST"])
def expense():
    print("expense routed")
    data = request.get_json() 
    access_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    if(len(data) > 2):
        amount = data["amount"]
        purchase_date = data["purchase_date"]
        category = data["category"]
        print(access_token)
        status = expenses.report_expense(access_token, amount, purchase_date, category)
    else:
        amount = data["amount"]
        account = data["account"]
        status = expenses.report_fund(access_token, amount, account)

    return jsonify ({
        "success": status[0],
        "message": status[1]
    })

@app.route("/budget", methods=["GET"])
def get_budget():

    access_token = request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()

    success, expenses_data = expenses.get_expenses(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": expenses_data
        })

    success, funds_data = expenses.get_funds(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    income = 0

    if len(funds_data) > 0:
        income = float(funds_data[0]["amount"])

    summary = budget.calculate_budget(income, expenses_data)
    warnings = budget.evaluate_budget(summary)

    return jsonify({
        "success": True,
        "budget": summary,
        "warnings": warnings
    })


@app.route("/fees", methods=["GET"])
def get_fee_warnings():

    access_token = request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()

    success, fees = fee_monitor.get_fees(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": fees
        })

    warnings = fee_monitor.check_fee_warnings(fees)

    return jsonify({
        "success": True,
        "warnings": warnings
    })

@app.route("/purchase-rules", methods=["POST"])
def evaluate_purchase():

    data = request.get_json()

    access_token = request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()

    success, expenses_data = expenses.get_expenses(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": expenses_data
        })

    success, funds_data = expenses.get_funds(access_token)

    if not success:
        return jsonify({
            "success": False,
            "message": funds_data
        })

    income = float(funds_data[0]["amount"])

    result = purchase_rules.evaluate_purchase(
    income,
    expenses_data,
    float(data["amount"]),
    data["category"]
    )

    return jsonify({
    "success": True,
    "result": result
    })


if __name__ == "__main__":
    app.run(debug=True) #, port=5500)