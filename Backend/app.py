# route logout back to signup (and add the "you have logged out popup")

from  flask import request, Flask, jsonify, url_for, redirect
from flask_cors import CORS
import user as user_file


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

@app.route("/", methods=["GET"])
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

@app.route("/logout")
def logout():
    user_file.logout()

if __name__ == "__main__":
    app.run()
