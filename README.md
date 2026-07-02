# IT391_Team_2_Summer_Project
The following is the combined work of: Aiden McCaslen, Ram Paramatmuni, Shalom Adiboshi, Vadim Korypaev, and Austin Marinich

Week of 6/15/26
    We are currently in progress of creating the bones of the program. Such as the UI and basic inputs.
Create venv (windows)
    python -m venv myVenv
    .\myVenv\Scripts\Activate.ps1

To install requirements
    pip install -r requirements.txt

To add to requirements
    pip freeze > requirements.txt (after installing dependencies)

To run the app
    make sure the requirements are installed (check above command)
    run 'python app.py' (in the backend folder)
    install live server by Ritwick Dey on vs code
    open your html page with live server (right click the html file and open with liveserver)

To close the app
    press ctrl + c on the terminal to close the flask app
    close the webpage

Important notes
    DO NOT try to use the http link flask gives you, it will not work (for now, working on fixing it)
    Put all files in the apporpriate folders and do not move the files, the program is very sensitive and moving files will break the program