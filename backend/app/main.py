"""Portable FastAPI backend for Chhabinathpur Durga Pooja Samiti."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from pymongo import ReturnDocument
from io import BytesIO
from pathlib import Path
from typing import Any

import jwt
import qrcode
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field

ROOT = Path(__file__).resolve().parents[1]
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY = os.getenv("SECRET_KEY", "development-only-change-me-before-deploying")
MONGO_URL = os.getenv("MONGO_URL", "")
MONGO_DB = os.getenv("MONGO_DB", "chhabinathpur_durga_pooja")
ALLOW_MEMORY = os.getenv("ALLOW_MEMORY_STORE", "true").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "5242880"))
ORIGINS = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
PWD = CryptContext(schemes=["argon2"], deprecated="auto")
client: AsyncIOMotorClient | None = None
db = None
memory: dict[str, list[dict[str, Any]]] = {name: [] for name in ["admins", "announcements", "schedule", "programs", "gallery", "committee", "donations", "expenses", "visitors", "counters"]}
memory_settings: dict[str, Any] = {}

app = FastAPI(title="Chhabinathpur Durga Pooja Samiti API", version="1.0.0", docs_url="/docs" if os.getenv("ENVIRONMENT") != "production" else None)
app.add_middleware(CORSMiddleware, allow_origins=ORIGINS, allow_credentials=False, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

class LoginIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)
class DonationIn(BaseModel):
    donor_name: str = Field(min_length=2, max_length=100)
    mobile: str = Field(min_length=10, max_length=20)
    email: EmailStr | None = None
    amount: float = Field(gt=0, le=1_000_000)
    payment_method: str = Field(default="UPI", max_length=30)
    transaction_reference: str = Field(default="", max_length=80)
class ContentIn(BaseModel):
    data: dict[str, Any]

DEFAULT_SETTINGS = {
    "organization_name": "Chhabinathpur Durga Pooja Samiti", "upi_id": "8172938399@ybl",
    "address": "Chhabinathpur, Jigna, Mirzapur, Uttar Pradesh - 231313",
    "puja_venue": "Near Pawan Ki Dukan, Chhabinathpur", "puja_start_date": "2026-10-11", "visarjan_date": "2026-10-20",
    "morning_aarti": "7:30 AM", "evening_aarti": "7:00 PM", "footer_text": "Jai Maa Durga",
    "maps_url": "", "contact_number": "", "whatsapp_number": "", "email": "", "social_links": {},
}
INITIAL_COMMITTEE = [
    {"name": "Pramod Tiwari", "position": "Adhyaksha", "sort_order": 1},
    {"name": "Ankit Tiwari", "position": "Koshadhyaksha", "sort_order": 2},
    {"name": "Atul Tiwari", "position": "Committee Member", "sort_order": 3},
    {"name": "Rohit Tiwari", "position": "Committee Member", "sort_order": 4},
    {"name": "Vinod Tiwari", "position": "Committee Member", "sort_order": 5},
]

def now() -> str:
    return datetime.now(timezone.utc).isoformat()
def uid() -> str:
    return str(uuid.uuid4())
def clean(value: Any, max_length: int = 500) -> str:
    """Normalize text inputs; React escapes output and this removes control characters."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).strip()[:max_length]
