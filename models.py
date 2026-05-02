import hashlib
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base, engine, SessionLocal


def hash_password(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()


def verify_password(plain: str, hashed: str) -> bool:
    return hash_password(plain) == hashed


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role = Column(String, default="cashier")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    dot_color = Column(String, default="brown")
    badge = Column(String, nullable=True)
    image = Column(String, nullable=True)  # filename in /static/products/
    is_available = Column(Boolean, default=True)


class ShopSettings(Base):
    __tablename__ = "shop_settings"
    id = Column(Integer, primary_key=True, default=1)
    gcash_number = Column(String, nullable=True)
    gcash_qr = Column(String, nullable=True)  # filename in /static/


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    items_json = Column(Text, nullable=False)
    total_amount = Column(Float, nullable=False)
    payment_method = Column(String, nullable=False)
    amount_tendered = Column(Float, nullable=True)
    change_given = Column(Float, nullable=True)
    cashier_id = Column(Integer, ForeignKey("users.id"))
    is_voided = Column(Boolean, default=False)
    void_reason = Column(String, nullable=True)
    cashier = relationship("User")


def seed():
    db = SessionLocal()
    if db.query(User).first():
        db.close()
        return
    db.add_all([
        User(username="admin",    password=hash_password("admin123"),   role="admin"),
        User(username="cashier1", password=hash_password("cashier123"), role="cashier"),
    ])
    # name, category, price, dot_color, badge, image
    products = [
        # Hot Coffee
        ("Americano",                 "Hot Coffee",      49, "red",   None,          None),
        ("Latte",                     "Hot Coffee",      79, "red",   None,          None),
        ("Cappuccino",                "Hot Coffee",      79, "red",   None,          None),
        ("Spanish Latte",             "Hot Coffee",      79, "red",   None,          None),
        ("Caramel Macchiato",         "Hot Coffee",      79, "red",   None,          None),
        ("Cafe Mocha",                "Hot Coffee",      79, "red",   None,          None),
        # Hot Non-Coffee
        ("Matcha Latte",              "Hot Non-Coffee",  79, "red",   None,          None),
        # Iced Espresso
        ("Salted Caramel",            "Iced Espresso",  110, "blue",  "Best Seller", "salted-caramel.jpg"),
        ("Signature Coffee",          "Iced Espresso",  110, "blue",  None,          "signature-coffee.jpg"),
        ("Dalgona",                   "Iced Espresso",  110, "blue",  None,          "dalgona.png"),
        ("Sweetened Double Espresso", "Iced Espresso",   99, "blue",  None,          "sweetened-double-espresso.jpg"),
        ("Caramel Macchiato",         "Iced Espresso",   99, "blue",  None,          "caramel-macchiato.png"),
        ("Mocha",                     "Iced Espresso",   99, "blue",  None,          "mocha.png"),
        ("Mint Latte",                "Iced Espresso",   99, "blue",  None,          "mint-latte.png"),
        ("Spanish Latte",             "Iced Espresso",   79, "blue",  None,          "spanish-latte.png"),
        # Iced Non-Coffee
        ("Strawberry Refresher",      "Iced Non-Coffee",120, "blue",  None,          "strawberry-refresher.jpg"),
        ("Strawberry Latte",          "Iced Non-Coffee", 99, "blue",  "Best Seller", "strawberry-latte.jpg"),
        ("Tsokolate De Baterol",      "Iced Non-Coffee", 99, "brown", None,          "tsokolate-de-baterol.jpg"),
        ("Minty Chocolate",           "Iced Non-Coffee", 99, "blue",  None,          "minty-chocolate.png"),
        # Matcha
        ("Matcha Creamcheese",        "Matcha",         120, "green", None,          "matcha-creamcheese.png"),
        ("Matcha Charcoal",           "Matcha",         120, "green", None,          "matcha-charcoal.png"),
        ("Matcha Strawberry",         "Matcha",         110, "green", None,          "matcha-strawberry.jpg"),
        ("Matcha Latte",              "Matcha",          99, "green", None,          "matcha-latte.png"),
        # Pastries
        ("Chocolate Brownies",        "Pastries",        49, "cream", None,          None),
        ("Biscoff Blondies",          "Pastries",        49, "cream", None,          None),
        ("Chocolate Chip Cookies",    "Pastries",        49, "cream", None,          None),
        ("Matcha Cookies",            "Pastries",        49, "cream", None,          None),
    ]
    for name, cat, price, dot, badge, image in products:
        db.add(Product(name=name, category=cat, price=price,
                       dot_color=dot, badge=badge, image=image))
    db.commit()
    db.close()


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    seed()
    print("Database initialized and seeded.")
