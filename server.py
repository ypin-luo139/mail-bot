# server.py
from fastapi import FastAPI, Request
from pydantic import BaseModel
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
import os

# Add necessary imports from gg_calendar.py
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

app = FastAPI()

# For demo purpose: put access_token here (in production you must securely refresh it)
ACCESS_TOKEN = os.getenv("GMAIL_ACCESS_TOKEN")  # get from environment variable

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
                creds.refresh(Request())
            except Exception as e:
                print(f"Error refreshing token: {e}. Need to re-authenticate.")
                # If refresh fails, force re-authentication
                flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            # Check if credentials file exists
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
# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)