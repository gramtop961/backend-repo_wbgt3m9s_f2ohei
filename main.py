import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Product, Cart, CartItem, Order

app = FastAPI(title="Smart Self-Checkout API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str
    role: str = "customer"


class ScanRequest(BaseModel):
    barcode: str


class ReceiptRequest(BaseModel):
    order_id: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


# Utility

def oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


@app.get("/")
async def root():
    return {"message": "Smart Self-Checkout Backend Running"}


@app.get("/test")
async def test_database():
    info = {
        "backend": "running",
        "database": "unavailable",
        "collections": [],
    }
    try:
        if db is not None:
            info["database"] = "connected"
            info["collections"] = db.list_collection_names()
    except Exception as e:
        info["database"] = f"error: {str(e)[:80]}"
    return info


# Auth
@app.post("/auth/register")
async def register(payload: RegisterRequest):
    exists = db["user"].find_one({"email": payload.email})
    if exists:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password=payload.password,
        role=payload.role,
    )
    user_id = create_document("user", user)
    return {"user_id": user_id}


@app.post("/auth/login")
async def login(payload: LoginRequest):
    user = db["user"].find_one({"email": payload.email, "password": payload.password})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"user_id": str(user["_id"]), "role": user.get("role", "customer"), "name": user.get("name")}


# Products
@app.get("/products")
async def list_products():
    docs = get_documents("product")
    for d in docs:
        d["_id"] = str(d["_id"])  # make JSON serializable
    return docs


@app.post("/products")
async def add_product(product: Product):
    inserted_id = create_document("product", product)
    return {"product_id": inserted_id}


# Scanner (OpenCV placeholder): We accept barcode text sent by client or IoT device
@app.post("/scan")
async def scan_item(req: ScanRequest):
    # Find by barcode; if not available, try by title code
    product = db["product"].find_one({"barcode": req.barcode})
    if not product:
        product = db["product"].find_one({"title": req.barcode})
    if not product:
        raise HTTPException(status_code=404, detail="Item not found")

    product_id = str(product["_id"])
    return {
        "product_id": product_id,
        "title": product.get("title"),
        "price": product.get("price", 0.0),
        "barcode": product.get("barcode"),
    }


# Cart
@app.post("/cart/{user_id}/add")
async def cart_add(user_id: str, item: CartItem):
    cart = db["cart"].find_one({"user_id": user_id, "status": "active"})
    if not cart:
        cart = {
            "user_id": user_id,
            "items": [],
            "status": "active",
            "subtotal": 0.0,
        }
        cart["_id"] = ObjectId(create_document("cart", cart))
    # Merge quantity if same product
    merged = False
    for ci in cart["items"]:
        if ci["product_id"] == item.product_id:
            ci["quantity"] += item.quantity
            merged = True
            break
    if not merged:
        cart["items"].append(item.model_dump())

    cart["subtotal"] = sum(i["price"] * i["quantity"] for i in cart["items"])
    db["cart"].update_one({"_id": cart["_id"]}, {"$set": {"items": cart["items"], "subtotal": cart["subtotal"]}})
    return {"cart_id": str(cart["_id"]), "subtotal": cart["subtotal"], "items": cart["items"]}


@app.get("/cart/{user_id}")
async def get_cart(user_id: str):
    cart = db["cart"].find_one({"user_id": user_id, "status": "active"})
    if not cart:
        return {"items": [], "subtotal": 0.0}
    cart["_id"] = str(cart["_id"])
    return cart


# Checkout -> create order
@app.post("/checkout/{user_id}")
async def checkout(user_id: str):
    cart = db["cart"].find_one({"user_id": user_id, "status": "active"})
    if not cart or not cart.get("items"):
        raise HTTPException(status_code=400, detail="Cart is empty")

    total = sum(i["price"] * i["quantity"] for i in cart["items"])
    order = Order(
        user_id=user_id,
        cart_id=str(cart["_id"]),
        items=cart["items"],
        total=total,
        status="pending",
        payment_method="gpay",
    )
    order_id = create_document("order", order)

    # reduce stock counts
    for i in cart["items"]:
        db["product"].update_one({"_id": oid(i["product_id"])}, {"$inc": {"stock": -i["quantity"]}})

    # mark cart checked_out
    db["cart"].update_one({"_id": cart["_id"]}, {"$set": {"status": "checked_out"}})

    return {"order_id": order_id, "total": total}


# Payment simulation for GPay
@app.post("/pay/gpay/{order_id}")
async def pay_gpay(order_id: str):
    order = db["order"].find_one({"_id": oid(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # Simulate success
    db["order"].update_one({"_id": order["_id"]}, {"$set": {"status": "paid"}})
    return {"status": "success"}


# Manager dashboard stats
@app.get("/manager/stats")
async def manager_stats():
    total_items = db["product"].count_documents({})
    sold = db["order"].aggregate([
        {"$match": {"status": {"$in": ["pending", "paid"]}}},
        {"$unwind": "$items"},
        {"$group": {"_id": None, "qty": {"$sum": "$items.quantity"}}},
    ])
    sold_qty = 0
    for s in sold:
        sold_qty = s.get("qty", 0)

    remaining = db["product"].aggregate([
        {"$group": {"_id": None, "qty": {"$sum": "$stock"}}},
    ])
    remaining_qty = 0
    for r in remaining:
        remaining_qty = r.get("qty", 0)

    revenue = db["order"].aggregate([
        {"$match": {"status": "paid"}},
        {"$group": {"_id": None, "total": {"$sum": "$total"}}},
    ])
    revenue_total = 0.0
    for rv in revenue:
        revenue_total = rv.get("total", 0.0)

    return {
        "total_items": total_items,
        "sold_items": sold_qty,
        "remaining_items": remaining_qty,
        "daily_revenue": revenue_total,
    }


# Digital receipt (email/SMS stub)
@app.post("/receipt/send")
async def send_receipt(req: ReceiptRequest):
    order = db["order"].find_one({"_id": oid(req.order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    # In a real system, integrate with email/SMS providers. Here we simulate.
    return {
        "status": "queued",
        "to": req.email or req.phone,
        "order_id": req.order_id,
        "message": "Receipt will be sent shortly",
    }


# Seed some demo products if empty
@app.post("/seed")
async def seed_products():
    count = db["product"].count_documents({})
    if count > 0:
        return {"message": "Products already exist"}
    items = [
        {"title": "Pen", "price": 1.5, "barcode": "PEN123", "stock": 100, "category": "stationery", "in_stock": True},
        {"title": "Milk", "price": 2.0, "barcode": "MILK123", "stock": 50, "category": "grocery", "in_stock": True},
        {"title": "Chocolate", "price": 3.0, "barcode": "CHOCO123", "stock": 75, "category": "snacks", "in_stock": True},
    ]
    for it in items:
        create_document("product", it)
    return {"message": "Seeded"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
