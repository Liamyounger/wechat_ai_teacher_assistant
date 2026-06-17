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

        # Step 1: Login on pan.quark.cn
        page.goto("https://pan.quark.cn/")
        print("\nPlease log in to Quark in the browser window.")
        print("After login, press Enter in this terminal to continue...")
        input()

        # Step 2: Visit drive-pc.quark.cn to set domain-specific cookies
        print("Capturing drive API cookies...")
        try:
            page.goto("https://drive-pc.quark.cn/1/clouddrive/file/sort?pr=pc&pwd=1&pdir_fid=0&_page=1&_size=5&_sort=file_type:asc,updated_at:desc", timeout=10000)
        except Exception:
            pass  # JSON response may not render as HTML page — that's fine

        # Step 3: Trigger an API call from the main page to ensure all cookies are set
        page.goto("https://pan.quark.cn/")
        page.wait_for_timeout(2000)

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
    print(f"\nExported {len(cookies)} cookies to {OUTPUT}")
    print("Copy this file to the server: python-service/config/cookies.json")


if __name__ == "__main__":
    main()
