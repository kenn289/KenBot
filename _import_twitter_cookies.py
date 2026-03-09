"""
Import Twitter/X session cookies from a JSON file exported by your real browser.

HOW TO USE:
1. In your real Chrome/Edge, go to x.com and make sure you're logged in
2. Install the "Cookie-Editor" extension:
   Chrome: https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
   Edge:   https://microsoftedge.microsoft.com/addons/detail/cookieeditor/neaplmfkghagebokkhpjpoebhdledlfi
3. Go to x.com, click the Cookie-Editor extension icon
4. Click "Export" → "Export as JSON" — it copies to clipboard
5. Paste into a new file called: credentials/x_cookies_raw.json
6. Run this script: python _import_twitter_cookies.py
"""
import json
from pathlib import Path

RAW = Path("credentials/x_cookies_raw.json")
OUT = Path("credentials/twitter_session.json")

if not RAW.exists():
    print(f"❌ Not found: {RAW}")
    print("   Follow the instructions at the top of this file.")
    exit(1)

raw = json.loads(RAW.read_text(encoding="utf-8"))

# Cookie-Editor exports slightly different format than Playwright expects
# Playwright needs: name, value, domain, path, secure, httpOnly, sameSite, expires
SAMESITE_MAP = {
    "no_restriction": "None",
    "lax": "Lax",
    "strict": "Strict",
    "unspecified": "None",
}
converted = []
for c in raw:
    raw_ss = (c.get("sameSite") or "no_restriction").lower()
    same_site = SAMESITE_MAP.get(raw_ss, "None")
    entry = {
        "name":     c.get("name", ""),
        "value":    c.get("value", ""),
        "domain":   c.get("domain", ".x.com"),
        "path":     c.get("path", "/"),
        "secure":   c.get("secure", True),
        "httpOnly": c.get("httpOnly", False),
        "sameSite": same_site,
    }
    # Playwright uses 'expires' (float unix timestamp), Cookie-Editor uses 'expirationDate'
    exp = c.get("expirationDate") or c.get("expires")
    if exp:
        entry["expires"] = float(exp)
    converted.append(entry)

OUT.write_text(json.dumps(converted, indent=2))
print(f"✅ Saved {len(converted)} cookies to {OUT}")
print("   Run _test_tweet.py now — the bot will use your real session.")
