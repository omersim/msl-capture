"""
Core capture logic — 4 modes:
  fullpage      : full-page Playwright screenshot
  element       : screenshot of a single CSS selector
  pdf           : download PDF, convert each page → PNG via pdftoppm
  xlsx          : render spreadsheet → PNG via LibreOffice headless
"""
import asyncio
import hashlib
import os
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

# ── constants ────────────────────────────────────────────────────────────────
TIMEOUT_MS = 60_000          # 60 s hard limit
DEFAULT_VIEWPORT = 1440
CF_BLOCK_STATUSES = {403, 429, 503}

# User-agent that looks like a real browser
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── helpers ───────────────────────────────────────────────────────────────────
def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _crop(img_bytes: bytes, crop: dict | None) -> bytes:
    """PIL crop — pixels only, no text drawing (Hebrew gibberish risk)."""
    if not crop:
        return img_bytes
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(img_bytes)
        f.flush()
        img = Image.open(f.name)
        w, h = img.size
        left   = int(crop.get("left", 0))
        top    = int(crop.get("top", 0))
        right  = w - int(crop.get("right", 0))
        bottom = h - int(crop.get("bottom", 0))
        cropped = img.crop((left, top, right, bottom))
        out = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        cropped.save(out.name, "PNG")
        return Path(out.name).read_bytes()


