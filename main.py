import os
import json
import uuid
import aiofiles
from datetime import datetime, date, timezone, timedelta
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Base, User, Product, Transaction, ShopSettings, seed, verify_password, hash_password

Base.metadata.create_all(bind=engine)
seed()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

CATEGORIES = ["Hot Coffee", "Hot Non-Coffee", "Iced Espresso", "Iced Non-Coffee", "Matcha", "Pastries"]
SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours
PH_TZ = timezone(timedelta(hours=8))


def now_ph():
    return datetime.now(PH_TZ).replace(tzinfo=None)


def get_session_user(request: Request, db: Session):
    uid = request.cookies.get("user_id")
    if not uid:
        return None
    try:
        return db.query(User).filter(User.id == int(uid)).first()
    except Exception:
        return None


def get_settings(db: Session) -> ShopSettings:
    s = db.query(ShopSettings).filter(ShopSettings.id == 1).first()
    if not s:
        s = ShopSettings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


# ── auth ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials."})
    resp = RedirectResponse("/pos" if user.role == "cashier" else "/admin", status_code=302)
    resp.set_cookie("user_id",   str(user.id),  max_age=SESSION_MAX_AGE, httponly=True)
    resp.set_cookie("user_role", user.role,      max_age=SESSION_MAX_AGE, httponly=True)
    resp.set_cookie("user_name", user.username,  max_age=SESSION_MAX_AGE, httponly=True)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("user_id")
    resp.delete_cookie("user_role")
    resp.delete_cookie("user_name")
    return resp


# ── cashier POS ───────────────────────────────────────────────────────────────

@app.get("/pos", response_class=HTMLResponse)
def pos_terminal(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return RedirectResponse("/login")
    products = db.query(Product).filter(Product.is_available == True).all()
    grouped = {cat: [p for p in products if p.category == cat] for cat in CATEGORIES}
    cat_counts = {cat: len(grouped[cat]) for cat in CATEGORIES}
    settings = get_settings(db)
    return templates.TemplateResponse("pos.html", {
        "request": request,
        "grouped": grouped,
        "categories": CATEGORIES,
        "cat_counts": cat_counts,
        "user": user,
        "gcash_number": settings.gcash_number,
        "gcash_qr": f"/static/{settings.gcash_qr}" if settings.gcash_qr else None,
    })


@app.post("/checkout")
async def checkout(request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    data = await request.json()
    items = data.get("items", [])
    payment = data.get("payment_method", "Cash")
    tendered = float(data.get("amount_tendered", 0))
    if not items:
        raise HTTPException(status_code=400, detail="No items in order")
    if payment not in ("Cash", "GCash"):
        raise HTTPException(status_code=400, detail="Invalid payment method")
    server_total = 0.0
    validated_items = []
    for item in items:
        qty = int(item.get("qty", 1))
        if qty < 1 or qty > 99:
            raise HTTPException(status_code=400, detail=f"Invalid qty for {item.get('name')}")
        product = db.query(Product).filter(Product.id == int(item["id"]), Product.is_available == True).first()
        if not product:
            raise HTTPException(status_code=400, detail=f"Product {item.get('name')} unavailable")
        server_total += product.price * qty
        validated_items.append({"id": product.id, "name": product.name, "price": product.price, "qty": qty})
    server_total = round(server_total, 2)
    if payment == "Cash" and tendered < server_total:
        raise HTTPException(status_code=400, detail="Tendered amount insufficient")
    change = round(tendered - server_total, 2) if payment == "Cash" else 0
    order_number = f"CHN-{now_ph().strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"
    tx = Transaction(
        order_number=order_number,
        timestamp=now_ph(),
        items_json=json.dumps(validated_items),
        total_amount=server_total,
        payment_method=payment,
        amount_tendered=tendered if payment == "Cash" else None,
        change_given=change if payment == "Cash" else None,
        cashier_id=user.id,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return JSONResponse({"success": True, "order_number": order_number, "change": change, "tx_id": tx.id})


# ── receipt ───────────────────────────────────────────────────────────────────

@app.get("/receipt/{tx_id}", response_class=HTMLResponse)
def receipt(tx_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user:
        return RedirectResponse("/login")
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404)
    return templates.TemplateResponse("receipt.html", {
        "request": request,
        "tx": tx,
        "items": json.loads(tx.items_json),
    })


# ── admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, filter_date: str = None, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        return RedirectResponse("/login")
    query = db.query(Transaction).filter(Transaction.is_voided == False)
    if filter_date:
        try:
            d = date.fromisoformat(filter_date)
            query = query.filter(
                Transaction.timestamp >= datetime(d.year, d.month, d.day, 0, 0, 0),
                Transaction.timestamp <= datetime(d.year, d.month, d.day, 23, 59, 59),
            )
        except ValueError:
            pass
    transactions = query.order_by(Transaction.timestamp.desc()).limit(100).all()
    total_sales = sum(t.total_amount for t in transactions)
    for tx in transactions:
        tx.items = json.loads(tx.items_json)
    products = db.query(Product).order_by(Product.category, Product.name).all()
    settings = get_settings(db)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "user": user,
        "transactions": transactions,
        "total_sales": total_sales,
        "products": products,
        "categories": CATEGORIES,
        "filter_date": filter_date or "",
        "settings": settings,
    })


@app.post("/admin/void/{tx_id}")
async def void_transaction(tx_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    data = await request.json()
    tx = db.query(Transaction).filter(Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404)
    tx.is_voided = True
    tx.void_reason = data.get("reason", "No reason given")
    db.commit()
    return JSONResponse({"success": True})


@app.post("/admin/product/toggle/{product_id}")
def toggle_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404)
    p.is_available = not p.is_available
    db.commit()
    return JSONResponse({"success": True, "is_available": p.is_available})


@app.post("/admin/product/delete/{product_id}")
def delete_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404)
    db.delete(p)
    db.commit()
    return JSONResponse({"success": True})


