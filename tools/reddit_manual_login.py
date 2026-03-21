from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SESSION_PATH = ROOT / "credentials" / "reddit_session.json"
SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("Opening Reddit login browser...")
    print("1) Log in using Reddit username/password (avoid 'Continue with Google')")
    print("2) If Reddit asks for 2FA, complete it")
    print("3) Return to this terminal and press ENTER to save session")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-popup-blocking",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )

        if SESSION_PATH.exists():
            try:
                cookies = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if cookies:
                    context.add_cookies(cookies)
            except Exception:
                pass

        page = context.new_page()

        # Close unexpected popup pages (often blank/about:blank) that break manual login flow
        def _on_new_page(p):
            try:
                u = (p.url or "").lower()
                if not u or u == "about:blank":
                    p.close()
            except Exception:
                pass
        context.on("page", _on_new_page)

        # old.reddit login form is simpler and more stable in automation
        page.goto("https://old.reddit.com/login", wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
        print("Opened: https://old.reddit.com/login")

        input("\nAfter login is complete and you can see Reddit home, press ENTER here to continue...")

        # Do NOT force another navigation here; Reddit may still be redirecting
        # between old/new domains and that can interrupt goto().
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        cookies = context.cookies()
        if not cookies:
            raise RuntimeError("No cookies found after login; session was not captured")
        SESSION_PATH.write_text(json.dumps(cookies), encoding="utf-8")

        browser.close()

    print(f"Saved Reddit session to: {SESSION_PATH}")


if __name__ == "__main__":
    main()
