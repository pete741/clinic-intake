# Clinic Intake System

A complete onboarding intake system for allied health clinics.

Clinics fill in a 4-step form → data lands in GoHighLevel as a contact with all custom fields populated and the right tags set → GHL workflows fire emails automatically → if Google Ads access is granted, a background job pulls account data and writes the summary back to the GHL contact.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), Tailwind CSS |
| Backend | Python 3.11+, FastAPI, uvicorn |
| CRM | GoHighLevel REST API v2 |
| Ads data | google-ads Python library |
| Email | GHL workflows (tag-triggered, no email code in backend) |
| Background jobs | FastAPI BackgroundTasks (upgrade to Celery later) |
| State | `.env` + `polling_state.json` (upgrade to Postgres later) |

---

## Prerequisites

- **Node 18+** — [nodejs.org](https://nodejs.org)
- **Python 3.11+** — [python.org](https://python.org)
- **GoHighLevel account** with a Private Integration Token and Location ID
- **Google Ads developer token** (for the Ads polling feature)

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd clinic-intake
```

### 2. Backend setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Copy the example env file and fill in your credentials
cp .env.example .env
```

Edit `backend/.env` with your real credentials (see credential guides below).

### 3. Frontend setup

```bash
cd frontend
npm install

# Create the frontend env file
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

---

## Credentials — how to get each one

### GHL Private Integration Token

1. Log into GoHighLevel
2. Go to **Settings → Integrations → API Keys**
3. Click **Create Key**, choose **Private Integration Token**
4. Copy the token → paste into `GHL_API_KEY` in your `.env`

### GHL Location ID

1. In GoHighLevel, go to **Settings → Business Profile**
2. Scroll down to **Location ID**
3. Copy the value → paste into `GHL_LOCATION_ID` in your `.env`

### Google Ads credentials

You need OAuth2 credentials for the **pete@clinicmastery.com** Google account (the account clinics grant read-only access to).

#### Step A — Create OAuth credentials in Google Cloud Console

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or use an existing one)
3. Enable the **Google Ads API** in Library
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON — note the `client_id` and `client_secret`

#### Step B — Get your developer token

1. Sign into your Google Ads **manager account** at [ads.google.com](https://ads.google.com)
2. Go to **Tools → API Center**
3. Apply for a developer token (basic access is sufficient for read-only pulls)

#### Step C — Generate a refresh token

The google-ads library ships a utility for this. Run it once logged in as pete@clinicmastery.com:

```bash
cd backend
source venv/bin/activate
python -c "
from google.ads.googleads.client import GoogleAdsClient
# Follow the prompts — it will open a browser and give you a refresh token
"
```

Or use the official utility:

```bash
python -m google.ads.googleads.util.generate_refresh_token \
  --client_id YOUR_CLIENT_ID \
  --client_secret YOUR_CLIENT_SECRET
```

Paste the refresh token into `GOOGLE_ADS_REFRESH_TOKEN` in your `.env`.

---

## Running locally

### Start the backend

```bash
cd backend
source venv/bin/activate
uvicorn main:app --reload
```

The API will be at `http://localhost:8000`. Visit `http://localhost:8000/docs` for the interactive Swagger UI.

### Start the frontend

```bash
cd frontend
npm run dev
```

The form will be at `http://localhost:3000`.

---

## One-time GHL custom field setup

On first startup, the backend calls `setup_custom_fields()` automatically. You can also run it manually:

```bash
cd backend
source venv/bin/activate
python -c "from ghl import setup_custom_fields; import asyncio; asyncio.run(setup_custom_fields())"
```

This creates all 19 custom fields in GHL and saves a `field_ids.json` cache file so they're never re-created. Check `field_ids.json` to confirm each field has a real ID.

---

## GHL workflow setup (manual — do this after the backend is working)

All emails are sent by GHL workflows triggered by contact tags. No email code lives in the backend. Set up these three workflows in **GHL → Automations → Workflows**:

### Workflow 1 — Internal notification to pete

- **Trigger:** Contact tag added = `intake-submitted`
- **Action:** Send email to `pete@clinicmastery.com.au`
- **Subject:** `New intake submitted — {{contact.name}}`
- **Body:** Use GHL custom values to include all intake fields

### Workflow 2 — Google Ads invite follow-up to clinic

- **Trigger:** Contact tag added = `ads-invite-pending`
- **Wait:** 1 hour
- **Action:** Send email to `{{contact.email}}`
- **Subject:** `One quick step to unlock your full growth brief`
- **Body:** Include the 6-step Google Ads invite instructions with `pete@clinicmastery.com` displayed prominently

### Workflow 3 — Expired invite follow-up

- **Trigger:** Contact tag added = `ads-invite-expired`
- **Action 1:** Send email to `{{contact.email}}`
- **Action 2:** Create a task assigned to `pete@clinicmastery.com.au` to follow up manually

### Tag reference

| Tag | When it's applied | GHL action |
|---|---|---|
| `intake-submitted` | Every submission | Sends internal notification to pete |
| `ads-invite-confirmed` | Clinic says they sent the invite | Polling starts — no immediate email |
| `ads-invite-pending` | Has Google Ads but hasn't sent invite yet | GHL sends follow-up instructions after 1h |
| `ads-invite-expired` | 72h polling with no access found | GHL sends follow-up + creates manual task |
| `ads-not-applicable` | No Google Ads account | No automated follow-up needed |
| `specialty-{name}` | Every submission | Useful for GHL filtering/segmentation |

---

## Deployment

### Backend — Railway (recommended)

1. Push the `backend/` directory to a GitHub repo
2. Create a new Railway project, connect the repo
3. Set all env vars from your `.env` in Railway's Variables tab
4. Railway auto-detects the `requirements.txt` and deploys

### Frontend — Vercel (recommended)

1. Push the `frontend/` directory to a GitHub repo
2. Import the project in Vercel
3. Set `NEXT_PUBLIC_API_URL` to your Railway backend URL
4. Deploy

Update the `FRONTEND_URL` env var on Railway to your Vercel URL so CORS works correctly.

---

## Monitoring the Google Ads polling loop

Polling state is stored in `backend/polling_state.json`. Each entry looks like:

```json
{
  "ghl_contact_id_here": {
    "clinic_name": "Bayside Physio",
    "ghl_contact_id": "ghl_contact_id_here",
    "status": "pending",
    "started_at": "2024-01-15T09:00:00+00:00",
    "cancel": false
  }
}
```

**Status values:** `pending` → `complete` or `expired` or `cancelled`

To cancel a polling task externally:

```bash
cd backend
python -c "
from google_ads import cancel_polling
cancel_polling('THE_GHL_CONTACT_ID')
"
```

---

## Weekly maintenance — revoking Google Ads access

After a clinic call, if they don't convert, remove pete@clinicmastery.com's access from their Google Ads account:

1. Log into the clinic's Google Ads account
2. Go to **Admin → Access and security → Users**
3. Find `pete@clinicmastery.com`
4. Click the three-dot menu → **Remove**

Do this weekly to keep the accessible accounts list clean and avoid confusion in the polling loop.

---

## Troubleshooting

**GHL contact not being created**
- Check `GHL_API_KEY` and `GHL_LOCATION_ID` are set correctly in `.env`
- Check the backend logs — GHL errors are logged with the full response body
- Run the custom field setup manually and check `field_ids.json` has real IDs

**Google Ads polling not finding the account**
- The match is by clinic name word overlap — make sure the name in Google Ads matches closely
- Check the backend logs for the list of accessible accounts being found
- Confirm the refresh token in `.env` is for pete@clinicmastery.com (not a different account)

**CORS errors in the browser**
- Make sure `FRONTEND_URL` in your backend `.env` matches exactly where Next.js is running
- Restart the backend after changing env vars
