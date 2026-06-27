from dotenv import load_dotenv
import os
from supabase import create_client, Client

load_dotenv()

url : str = os.getenv("SUPABASE_URL")
key :str = os.getenv("SUPABASE_KEY")
supabase_client : Client = create_client(url, key)

def signup(name, email, password):
# supabase checks length of password (password should be > 8 chars long)
# can implement other password rules as required
    response = supabase_client.auth.sign_up({"email": email, "password": password,
                                             "options": {
                                                 "data":{
                                                     "full_name": name,
                                                     "display_name": name,
                                                 }
                                             }})
    # Response contains: {'user': {'email': '...', ...}}

    if (response != None):
        return (True, "No errors")
    
    return (False, "Unknown error has occured")

def login(email, password):
    response = supabase_client.auth.sign_in_with_password({"email": email, "password": password})
    # Response contains: {'access_token': '...', 'refresh_token': '...', 'user': {...}}

    if (response != None):
        return (True, "No error")
    
    return (False, "Unknown error has occured")

def logout():
    supabase_client.auth.sign_out()
    # Returns: None