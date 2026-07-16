"""
LGU Gate Verify - checks a scanned/photographed student ID card and
tells the guard whether the student is currently allowed on campus.

Rejects:
  - Graduated students (session end year has passed)
  - Frozen-semester / dropped-out students (manual override list)

Everything else is allowed.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.ocr import read_card, CardReadError
from app import status_list

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gate_verify")

app = FastAPI(
    title="LGU Gate Verify",
    description="Verifies student ID cards at the gate against enrollment status.",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    status_list.init_db()


app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", tags=["frontend"])
def serve_frontend():
    return FileResponse("app/static/index.html")


@app.get("/admin", tags=["frontend"])
def serve_admin():
    return FileResponse("app/static/admin.html")


# ---------------------------------------------------------------------------
# Core verification logic (shared by photo-scan and manual-entry paths)
# ---------------------------------------------------------------------------

class VerifyResult(BaseModel):
    allowed: bool
    roll_number: str
    reason: str
    session_end_year: Optional[int] = None
    detail: Optional[str] = None


def evaluate_status(roll_number: str, session_end_year: Optional[int]) -> VerifyResult:
    current_year = datetime.now().year

    # 1. Session check first (only possible if we know the session end year)
    if session_end_year is not None and current_year > session_end_year:
        return VerifyResult(
            allowed=False,
            roll_number=roll_number,
            reason="graduated",
            session_end_year=session_end_year,
            detail=f"Session ended {session_end_year}. Student has passed out.",
        )

    # 2. Frozen / dropped-out override list
    override = status_list.check_roll(roll_number)
    if override:
        return VerifyResult(
            allowed=False,
            roll_number=roll_number,
            reason=override["status"],
            session_end_year=session_end_year,
            detail=override["note"] or f"Marked as {override['status']} by admin.",
        )

    # 3. Clear
    return VerifyResult(
        allowed=True,
        roll_number=roll_number,
        reason="active",
        session_end_year=session_end_year,
        detail="Currently enrolled.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/verify/scan", response_model=VerifyResult, tags=["verify"])
async def verify_by_scan(file: UploadFile = File(...)):
    """Guard uploads/captures a photo of the card. OCR reads Roll No + Session."""
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")

    try:
        card_data = read_card(image_bytes)
    except CardReadError as e:
        raise HTTPException(status_code=422, detail=str(e))

    logger.info(f"Scanned card -> roll={card_data['roll_number']} session_end={card_data['session_end_year']}")

    result = evaluate_status(card_data["roll_number"], card_data["session_end_year"])
    return result


class ManualVerifyRequest(BaseModel):
    roll_number: str
    session_end_year: Optional[int] = None  # optional fallback if OCR fails entirely


@app.post("/verify/manual", response_model=VerifyResult, tags=["verify"])
def verify_manual(request: ManualVerifyRequest):
    """Fallback for when the camera/OCR path fails - guard types the roll number in."""
    return evaluate_status(request.roll_number, request.session_end_year)


# ---------------------------------------------------------------------------
# Admin: manage the frozen / dropped-out list
# ---------------------------------------------------------------------------

@app.get("/admin/list", tags=["admin"])
def admin_list():
    return status_list.list_all()


@app.post("/admin/list", tags=["admin"])
def admin_add(roll_number: str = Form(...), status: str = Form(...), note: str = Form("")):
    if status not in ("frozen", "dropped"):
        raise HTTPException(status_code=400, detail="status must be 'frozen' or 'dropped'")
    status_list.upsert_roll(roll_number, status, note)
    return {"ok": True}


@app.delete("/admin/list/{roll_number}", tags=["admin"])
def admin_delete(roll_number: str):
    status_list.delete_roll(roll_number)
    return {"ok": True}


@app.post("/admin/list/import", tags=["admin"])
async def admin_import_csv(file: UploadFile = File(...)):
    """Bulk upload a CSV with columns: roll_number, status, note"""
    content = await file.read()
    try:
        count, errors = status_list.import_csv(content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"imported": count, "errors": errors}


@app.get("/health", tags=["ops"])
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
