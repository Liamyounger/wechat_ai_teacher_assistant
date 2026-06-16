"""Run on local PC with a display. Opens browser, user logs into Quark,
then cookies are exported to cookies.json for upload to the server."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUTPUT = Path(__file__).resolve().parent.parent / "python-service" / "config" / "cookies.json"


def main():
    print("Opening browser for Quark login...")
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://pan.quark.cn/")
        print("\nPlease log in to Quark in the browser window.")
        print("After login, press Enter in this terminal to export cookies...")
        input()

        cookies = context.cookies()
        browser.close()

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cookies": [
            {"name": c["name"], "value": c["value"], "domain": c.get("domain", "")}
            for c in cookies
        ],
        "created_at": time.time(),
    }
    OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Cookies exported to {OUTPUT}")
    print("Copy this file to the server: python-service/config/cookies.json")


if __name__ == "__main__":
    main()
