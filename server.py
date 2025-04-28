# server.py
from fastapi import FastAPI, Request # Keep FastAPI's Request
# Add RedirectResponse and JSONResponse
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from google.oauth2.credentials import Credentials
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
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "YOUR_GOOGLE_CLIENT_SECRET")
# This specific redirect URI is often used by OpenAI GPT Actions
REDIRECT_URI = "https://oauth.openai.com/authorization-callback"

# === Google Gmail OAuth Setup ===
# Define the SCOPES for Gmail API
SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly']
GMAIL_TOKEN_FILE = "token.pkl"
GMAIL_CREDENTIALS_FILE = "credentials.json" # Make sure this file exists

# Remove the hardcoded ACCESS_TOKEN line
# ACCESS_TOKEN = os.getenv("GMAIL_ACCESS_TOKEN")  # get from environment variable

# Adapt the get_calendar_service function for Gmail
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
                 raise FileNotFoundError(f"Credentials file not found at {GMAIL_CREDENTIALS_FILE}. Please download it from Google Cloud Console.")
             flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
             creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(GMAIL_TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
    # Build the Gmail service
    service = build('gmail', 'v1', credentials=creds)
    return service

# === Web Server OAuth Endpoints (for GPT Actions, etc.) ===

@app.get("/oauth/authorize")
async def authorize():
    """
    Redirects the user to Google's OAuth consent screen.
    """
    # Note: Using gmail.modify scope as in the example. Adjust if needed.
    # Consider adding other scopes required by your application, space-separated.
    scopes_string = " ".join(SCOPES) # Use scopes defined earlier or customize
    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        # f"&scope=https://www.googleapis.com/auth/gmail.modify" # Original example scope
        f"&scope={scopes_string}" # Using defined SCOPES
        f"&access_type=offline"  # Request refresh token
        f"&prompt=consent"       # Force consent screen even if previously authorized
    )
    return RedirectResponse(url=auth_url)

# Add response_model=None to prevent FastAPI from analyzing the return type
@app.post("/oauth/token", response_model=None)
# Use FastAPI's Request for the type hint
async def token(request: Request):
    """
    Exchanges the authorization code received from Google (via redirect)
    for access and refresh tokens.
    """
    # Check if CLIENT_ID or CLIENT_SECRET are still placeholders
    if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID" or CLIENT_SECRET == "YOUR_GOOGLE_CLIENT_SECRET":
         return JSONResponse(status_code=500, content={"error": "Server configuration error: Google Client ID or Secret not set."})

    try:
        # Access form data from fastapi.Request
        data = await request.form()
        code = data.get("code")
        if not code:
            return JSONResponse(status_code=400, content={"error": "Missing authorization code"})

        # Prepare request to Google's token endpoint
        token_request_data = {
            'code': code,
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code',
        }

        # Send request to exchange code for tokens
        token_response = requests.post(
            "https://oauth2.googleapis.com/token",
            data=token_request_data
        )
        token_response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        # Return the tokens received from Google
        return JSONResponse(content=token_response.json())

    except requests.exceptions.RequestException as e:
        # Log the error for debugging
        print(f"Error exchanging token: {e}")
        # Provide a generic error response
        error_content = {"error": "Failed to exchange authorization code for token"}
        if e.response is not None:
            try:
                error_content["details"] = e.response.json()
            except ValueError: # Handle cases where response is not JSON
                error_content["details"] = e.response.text
        return JSONResponse(status_code=500, content=error_content)
    except Exception as e:
        print(f"Unexpected error in /oauth/token: {e}")
        return JSONResponse(status_code=500, content={"error": "An unexpected error occurred"})

@app.get("/listEmails")
async def list_emails():
    service = get_gmail_service()
    results = service.users().messages().list(userId='me', maxResults=5).execute()
    messages = results.get('messages', [])
    return {"messages": messages}

class SendEmailRequest(BaseModel):
    to: str
    subject: str
    message: str

@app.post("/sendEmail")
async def send_email(request: SendEmailRequest):
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

# Add a main block to run the server if needed
if __name__ == "__main__":
    import uvicorn
    # Ensure required environment variables are set before starting
    if CLIENT_ID == "YOUR_GOOGLE_CLIENT_ID" or CLIENT_SECRET == "YOUR_GOOGLE_CLIENT_SECRET":
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables must be set.")
        # Optionally exit or prevent uvicorn.run if not set
        # exit(1)
    else:
        print("Starting server...")
        print(f"OAuth Client ID: {CLIENT_ID}")
        print(f"OAuth Redirect URI: {REDIRECT_URI}")
        print(f"OAuth Scopes: {' '.join(SCOPES)}")
        uvicorn.run(app, host="0.0.0.0", port=8000)