# ── browser-based capture (fullpage + element) ────────────────────────────────
async def _browser_capture(
    url: str,
    mode: str,
    selector: str | None,
    viewport: int,
    wait_ms: int,
    scroll: bool,
    crop: dict | None,
) -> dict:
    """
    Returns dict with keys: png_bytes, width, height, final_url, login_screen, blocked
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context(
            viewport={"width": viewport, "height": 900},
            user_agent=USER_AGENT,
            locale="he-IL",
        )
        page = await context.new_page()

        # Detect navigation status
        final_status = 200
        final_url = url
        login_screen = False

        def _on_response(resp):
            nonlocal final_status
            if resp.url == page.url or resp.request.is_navigation_request():
                final_status = resp.status

        page.on("response", _on_response)

        try:
            resp = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=TIMEOUT_MS,
            )
            if resp:
                final_status = resp.status
            final_url = page.url
        except Exception as e:
            await browser.close()
            return {"error": "navigation_failed", "detail": str(e)}

        # CF / anti-bot block detection
        if final_status in CF_BLOCK_STATUSES:
            await browser.close()
            return {"error": "blocked_by_target", "status": final_status}

        # Login-screen detection (simple heuristics)
        page_text = await page.evaluate("document.body?.innerText || ''")
        login_keywords = ["sign in", "log in", "הכנס", "התחבר", "כניסה לחשבון", "login"]
        if any(kw in page_text.lower() for kw in login_keywords):
            # Only flag if URL also changed to a login path
            if any(s in final_url.lower() for s in ["/login", "/signin", "/auth", "account"]):
                login_screen = True

        # Optional wait
        if wait_ms > 0:
            await asyncio.sleep(wait_ms / 1000)

        # Optional scroll-to-bottom (lazy-load trigger)
        if scroll:
            await page.evaluate(
                "window.scrollTo(0, document.body.scrollHeight)"
            )
            await asyncio.sleep(0.5)

        # Screenshot
        if mode == "element" and selector:
            try:
                el = await page.wait_for_selector(selector, timeout=10_000)
                png_bytes = await el.screenshot(type="png")
            except Exception as e:
                await browser.close()
                return {"error": "selector_not_found", "detail": str(e)}
        else:
            # fullpage
            png_bytes = await page.screenshot(type="png", full_page=True)

        await browser.close()

    # Crop
    if crop:
        png_bytes = _crop(png_bytes, crop)

    img = Image.open(__import__("io").BytesIO(png_bytes))
    w, h = img.size

    return {
        "png_bytes": png_bytes,
        "width": w,
        "height": h,
        "final_url": final_url,
        "login_screen": login_screen,
        "blocked": False,
    }


# ── PDF → PNG ─────────────────────────────────────────────────────────────────
async def _pdf_capture(url: str, crop: dict | None) -> dict:
    """Download PDF and convert first page to PNG via pdftoppm."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        if r.status_code in CF_BLOCK_STATUSES:
            return {"error": "blocked_by_target", "status": r.status_code}
        if r.status_code != 200:
            return {"error": "download_failed", "status": r.status_code}
        pdf_bytes = r.content

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "input.pdf")
        out_prefix = os.path.join(tmpdir, "page")
        Path(pdf_path).write_bytes(pdf_bytes)

        result = subprocess.run(
            ["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", "1", pdf_path, out_prefix],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {"error": "pdftoppm_failed", "detail": result.stderr.decode()}

        pages = sorted(Path(tmpdir).glob("page-*.png"))
        if not pages:
            return {"error": "no_pages_produced"}

        png_bytes = pages[0].read_bytes()

    if crop:
        png_bytes = _crop(png_bytes, crop)

    img = Image.open(__import__("io").BytesIO(png_bytes))
    w, h = img.size
    return {"png_bytes": png_bytes, "width": w, "height": h, "final_url": url,
            "login_screen": False, "blocked": False}


# ── XLSX → PNG ────────────────────────────────────────────────────────────────
async def _xlsx_capture(url: str, crop: dict | None) -> dict:
    """Download xlsx and render first sheet to PNG via LibreOffice headless."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        r = await client.get(url, headers={"User-Agent": USER_AGENT})
        if r.status_code in CF_BLOCK_STATUSES:
            return {"error": "blocked_by_target", "status": r.status_code}
        if r.status_code != 200:
            return {"error": "download_failed", "status": r.status_code}
        xlsx_bytes = r.content

    with tempfile.TemporaryDirectory() as tmpdir:
        xlsx_path = os.path.join(tmpdir, "input.xlsx")
        Path(xlsx_path).write_bytes(xlsx_bytes)

        # LibreOffice: convert to PNG (renders first sheet)
        result = subprocess.run(
            [
                "libreoffice", "--headless", "--convert-to", "png",
                "--outdir", tmpdir, xlsx_path,
            ],
            capture_output=True,
            timeout=60,
            env={**os.environ, "HOME": tmpdir},
        )
        if result.returncode != 0:
            return {"error": "libreoffice_failed", "detail": result.stderr.decode()}

        pngs = list(Path(tmpdir).glob("*.png"))
        if not pngs:
            return {"error": "no_png_produced"}

        png_bytes = pngs[0].read_bytes()

    if crop:
        png_bytes = _crop(png_bytes, crop)

    img = Image.open(__import__("io").BytesIO(png_bytes))
    w, h = img.size
    return {"png_bytes": png_bytes, "width": w, "height": h, "final_url": url,
            "login_screen": False, "blocked": False}


# ── public entry point ────────────────────────────────────────────────────────
async def run_capture(
    url: str,
    mode: str,
    selector: str | None = None,
    viewport: int = DEFAULT_VIEWPORT,
    wait_ms: int = 0,
    scroll: bool = False,
    crop: dict | None = None,
) -> dict:
    """Dispatch to the correct capture handler."""
    start = time.time()
    if mode in ("fullpage", "element"):
        result = await _browser_capture(url, mode, selector, viewport, wait_ms, scroll, crop)
    elif mode == "pdf":
        result = await _pdf_capture(url, crop)
    elif mode == "xlsx":
        result = await _xlsx_capture(url, crop)
    else:
        return {"error": "unknown_mode", "detail": f"mode={mode}"}

    if "png_bytes" in result:
        result["md5"] = _md5(result["png_bytes"])
        result["elapsed_ms"] = int((time.time() - start) * 1000)

    return result
