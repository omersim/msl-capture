"""
msl-capture — FastAPI entry point
"""
import time
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from allowed_domains import is_allowed
from auth import require_hmac
from capture import run_capture

VERSION = "1.0.0"
START_TIME = time.time()

app = FastAPI(title="msl-capture", version=VERSION, docs_url=None, redoc_url=None)


# ── health ─────────────────────────────────────────────────────────────────────
@app.get("/v1/health")
async def health():
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": int(time.time() - START_TIME),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── capture request schema ────────────────────────────────────────────────────
class CropParams(BaseModel):
    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


class CaptureRequest(BaseModel):
    url: str
    mode: str = Field("fullpage", pattern="^(fullpage|element|pdf|xlsx)$")
    selector: str | None = None
    viewport: int = Field(1440, ge=320, le=3840)
    wait_ms: int = Field(0, ge=0, le=10000)
    scroll: bool = False
    crop: CropParams | None = None


# ── /v1/capture ───────────────────────────────────────────────────────────────
@app.post("/v1/capture", dependencies=[Depends(require_hmac)])
async def capture(req: CaptureRequest):
    # Domain allowlist check
    if not is_allowed(req.url):
        return JSONResponse(
            status_code=403,
            content={"error": "domain_not_allowed", "url": req.url},
        )

    # Validate element mode has selector
    if req.mode == "element" and not req.selector:
        return JSONResponse(
            status_code=422,
            content={"error": "selector_required_for_element_mode"},
        )

    crop_dict = req.crop.model_dump() if req.crop else None

    result = await run_capture(
        url=req.url,
        mode=req.mode,
        selector=req.selector,
        viewport=req.viewport,
        wait_ms=req.wait_ms,
        scroll=req.scroll,
        crop=crop_dict,
    )

    # Propagate capture errors as JSON
    if "error" in result:
        status = 502 if result["error"] == "blocked_by_target" else 500
        return JSONResponse(status_code=status, content=result)

    png_bytes = result.pop("png_bytes")
    headers = {
        "X-MD5":        result["md5"],
        "X-Width":      str(result["width"]),
        "X-Height":     str(result["height"]),
        "X-Mode":       req.mode,
        "X-Final-URL":  result["final_url"],
        "X-Login-Screen": "true" if result.get("login_screen") else "false",
        "X-Elapsed-MS": str(result.get("elapsed_ms", 0)),
    }
    return Response(content=png_bytes, media_type="image/png", headers=headers)
