from dotenv import load_dotenv
import os
from supabase import create_client, Client, ClientOptions, AuthApiError


load_dotenv()

url : str = os.getenv("SUPABASE_URL")
key :str = os.getenv("SUPABASE_KEY")
supabase_client : Client = create_client(url, key)
# NOTE: supabase_client is shared by every request the server handles. It is fine
# for signup/login/get_user_id (those take the email/password/token as arguments),
# but it must NEVER be logged in as one particular user -- see client_for_token.

def signup(name, email, password):
# supabase checks length of password (password should be > 8 chars long)
# can implement other password rules as required
    try:
        response = supabase_client.auth.sign_up({"email": email, "password": password,
                                                "options": {
                                                        "data":{
                                                                "full_name": name,
                                                                "display_name": name,
                                                        }
                                                }
        })
        # Response contains: {'user': {'email': '...', ...}}

        if (response != None):
            return (True, "No errors")
        
        return (False, "Unknown error has occured")
    except AuthApiError as e:
        return (False,  str(e))
    except Exception as e:
        return (False,  str(e))

def login(email, password):
    try:
        response = supabase_client.auth.sign_in_with_password({"email": email, "password": password})
        # Response contains: {'access_token': '...', 'refresh_token': '...', 'user': {...}}

        if (response != None and response.session != None):
            # Hand the tokens back to the caller. The frontend stores access_token
            # and sends it as "Authorization: Bearer <token>" on /chat and
            # /conversations, which is how the backend knows who is asking.
            return (True, {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
                "user_id": response.user.id,
            })

        return (False, "Username or password incorrect")
    except AuthApiError as e:
        return (False,  str(e))
    except Exception as e:
        return (False,  str(e))

def logout():
    try:
        supabase_client.auth.sign_out()
    except AuthApiError as e:
        return (False,  str(e))
    except Exception as e:
        return (False,  str(e))
    # Returns: None

def get_user_id(token):
# Checks the access token the frontend sent in the "Authorization: Bearer <token>"
# header and tells us which user it belongs to. This is how every chat/history
# endpoint knows who is calling.
    try:
        response = supabase_client.auth.get_user(token)
        # Passing the token in explicitly means Supabase validates THAT token and
        # returns its user. It does not sign supabase_client in as anybody, so the
        # shared client's auth state is left alone (see the note at the top).

        if (response == None or response.user == None):
            return (False, "Invalid or expired token")

        return (True, response.user.id)
    except AuthApiError as e:
        return (False,  str(e))
    except Exception as e:
        return (False,  str(e))

def client_for_token(token):
# Builds a throwaway Supabase client that talks to the database AS the logged-in
# user, for one request only.
#
# The constraint: we cannot use supabase_client for this. It is one shared object
# for the whole server, so logging a user into it (or calling postgrest.auth on it)
# would bleed that user's identity into everyone else's requests. Instead we make a
# fresh client whose Authorization header is this user's access token -- that token
# is what the Row Level Security policies in migrations/001_chat_history.sql read
# via auth.uid(), so the database itself enforces "you only see your own chats".
#
# Returns a Client (not a tuple) -- it is just a constructor.
    return create_client(
        url,
        key,
        options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )