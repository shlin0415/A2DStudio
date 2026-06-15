"""Quick check: ReviewPanel visibility on stage page."""

import os, json
from pathlib import Path
from playwright.sync_api import sync_playwright

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = _PROJECT_ROOT / "tmp"

STAGE_URL = "http://localhost:5173/stage"
_HEADED = os.environ.get("A2D_E2E_HEADLESS", "").strip() not in ("1", "true", "yes")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not _HEADED)
        page = browser.new_page(viewport={"width": 1280, "height": 720})

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto(STAGE_URL, wait_until="networkidle")
        page.wait_for_timeout(3000)

        # Click "开始对话"
        btn = page.locator("button:has-text('开始对话')")
        if btn.is_visible():
            print("[1] Clicking '开始对话'...")
            btn.click()
            page.wait_for_timeout(10000)

        # Check DOM for ReviewPanel text
        dom = page.evaluate("""
            () => {
                const panel = document.querySelector('.review-panel');
                const preview = document.querySelector('.preview-text');
                const statusText = document.querySelector('.status-text');
                const editArea = document.querySelector('.edit-area');
                const textarea = document.querySelector('.text-editor');
                return {
                    hasReviewPanel: !!panel,
                    hasPreviewText: !!preview,
                    previewContent: preview ? preview.textContent : null,
                    statusText: statusText ? statusText.textContent : null,
                    hasEditArea: !!editArea,
                    textareaValue: textarea ? textarea.value : null,
                    panelHTML: panel ? panel.innerHTML.slice(0, 500) : 'NO PANEL',
                };
            }
        """)

        print(json.dumps(dom, ensure_ascii=False, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