@app.post("/admin/product/add")
async def add_product(request: Request,
                      name: str = Form(...), category: str = Form(...),
                      price: float = Form(...), dot_color: str = Form("brown"),
                      badge: str = Form(None), db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    form = await request.form()
    image_file = form.get("image")
    image_filename = None
    if image_file and hasattr(image_file, "filename") and image_file.filename:
        ext = os.path.splitext(image_file.filename)[1].lower()
        safe_name = name.lower().replace(" ", "-").replace("/", "-") + ext
        async with aiofiles.open(f"static/products/{safe_name}", "wb") as f:
            await f.write(await image_file.read())
        image_filename = safe_name
    db.add(Product(name=name, category=category, price=price,
                   dot_color=dot_color, badge=badge or None, image=image_filename))
    db.commit()
    return RedirectResponse("/admin?tab=menu", status_code=302)


@app.post("/admin/product/edit/{product_id}")
async def edit_product(product_id: int, request: Request,
                       name: str = Form(...), category: str = Form(...),
                       price: float = Form(...), dot_color: str = Form("brown"),
                       badge: str = Form(None), db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(status_code=404)
    form = await request.form()
    image_file = form.get("image")
    if image_file and hasattr(image_file, "filename") and image_file.filename:
        ext = os.path.splitext(image_file.filename)[1].lower()
        safe_name = name.lower().replace(" ", "-").replace("/", "-") + ext
        async with aiofiles.open(f"static/products/{safe_name}", "wb") as f:
            await f.write(await image_file.read())
        p.image = safe_name
    p.name, p.category, p.price = name, category, price
    p.dot_color, p.badge = dot_color, badge or None
    db.commit()
    return RedirectResponse("/admin?tab=menu", status_code=302)


@app.post("/admin/settings")
async def save_settings(request: Request, gcash_number: str = Form(""), db: Session = Depends(get_db)):
    user = get_session_user(request, db)
    if not user or user.role != "admin":
        raise HTTPException(status_code=403)
    s = get_settings(db)
    s.gcash_number = gcash_number.strip() or None
    form = await request.form()
    qr_file = form.get("gcash_qr")
    if qr_file and hasattr(qr_file, "filename") and qr_file.filename:
        ext = os.path.splitext(qr_file.filename)[1].lower()
        filename = f"gcash-qr{ext}"
        async with aiofiles.open(f"static/{filename}", "wb") as f:
            await f.write(await qr_file.read())
        s.gcash_qr = filename
    db.commit()
    return RedirectResponse("/admin?tab=settings", status_code=302)


@app.get("/api/settings")
def api_settings(db: Session = Depends(get_db)):
    s = get_settings(db)
    return JSONResponse({"gcash_number": s.gcash_number, "gcash_qr": f"/static/{s.gcash_qr}" if s.gcash_qr else None})


@app.get("/api/daily-total")
def daily_total(db: Session = Depends(get_db)):
    today = now_ph().date()
    txs = db.query(Transaction).filter(
        Transaction.is_voided == False,
        Transaction.timestamp >= datetime(today.year, today.month, today.day, 0, 0, 0),
        Transaction.timestamp <= datetime(today.year, today.month, today.day, 23, 59, 59),
    ).all()
    total = sum(t.total_amount for t in txs)
    return JSONResponse({"total": round(total, 2), "count": len(txs)})
