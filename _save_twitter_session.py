"""
Run this script once to manually log in to X in a real browser window.
Your session cookies will be saved and the bot will reuse them automatically.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_PATH = Path("credentials/twitter_session.json")
SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=False, args=["--window-size=1280,900"])
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
        locale="en-US",
    )
    page = context.new_page()
    page.goto("https://x.com/login")

    print("\n>>> Log in manually in the browser window that just opened.")
    print(">>> Once you're on the X home feed, press ENTER here to save your session.\n")
    input("Press ENTER after you're logged in...")

    cookies = context.cookies()
    SESSION_PATH.write_text(json.dumps(cookies, indent=2))
    print(f"\n✅ Session saved to {SESSION_PATH}")
    print("The bot will now use this session — no more login needed.\n")
    browser.close()
