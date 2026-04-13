"""
Run this once to generate a Google Ads refresh token for pete@clinicmastery.com.
It opens a browser window — sign in with pete@clinicmastery.com when prompted.
Paste the printed refresh token into GOOGLE_ADS_REFRESH_TOKEN in your .env file.

Usage:
    python get_refresh_token.py
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_ADS_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET")

# Google Ads requires this exact scope
SCOPES = ["https://www.googleapis.com/auth/adwords"]

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

# Opens a local browser tab — sign in as pete@clinicmastery.com
credentials = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

print("\n" + "=" * 60)
print("SUCCESS — copy this into your .env file:")
print("=" * 60)
print(f"\nGOOGLE_ADS_REFRESH_TOKEN={credentials.refresh_token}\n")