def public(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None: return None
    copy = {k: v for k, v in doc.items() if k != "_id" and k != "password_hash"}
    return copy

async def list_docs(collection: str, query: dict[str, Any] | None = None, sort: tuple[str, int] = ("created_at", -1)) -> list[dict[str, Any]]:
    query = query or {}
    if db is not None:
        return [public(x) async for x in db[collection].find(query).sort(*sort)]
    rows = [x.copy() for x in memory[collection] if all(x.get(k) == v for k, v in query.items())]
    return sorted(rows, key=lambda x: x.get(sort[0], ""), reverse=sort[1] < 0)
async def one_doc(collection: str, query: dict[str, Any]) -> dict[str, Any] | None:
    if db is not None: return public(await db[collection].find_one(query))
    return next((x.copy() for x in memory[collection] if all(x.get(k) == v for k, v in query.items())), None)
async def add_doc(collection: str, document: dict[str, Any]) -> dict[str, Any]:
    document = {**document, "id": document.get("id", uid()), "created_at": document.get("created_at", now())}
    if db is not None: await db[collection].insert_one(document)
    else: memory[collection].append(document.copy())
    return public(document)
async def change_doc(collection: str, doc_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    changes["updated_at"] = now()
    if db is not None:
        result = await db[collection].find_one_and_update({"id": doc_id}, {"$set": changes}, return_document=ReturnDocument.AFTER)
        if not result: raise HTTPException(404, "Item not found")
        return public(result)
    for row in memory[collection]:
        if row["id"] == doc_id:
            row.update(changes); return row.copy()
    raise HTTPException(404, "Item not found")
async def remove_doc(collection: str, doc_id: str) -> None:
    if db is not None:
        result = await db[collection].delete_one({"id": doc_id})
        if not result.deleted_count: raise HTTPException(404, "Item not found")
        return
    before = len(memory[collection]); memory[collection] = [x for x in memory[collection] if x["id"] != doc_id]
    if before == len(memory[collection]): raise HTTPException(404, "Item not found")
async def count_docs(collection: str, query: dict[str, Any] | None = None) -> int:
    query = query or {}
    if db is not None: return await db[collection].count_documents(query)
    return len([x for x in memory[collection] if all(x.get(k) == v for k, v in query.items())])
async def settings() -> dict[str, Any]:
    if db is not None:
        found = await db.site_settings.find_one({"key": "site"})
        return {**DEFAULT_SETTINGS, **(found or {})}
    return {**DEFAULT_SETTINGS, **memory_settings}
async def save_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = set(DEFAULT_SETTINGS)
    clean_values = {k: (clean(v, 400) if isinstance(v, str) else v) for k, v in values.items() if k in allowed}
    if db is not None:
        await db.site_settings.update_one({"key": "site"}, {"$set": {**clean_values, "key": "site", "updated_at": now()}}, upsert=True)
    else: memory_settings.update(clean_values)
    return await settings()

@app.on_event("startup")
async def startup() -> None:
    global client, db
    if MONGO_URL:
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000)
        try:
            await client.admin.command("ping"); db = client[MONGO_DB]
        except Exception as exc:
            client = None
            if not ALLOW_MEMORY: raise RuntimeError("MongoDB connection failed and memory storage is disabled") from exc
    if db is None and not ALLOW_MEMORY: raise RuntimeError("MONGO_URL is required when ALLOW_MEMORY_STORE=false")
    existing = await one_doc("admins", {"username": os.getenv("ADMIN_USERNAME", "admin")})
    if not existing:
        await add_doc("admins", {"username": os.getenv("ADMIN_USERNAME", "admin"), "password_hash": PWD.hash(os.getenv("ADMIN_PASSWORD", "change-this-before-deployment")), "active": True})
    if await count_docs("committee") == 0:
        for member in INITIAL_COMMITTEE: await add_doc("committee", {**member, "description": "", "photo_url": "", "active": True})
    if db is not None:
        if not await db.site_settings.find_one({"key": "site"}): await save_settings(DEFAULT_SETTINGS)
    elif not memory_settings:
        await save_settings(DEFAULT_SETTINGS)

@app.on_event("shutdown")
async def shutdown() -> None:
    if client is not None: client.close()
def make_token(username: str) -> str:
    return jwt.encode({"sub": username, "exp": datetime.now(timezone.utc) + timedelta(hours=8)}, SECRET_KEY, algorithm="HS256")
async def admin_user(request: Request) -> dict[str, Any]:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "): raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin authentication is required")
    try: payload = jwt.decode(header[7:], SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError: raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session is invalid or has expired")
    user = await one_doc("admins", {"username": payload.get("sub", "")})
    if not user or not user.get("active", True): raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin account is unavailable")
    return user

def clean_content(collection: str, values: dict[str, Any]) -> dict[str, Any]:
    permitted = {
        "announcements": {"title", "description", "priority", "date", "time", "image", "published"},
        "schedule": {"date", "day", "title", "description", "ritual_program", "start_time", "end_time", "location", "published"},
        "programs": {"title", "description", "date", "start_time", "end_time", "venue", "poster_url", "published"},
        "committee": {"name", "position", "description", "photo_url", "sort_order", "active"},
        "expenses": {"title", "category", "amount", "date", "notes"},
    }[collection]
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key not in permitted: continue
        if key == "amount":
            try: result[key] = round(float(value), 2)
            except (TypeError, ValueError): raise HTTPException(422, "Amount must be a valid number")
            if not 0 < result[key] <= 1_000_000: raise HTTPException(422, "Amount must be between 1 and 1,000,000")
        elif key in {"published", "active"}: result[key] = bool(value)
        elif key == "sort_order":
            try: result[key] = int(value)
            except (TypeError, ValueError): result[key] = 999
        else: result[key] = clean(value, 2000 if key in {"description", "notes"} else 200)
    if collection == "announcements" and result.get("priority") not in {"Normal", "Important", "Urgent", ""}:
        raise HTTPException(422, "Announcement priority must be Normal, Important, or Urgent")
    return result

@app.get("/health")
async def health() -> dict[str, Any]: return {"status": "ok", "storage": "mongodb" if db is not None else "memory"}
@app.post("/api/admin/login")
async def login(body: LoginIn) -> dict[str, str]:
    user = await one_doc("admins", {"username": clean(body.username, 64)})
    if not user or not user.get("active", True) or not PWD.verify(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    return {"access_token": make_token(user["username"]), "token_type": "bearer"}
@app.get("/api/site-settings")
async def get_settings() -> dict[str, Any]:
    data = await settings(); return public(data) or DEFAULT_SETTINGS
@app.get("/api/announcements")
async def announcements() -> list[dict[str, Any]]:
    return await list_docs("announcements", {"published": True})
@app.get("/api/schedule")
async def schedule() -> list[dict[str, Any]]:
    return await list_docs("schedule", {"published": True}, ("date", 1))
@app.get("/api/programs")
async def programs() -> list[dict[str, Any]]:
    return await list_docs("programs", {"published": True}, ("date", 1))
@app.get("/api/committee")
async def committee() -> list[dict[str, Any]]:
    return await list_docs("committee", {"active": True}, ("sort_order", 1))
@app.get("/api/gallery")
async def gallery(year: str | None = None, category: str | None = None, limit: int = Query(48, ge=1, le=100)) -> list[dict[str, Any]]:
    query: dict[str, Any] = {}
    if year: query["year"] = clean(year, 20)
    if category: query["category"] = clean(category, 80)
    return (await list_docs("gallery", query))[:limit]
async def financial_summary() -> dict[str, float]:
    donations = await list_docs("donations", {"status": "Verified"})
    expenses = await list_docs("expenses")
    donated = round(sum(float(x.get("amount", 0)) for x in donations), 2)
    spent = round(sum(float(x.get("amount", 0)) for x in expenses), 2)
    return {"total_donations": donated, "total_expenses": spent, "balance": round(donated - spent, 2)}
@app.get("/api/financial-summary")
async def financial() -> dict[str, float]: return await financial_summary()
@app.get("/api/qr")
async def qr(data: str = Query(min_length=1, max_length=1500), download: bool = False) -> Response:
    image = qrcode.make(data); buffer = BytesIO(); image.save(buffer, format="PNG", optimize=True)
    headers = {"Content-Disposition": "attachment; filename=cdps-qr.png"} if download else {}
    return Response(buffer.getvalue(), media_type="image/png", headers=headers)
@app.post("/api/donations", status_code=status.HTTP_201_CREATED)
async def create_donation(body: DonationIn) -> dict[str, Any]:
    mobile = re.sub(r"\D", "", body.mobile)
    if len(mobile) != 10: raise HTTPException(422, "Please enter a valid 10-digit mobile number")
    utr = clean(body.transaction_reference, 80)
    if utr and not re.fullmatch(r"[A-Za-z0-9._/-]{4,80}", utr): raise HTTPException(422, "Invalid transaction reference")
    record = await add_doc("donations", {"donor_name": clean(body.donor_name, 100), "mobile": mobile, "email": str(body.email or ""), "amount": round(body.amount, 2), "payment_method": clean(body.payment_method, 30), "upi_id": (await settings())["upi_id"], "transaction_reference": utr, "status": "Submitted" if utr else "Pending", "receipt_number": "", "verified_at": ""})
    return {"id": record["id"], "status": record["status"], "message": "Donation submitted successfully. Your payment will be verified by the committee."}
@app.post("/api/visitors")
async def record_visitor(request: Request, payload: dict[str, str]) -> dict[str, int]:
    raw_key = clean(payload.get("visitor_key", ""), 120)
    if not raw_key: raise HTTPException(422, "Visitor key is required")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fingerprint = hashlib.sha256(f"{raw_key}:{day}:{SECRET_KEY}".encode()).hexdigest()
    if not await one_doc("visitors", {"fingerprint": fingerprint, "day": day}):
        await add_doc("visitors", {"fingerprint": fingerprint, "day": day})
    return {"total": await count_docs("visitors"), "today": await count_docs("visitors", {"day": day})}
ADMIN_COLLECTIONS = {"announcements", "schedule", "programs", "committee", "expenses"}
@app.get("/api/admin/dashboard")
async def dashboard(_: dict = Depends(admin_user)) -> dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {"financial": await financial_summary(), "visitors": {"total": await count_docs("visitors"), "today": await count_docs("visitors", {"day": today}), "monthly": await count_docs("visitors")}, "counts": {"gallery": await count_docs("gallery"), "announcements": await count_docs("announcements"), "verified_donations": await count_docs("donations", {"status": "Verified"})}}
@app.get("/api/admin/{collection}")
async def admin_list(collection: str, _: dict = Depends(admin_user)) -> list[dict[str, Any]]:
    if collection not in ADMIN_COLLECTIONS | {"gallery", "donations"}: raise HTTPException(404, "Unknown collection")
    sort = ("sort_order", 1) if collection == "committee" else ("created_at", -1)
    return await list_docs(collection, sort=sort)
@app.post("/api/admin/{collection}", status_code=status.HTTP_201_CREATED)
async def admin_create(collection: str, values: dict[str, Any], _: dict = Depends(admin_user)) -> dict[str, Any]:
    if collection not in ADMIN_COLLECTIONS: raise HTTPException(404, "Unknown collection")
    item = clean_content(collection, values)
    required = {"announcements": ["title"], "schedule": ["title", "date"], "programs": ["title"], "committee": ["name", "position"], "expenses": ["title", "amount", "date"]}[collection]
    if any(not item.get(x) for x in required): raise HTTPException(422, "Required fields are missing")
    if collection in {"announcements", "schedule", "programs"}: item["published"] = item.get("published", True)
    if collection == "committee": item["active"] = item.get("active", True)
    if collection == "announcements": item["priority"] = item.get("priority") or "Normal"
    return await add_doc(collection, item)
@app.put("/api/admin/{collection}/{doc_id}")
async def admin_update(collection: str, doc_id: str, values: dict[str, Any], _: dict = Depends(admin_user)) -> dict[str, Any]:
    if collection not in ADMIN_COLLECTIONS: raise HTTPException(404, "Unknown collection")
    return await change_doc(collection, doc_id, clean_content(collection, values))
@app.delete("/api/admin/{collection}/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete(collection: str, doc_id: str, _: dict = Depends(admin_user)) -> None:
    if collection not in ADMIN_COLLECTIONS | {"gallery"}: raise HTTPException(404, "Unknown collection")
    image = await one_doc(collection, {"id": doc_id}) if collection == "gallery" else None
    await remove_doc(collection, doc_id)
    if image and image.get("stored_name"):
        try: (UPLOAD_DIR / image["stored_name"]).unlink(missing_ok=True)
        except OSError: pass

ALLOWED_MIMES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
@app.post("/api/admin/gallery/upload", status_code=status.HTTP_201_CREATED)
async def upload_gallery(file: UploadFile = File(...), caption: str = "", year: str = "2026", category: str = "Maa Durga", _: dict = Depends(admin_user)) -> dict[str, Any]:
    if file.content_type not in ALLOWED_MIMES: raise HTTPException(415, "Only JPEG, PNG and WebP images are allowed")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES: raise HTTPException(413, "Image is larger than the allowed 5 MB limit")
    if not contents: raise HTTPException(422, "Uploaded image is empty")
    # Verify magic bytes so extension and browser-provided MIME type cannot bypass validation.
    magic = {b"\xff\xd8\xff": ".jpg", b"\x89PNG\r\n\x1a\n": ".png", b"RIFF": ".webp"}
    suffix = next((ext for signature, ext in magic.items() if contents.startswith(signature)), None)
    if suffix is None or suffix != ALLOWED_MIMES[file.content_type]: raise HTTPException(415, "Image content does not match its declared type")
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    (UPLOAD_DIR / stored_name).write_bytes(contents)
    return await add_doc("gallery", {"image_url": f"/uploads/{stored_name}", "stored_name": stored_name, "caption": clean(caption, 250), "year": clean(year, 20), "category": clean(category, 80)})
async def next_receipt_number() -> str:
    if db is not None:
        from pymongo import ReturnDocument
        counter = await db.counters.find_one_and_update({"key": "receipt_2026"}, {"$inc": {"value": 1}, "$setOnInsert": {"key": "receipt_2026"}}, upsert=True, return_document=ReturnDocument.AFTER)
        value = counter["value"]
    else:
        counter = await one_doc("counters", {"key": "receipt_2026"})
        if counter: value = int(counter.get("value", 0)) + 1; await change_doc("counters", counter["id"], {"value": value})
        else: value = 1; await add_doc("counters", {"key": "receipt_2026", "value": value})
    return f"CDPS-2026-{value:04d}"
@app.patch("/api/admin/donations/{doc_id}/verify")
async def verify_donation(doc_id: str, _: dict = Depends(admin_user)) -> dict[str, Any]:
    donation = await one_doc("donations", {"id": doc_id})
    if not donation: raise HTTPException(404, "Donation not found")
    receipt = donation.get("receipt_number") or await next_receipt_number()
    return await change_doc("donations", doc_id, {"status": "Verified", "receipt_number": receipt, "verified_at": now()})
@app.patch("/api/admin/donations/{doc_id}/reject")
async def reject_donation(doc_id: str, _: dict = Depends(admin_user)) -> dict[str, Any]:
    return await change_doc("donations", doc_id, {"status": "Rejected", "verified_at": ""})
@app.put("/api/admin/site-settings")
async def update_settings(values: dict[str, Any], _: dict = Depends(admin_user)) -> dict[str, Any]: return await save_settings(values)
@app.get("/api/receipts/{doc_id}", response_class=HTMLResponse)
async def receipt(doc_id: str, _: dict = Depends(admin_user)) -> HTMLResponse:
    donation = await one_doc("donations", {"id": doc_id})
    if not donation or donation.get("status") != "Verified": raise HTTPException(404, "Verified donation receipt not found")
    amount = f"₹{float(donation['amount']):,.2f}"
    verified_date = donation.get("verified_at", "")[:10] or datetime.now().strftime("%Y-%m-%d")
    safe_receipt = escape(str(donation["receipt_number"]))
    safe_donor = escape(str(donation["donor_name"]))
    safe_method = escape(str(donation["payment_method"]))
    safe_reference = escape(str(donation.get("transaction_reference") or "Not provided"))
    html = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{safe_receipt} | Donation Receipt</title><style>body{{font-family:Arial,sans-serif;background:#f4efe5;padding:35px;color:#241618}}.receipt{{max-width:720px;margin:auto;background:#fff;padding:55px;border-top:10px solid #741827;box-shadow:0 5px 20px #0002}}h1{{color:#741827;margin-bottom:4px}}h2{{color:#a67b2f;font-size:17px;letter-spacing:1px}}.line{{border-top:1px solid #dbcaa6;margin:26px 0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}.label{{font-size:12px;text-transform:uppercase;color:#756969;letter-spacing:1px}}.value{{font-size:17px;font-weight:bold;margin-top:4px}}footer{{margin-top:42px;color:#756969;font-size:13px}}button{{background:#741827;color:white;border:0;padding:11px 16px;cursor:pointer}}@media print{{body{{background:white;padding:0}}.receipt{{box-shadow:none}}button{{display:none}}}}</style></head><body><main class='receipt'><h1>CHHABINATHPUR DURGA POOJA SAMITI</h1><h2>DONATION RECEIPT</h2><div class='line'></div><div class='grid'><div><div class='label'>Receipt No.</div><div class='value'>{safe_receipt}</div></div><div><div class='label'>Status</div><div class='value'>Verified</div></div><div><div class='label'>Donor</div><div class='value'>{safe_donor}</div></div><div><div class='label'>Amount</div><div class='value'>{amount}</div></div><div><div class='label'>Payment Method</div><div class='value'>{safe_method}</div></div><div><div class='label'>Transaction Reference</div><div class='value'>{safe_reference}</div></div><div><div class='label'>Verification Date</div><div class='value'>{verified_date}</div></div></div><footer><p>Thank you for your contribution.</p><p>Jai Maa Durga</p></footer><button onclick='window.print()'>Print Receipt</button></main></body></html>"""
    return HTMLResponse(html, headers={"Content-Disposition": f"inline; filename={safe_receipt}.html"})




