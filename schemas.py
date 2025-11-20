"""
Database Schemas for Smart Self-Checkout System

Each Pydantic model represents a MongoDB collection. The collection name is the
lowercased class name (e.g., User -> "user").
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime


class User(BaseModel):
    """
    Users collection schema
    Fields kept minimal for demo auth (no hashing for brevity).
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    phone: Optional[str] = Field(None, description="Mobile number")
    password: str = Field(..., description="Plain password for demo only")
    role: str = Field("customer", description="Role: customer or manager")
    is_active: bool = Field(True)


class Product(BaseModel):
    """Products collection schema"""
    title: str = Field(..., description="Product name")
    description: Optional[str] = Field(None)
    price: float = Field(..., ge=0)
    barcode: Optional[str] = Field(None, description="Barcode/QR code content")
    stock: int = Field(0, ge=0, description="Units in stock")
    category: Optional[str] = Field(None)
    in_stock: bool = Field(True)


class CartItem(BaseModel):
    product_id: str
    title: str
    price: float
    quantity: int = Field(1, ge=1)
    barcode: Optional[str] = None


class Cart(BaseModel):
    user_id: str
    items: List[CartItem] = []
    status: str = Field("active", description="active | checked_out | cancelled")
    subtotal: float = 0.0


class Order(BaseModel):
    user_id: str
    cart_id: str
    items: List[CartItem]
    total: float
    status: str = Field("pending", description="pending | paid | failed")
    payment_method: Optional[str] = None
    created_at: Optional[datetime] = None

