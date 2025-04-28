# server.py
from fastapi import FastAPI, Request # Keep FastAPI's Request
# Add RedirectResponse, JSONResponse, and Response
from fastapi.responses import RedirectResponse, JSONResponse, Response
from pydantic import BaseModel
# Remove Credentials import if not used elsewhere after change
# from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import os
# Add requests library for token exchange
import requests

# Add necessary imports from gg_calendar.py
from google_auth_oauthlib.flow import InstalledAppFlow
# Rename the google auth request to avoid conflict
from google.auth.transport.requests import Request as GoogleAuthRequest
import pickle

app = FastAPI()

# === Constants for Web OAuth Flow ===
# !! IMPORTANT: Replace with your actual credentials, preferably load from env vars !!
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID_REPLACE_ME")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET_REPLACE_ME")
# This specific redirect URI is often used by OpenAI GPT Actions
REDIRECT_URI = "https://oauth.openai.com/authorization-callback"

# === Google Gmail OAuth Setup (Installed App Flow - for local testing/other uses) ===
# Define the SCOPES for Gmail API - Ensure all needed scopes are listed
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify' # Added modify scope from example
]
GMAIL_TOKEN_FILE = "token.pkl"
GMAIL_CREDENTIALS_FILE = "credentials.json" # Make sure this file exists

# Adapt the get_calendar_service function for Gmail (Used for local testing/non-GPT flows)
def get_gmail_service():
    creds = None
    # Load token if it exists
    if os.path.exists(GMAIL_TOKEN_FILE):
        with open(GMAIL_TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                # Use the renamed GoogleAuthRequest here
                creds.refresh(GoogleAuthRequest())
            except Exception as e:
                print(f"Error refreshing token: {e}. Need to re-authenticate.")
                creds = None # Force re-auth if refresh fails
        # Use 'if not creds:' to handle both initial load failure and refresh failure
        if not creds:
             if not os.path.exists(GMAIL_CREDENTIALS_FILE):
                 # Consider how to handle this in a deployed server context
                 # Maybe return an error or log prominently
                 print(f"ERROR: Credentials file not found at {GMAIL_CREDENTIALS_FILE}. InstalledAppFlow cannot proceed.")
                 raise FileNotFoundError(f"Credentials file not found at {GMAIL_CREDENTIALS_FILE}.")
             flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
             # This flow is interactive and requires a browser - not suitable for the GPT OAuth flow
             # It's kept here for potential local testing or alternative auth methods
             print("Attempting to run local server for InstalledAppFlow - this requires user interaction.")
             creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(GMAIL_TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
    # Build the Gmail service
    service = build('gmail', 'v1', credentials=creds)
    return service


# === Web Server OAuth Endpoints (for GPT Actions, etc.) ===

# Update authorize endpoint to support GET and HEAD
@app.api_route("/oauth/authorize", methods=["GET", "HEAD"])
async def authorize(request: Request): # Add request parameter
    """
    Redirects the user to Google's OAuth consent screen (GET)
    or handles HEAD requests for health checks.
    """
    # For HEAD requests, FastAPI automatically handles returning headers only.
    # We just need to ensure the logic for GET runs correctly.

    # Check if Client ID is set
    if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_REPLACE_ME":
        # For HEAD, returning an error might be okay, or just a 500 status.
        # For GET, return the JSON error.
        return JSONResponse(status_code=500, content={"error": "Server configuration error: Google Client ID not set."})

    # Use the defined SCOPES list, joined by spaces
    scopes_string = " ".join(SCOPES)
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes_string}" # Use defined SCOPES
        f"&access_type=offline"  # Request refresh token
        f"&prompt=consent"       # Force consent screen even if previously authorized
    )
    # Only redirect for GET requests
    if request.method == "GET":
        print(f"Redirecting GET request to Google auth URL: {auth_url}") # Log for debugging
        return RedirectResponse(url=auth_url)
    elif request.method == "HEAD":
        # For HEAD, FastAPI handles sending back appropriate headers based on the GET logic path
        # that would have been taken. We can just return a simple 200 OK response header.
        # Alternatively, let FastAPI handle it implicitly by reaching the end of the function
        # for the HEAD request after checks pass. For explicit control:
        print("Responding to HEAD request for /oauth/authorize")
        return Response(status_code=200) # Return empty 200 OK for HEAD

