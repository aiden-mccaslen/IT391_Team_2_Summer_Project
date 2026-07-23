# route logout back to signup (and add the "you have logged out popup")

from  flask import Flask, request, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file
import kakeibo_ai


app = Flask(__name__)
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
def home():
    return login.html

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json() # turn what javascript sends to python dictionary
    status = user_file.login(data["email"], data["password"]) 
    # status returns a tuple (true or false depending on suscessful login, error message)
    return jsonify ({
        "success": status[0],
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

if __name__ == "__main__":
    app.run(debug=True)