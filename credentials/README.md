# credentials/

This directory holds OAuth tokens and service account keys.
It is gitignored — NEVER commit these files.

## Required files

| File | How to get it |
|---|---|
| `google_oauth.json` | Google Cloud Console → Create OAuth 2.0 Client ID (Desktop) → Download JSON |
| `youtube_token.pickle` | Auto-generated on first YouTube upload |

## Google Cloud Console steps

1. Go to https://console.cloud.google.com
2. Create a new project (e.g., "Ken ClawdBot")
3. Enable APIs:
   - YouTube Data API v3
   - Google Drive API (optional, for large video storage)
4. Go to APIs & Services → Credentials
5. Create Credentials → OAuth 2.0 Client ID → Desktop app
6. Download the JSON and save as `credentials/google_oauth.json`
7. Add your Google account as a test user (OAuth consent screen → Test users)