# Update token endpoint to support POST and HEAD
# Add response_model=None to prevent FastAPI from analyzing the return type
@app.api_route("/oauth/token", methods=["POST", "HEAD"], response_model=None)
# Use FastAPI's Request for the type hint
async def token(request: Request):
    """
    Exchanges the authorization code for tokens (POST)
    or handles HEAD requests for health checks.
    """
    # Handle HEAD request explicitly for health check
    if request.method == "HEAD":
        print("Responding to HEAD request for /oauth/token")
        # Check credentials setup as a basic health indicator
        if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_REPLACE_ME" or CLIENT_SECRET == "YOUR_GOOGLE_CLIENT_SECRET_REPLACE_ME":
             # Return 503 Service Unavailable if not configured
             return Response(status_code=503)
        else:
             # Return 200 OK if configured
             return Response(status_code=200)

    # Proceed with POST logic otherwise
    # Check if Client ID or Secret are set (redundant if checked in HEAD, but safe)
    if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_REPLACE_ME" or CLIENT_SECRET == "YOUR_GOOGLE_CLIENT_SECRET_REPLACE_ME":
         return JSONResponse(status_code=500, content={"error": "Server configuration error: Google Client ID or Secret not set."})

    try:
        # Access form data from fastapi.Request
        data = await request.form()
        code = data.get("code")
        if not code:
            print("Error: Missing authorization code in token request")
            return JSONResponse(status_code=400, content={"error": "Missing authorization code"})

        print(f"Received authorization code: {code[:10]}...") # Log received code (partially)

        # Prepare request to Google's token endpoint
        token_request_data = {
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code',
        }

        print("Exchanging code for token at Google...")
        # Send request to exchange code for tokens
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data=token_request_data
        )
        token_response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        print("Successfully exchanged code for token.")
        # Return the tokens received from Google directly to OpenAI
        return JSONResponse(content=token_response.json())

    except requests.exceptions.RequestException as e:
        # Log the error for debugging
        print(f"Error exchanging token with Google: {e}")
        error_content = {"error": "Failed to exchange authorization code for token with Google"}
        if e.response is not None:
            print(f"Google token endpoint response status: {e.response.status_code}")
            try:
                google_error = e.response.json()
                print(f"Google token endpoint response body: {google_error}")
                error_content["details"] = google_error
            except ValueError: # Handle cases where response is not JSON
                error_content["details"] = e.response.text
                print(f"Google token endpoint response body (non-JSON): {e.response.text}")
            # Return Google's status code if possible
            return JSONResponse(status_code=e.response.status_code, content=error_content)
        else:
             return JSONResponse(status_code=500, content=error_content) # Generic error if no response

    except Exception as e:
        print(f"Unexpected error in /oauth/token: {e}")
        return JSONResponse(status_code=500, content={"error": "An unexpected server error occurred"})


# === Existing API Endpoints ===
# These endpoints currently use the get_gmail_service() which relies on the
# InstalledAppFlow (token.pkl). For the GPT Action to use these, they would
# need to be modified to accept and use the Bearer token provided by OpenAI
# after the /oauth/token exchange. This is a next step after fixing the save issue.

@app.get("/listEmails")
async def list_emails():
    try:
        # NOTE: This uses the token.pkl flow, not the GPT OAuth flow token
        service = get_gmail_service()
        results = service.users().messages().list(userId='me', maxResults=5).execute()
        messages = results.get('messages', [])
        return {"messages": messages}
    except Exception as e:
        print(f"Error in /listEmails: {e}")
        return JSONResponse(status_code=500, content={"error": f"Failed to list emails: {str(e)}"})


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    message: str

@app.post("/sendEmail")
async def send_email(request: SendEmailRequest):
    try:
        # NOTE: This uses the token.pkl flow, not the GPT OAuth flow token
        service = get_gmail_service()
        message = MIMEText(request.message)
        message['to'] = request.to
        message['subject'] = request.subject
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        send_message = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()
        return {"id": send_message['id']}
    except Exception as e:
        print(f"Error in /sendEmail: {e}")
        return JSONResponse(status_code=500, content={"error": f"Failed to send email: {str(e)}"})


# Add a main block to run the server if needed
if __name__ == "__main__":
    import uvicorn
    # Ensure required environment variables are set before starting
    if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID_REPLACE_ME" or CLIENT_SECRET == "YOUR_GOOGLE_CLIENT_SECRET_REPLACE_ME":
        print("ERROR: Set the GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables or replace the placeholders in server.py before running.")
        exit(1)
    else:
        print("Starting server...")
        print(f"OAuth Client ID: {CLIENT_ID}")
        print(f"OAuth Redirect URI: {REDIRECT_URI}")
        print(f"OAuth Scopes: {' '.join(SCOPES)}")
        print(f"GPT Auth URL (GET, HEAD): http://<your_host>:8000/oauth/authorize")
        print(f"GPT Token URL (POST, HEAD): http://<your_host>:8000/oauth/token")
        uvicorn.run(app, host="0.0.0.0", port=8000)