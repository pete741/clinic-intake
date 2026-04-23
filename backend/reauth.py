"""
One-command Google Ads token refresh.

Usage:
    python reauth.py

What it does:
  1. Opens browser to re-authorise clinicmasteryads@gmail.com
  2. Saves the new refresh token to .env
  3. Copies it to clipboard
  4. Prints the Render update command
  5. Records the refresh timestamp so the expiry reminder knows when to fire
"""

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

ENV_FILE = Path(__file__).parent / ".env"
load_dotenv(ENV_FILE)

CLIENT_ID     = os.getenv("GOOGLE_ADS_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_ADS_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    print("ERROR: GOOGLE_ADS_CLIENT_ID or GOOGLE_ADS_CLIENT_SECRET not set in .env")
    sys.exit(1)

client_config = {
    "installed": {
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": ["http://localhost"],
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
    }
}

print("\n🔐 Opening browser — log in as clinicmasteryads@gmail.com and approve access...\n")

flow = InstalledAppFlow.from_client_config(
    client_config,
    scopes=["https://www.googleapis.com/auth/adwords"],
)
creds = flow.run_local_server(port=8085, open_browser=True)
new_token = creds.refresh_token
refreshed_at = datetime.now(timezone.utc).isoformat()

# ── Update .env ────────────────────────────────────────────────────────────────
env_text = ENV_FILE.read_text()

def _replace_or_append(text: str, key: str, value: str) -> str:
    import re
    pattern = rf"^{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, text, re.MULTILINE):
        return re.sub(pattern, replacement, text, flags=re.MULTILINE)
    return text + f"\n{replacement}\n"

env_text = _replace_or_append(env_text, "GOOGLE_ADS_REFRESH_TOKEN", new_token)
env_text = _replace_or_append(env_text, "GOOGLE_ADS_TOKEN_REFRESHED_AT", refreshed_at)
ENV_FILE.write_text(env_text)

# ── Copy to clipboard ──────────────────────────────────────────────────────────
try:
    subprocess.run(["pbcopy"], input=new_token.encode(), check=True)
    clipboard_msg = "✅ Token copied to clipboard"
except Exception:
    clipboard_msg = "(clipboard copy failed — copy manually from below)"

print("\n" + "=" * 65)
print("✅ .env updated")
print(f"✅ Refresh timestamp recorded: {refreshed_at}")
print(clipboard_msg)
print("=" * 65)
print("\n📋 Now update Render — go to:")
print("   dashboard.render.com → clinic-intake → Environment\n")
print("   GOOGLE_ADS_REFRESH_TOKEN =")
print(f"   {new_token}\n")
print("   GOOGLE_ADS_TOKEN_REFRESHED_AT =")
print(f"   {refreshed_at}\n")
print("=" * 65)
print("⏰ Next refresh due: within 6 days")
print("=" * 65 + "\n")
