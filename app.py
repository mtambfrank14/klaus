import os, re, secrets, sqlite3
from pathlib import Path
from functools import wraps
from datetime import datetime
from urllib.parse import quote

from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from flask_wtf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "klaus_store.db"
UPLOAD_DIR = BASE / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
csrf = CSRFProtect(app)

OWNER_USERNAME = os.environ.get("OWNER_USERNAME", "owner")
OWNER_PASSWORD = os.environ.get("OWNER_PASSWORD", "ChangeMe123!")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}

SEED_PRODUCTS = [
    ("Juventus", 250, "Jersey", "XL", "Black and White", 5),
    ("Jordan One (Low Cut)", 450, "Shoes", "40", "Black and Grey", 4),
    ("Jeans Short", 250, "Short", "32", "Grey", 7),
    ("T-Shirt", 180, "T-Shirt", "L", "Red and White", 6),
    ("Track Bottom", 350, "Bottom", "34", "Red", 5),
    ("Lofus", 550, "Shoes", "44", "Black and White", 3),
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL CHECK(price >= 0),
        category TEXT NOT NULL,
        size TEXT NOT NULL,
        colour TEXT NOT NULL,
        stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
        image TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        address TEXT NOT NULL,
        payment_method TEXT NOT NULL,
        total INTEGER NOT NULL CHECK(total >= 0),
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name TEXT NOT NULL,
        price INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        subtotal INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS owner_auth (
        id INTEGER PRIMARY KEY CHECK(id=1),
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        now = datetime.utcnow().isoformat(timespec="seconds")
        conn.executemany(
            "INSERT INTO products(name,price,category,size,colour,stock,image,created_at) VALUES(?,?,?,?,?,?,?,?)",
            [(n,p,c,s,col,st,"",now) for n,p,c,s,col,st in SEED_PRODUCTS]
        )
    if conn.execute("SELECT COUNT(*) FROM owner_auth").fetchone()[0] == 0:
        conn.execute("INSERT INTO owner_auth(id,username,password_hash) VALUES(1,?,?)",
                     (OWNER_USERNAME, generate_password_hash(OWNER_PASSWORD)))
    conn.commit()
    conn.close()

init_db()

@app.context_processor
def inject_globals():
    cart = session.get("cart", {})
    return {"cart_count": sum(int(v) for v in cart.values())}

@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response

def owner_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("owner_logged_in"):
            return redirect(url_for("owner_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def valid_int(value, minimum=0, maximum=100000000):
    try:
        n = int(value)
        return minimum <= n <= maximum, n
    except (TypeError, ValueError):
        return False, 0

def allowed_file(file):
    if not file or not file.filename:
        return False
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    return ext in ALLOWED_EXTENSIONS and file.mimetype in ALLOWED_MIME

def save_upload(file):
    if not file or not file.filename:
        return ""
    if not allowed_file(file):
        raise ValueError("Please upload a JPG, PNG or WEBP image.")
    ext = file.filename.rsplit(".", 1)[-1].lower()
    name = f"{secrets.token_hex(16)}.{ext}"
    file.save(UPLOAD_DIR / name)
    return f"uploads/{name}"

def get_product(pid):
    conn = db()
    p = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        abort(404)
    return p

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    conn = db()
    cats = [r["category"] for r in conn.execute("SELECT DISTINCT category FROM products ORDER BY category")]
    sql = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:
        sql += " AND (name LIKE ? OR category LIKE ? OR colour LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]
    if category:
        sql += " AND category=?"
        params.append(category)
    products = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
    conn.close()
    return render_template("index.html", products=products, categories=cats, q=q, category=category)

@app.route("/product/<int:pid>")
def product(pid):
    return render_template("product.html", product=get_product(pid))

@app.route("/cart")
def cart():
    cart = session.get("cart", {})
    ids = [int(k) for k,v in cart.items() if int(v) > 0]
    products = []
    total = 0
    if ids:
        conn = db()
        rows = conn.execute(f"SELECT * FROM products WHERE id IN ({','.join('?'*len(ids))})", ids).fetchall()
        conn.close()
        for p in rows:
            qty = int(cart.get(str(p["id"]), 0))
            subtotal = p["price"] * qty
            total += subtotal
            products.append((p, qty, subtotal))
    return render_template("cart.html", items=products, total=total)

@app.post("/cart/add/<int:pid>")
def cart_add(pid):
    p = get_product(pid)
    ok, qty = valid_int(request.form.get("quantity"), 1, 100)
    if not ok:
        flash("Invalid quantity.", "error")
        return redirect(request.referrer or url_for("index"))
    cart = session.get("cart", {})
    current = int(cart.get(str(pid), 0))
    if current + qty > p["stock"]:
        flash(f"Only {p['stock']} item(s) are currently in stock.", "error")
    else:
        cart[str(pid)] = current + qty
        session["cart"] = cart
        flash("Product added to cart.", "success")
    return redirect(request.referrer or url_for("index"))

@app.post("/cart/update")
def cart_update():
    cart = session.get("cart", {})
    conn = db()
    for key, val in request.form.items():
        if not key.startswith("qty_"): continue
        try: pid = int(key[4:]); qty = int(val)
        except ValueError: continue
        p = conn.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
        if p and qty > 0:
            cart[str(pid)] = min(qty, p["stock"])
        else:
            cart.pop(str(pid), None)
    conn.close()
    session["cart"] = cart
    flash("Cart updated.", "success")
    return redirect(url_for("cart"))

@app.post("/cart/remove/<int:pid>")
def cart_remove(pid):
    cart = session.get("cart", {})
    cart.pop(str(pid), None)
    session["cart"] = cart
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET","POST"])
def checkout():
    if not session.get("cart"):
        flash("Your cart is empty.", "error")
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("checkout.html")
    name = request.form.get("customer_name","").strip()
    phone = request.form.get("phone","").strip()
    address = request.form.get("address","").strip()
    payment = request.form.get("payment_method","").strip()
    if not (2 <= len(name) <= 80 and re.fullmatch(r"[0-9+ ()-]{7,20}", phone or "")):
        flash("Please enter a valid name and phone number.", "error"); return render_template("checkout.html")
    if not (5 <= len(address) <= 250):
        flash("Please enter a valid delivery address.", "error"); return render_template("checkout.html")
    if payment not in {"MTN Money","Airtel Money","Cash"}:
        flash("Please choose a payment method.", "error"); return render_template("checkout.html")

    cart = session.get("cart", {})
    conn = db()
    try:
        ids = [int(k) for k,v in cart.items() if int(v)>0]
        if not ids: raise ValueError("Cart is empty.")
        rows = conn.execute(f"SELECT * FROM products WHERE id IN ({','.join('?'*len(ids))})", ids).fetchall()
        byid = {p["id"]: p for p in rows}
        total = 0
        order_items = []
        for key, q in cart.items():
            pid, qty = int(key), int(q)
            p = byid.get(pid)
            if not p or qty < 1 or qty > p["stock"]:
                raise ValueError(f"Stock changed for {p['name'] if p else 'a product'}. Please review your cart.")
            subtotal = p["price"] * qty
            total += subtotal
            order_items.append((p, qty, subtotal))
        now = datetime.utcnow().isoformat(timespec="seconds")
        cur = conn.execute(
            "INSERT INTO orders(customer_name,phone,address,payment_method,total,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (name, phone, address, payment, total, "Pending", now)
        )
        oid = cur.lastrowid
        for p, qty, subtotal in order_items:
            conn.execute("INSERT INTO order_items(order_id,product_id,product_name,price,quantity,subtotal) VALUES(?,?,?,?,?,?)",
                         (oid,p["id"],p["name"],p["price"],qty,subtotal))
            conn.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?", (qty,p["id"],qty))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        flash(str(e), "error")
        return redirect(url_for("cart"))
    conn.close()
    session["cart"] = {}
    return render_template("success.html", order_id=oid, total=total, payment=payment, phone=phone)

@app.route("/whatsapp")
def whatsapp():
    cart = session.get("cart", {})
    conn = db()
    lines = ["Hello Klaus's Store, I would like to order:"]
    total = 0
    for key, qty in cart.items():
        p = conn.execute("SELECT * FROM products WHERE id=?", (int(key),)).fetchone()
        if p and int(qty)>0:
            sub = p["price"]*int(qty); total += sub
            lines.append(f"- {p['name']} x{qty} = K{sub:,}")
    conn.close()
    lines.append(f"Total: K{total:,}")
    lines.append("Please confirm availability and delivery.")
    msg = quote("\n".join(lines))
    return redirect(f"https://wa.me/260979530787?text={msg}")

@app.route("/owner/login", methods=["GET","POST"])
def owner_login():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        conn = db(); row = conn.execute("SELECT * FROM owner_auth WHERE id=1").fetchone(); conn.close()
        if row and secrets.compare_digest(username, row["username"]) and check_password_hash(row["password_hash"], password):
            session.clear(); session["owner_logged_in"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid owner login.", "error")
    return render_template("login.html")

@app.post("/owner/logout")
@owner_required
def owner_logout():
    session.clear()
    return redirect(url_for("index"))

@app.route("/owner/password", methods=["GET","POST"])
@owner_required
def owner_password():
    if request.method == "POST":
        current = request.form.get("current","")
        new = request.form.get("new","")
        confirm = request.form.get("confirm","")
        conn = db(); row = conn.execute("SELECT * FROM owner_auth WHERE id=1").fetchone()
        if not check_password_hash(row["password_hash"], current):
            conn.close(); flash("Current password is incorrect.", "error")
        elif len(new) < 12 or new != confirm:
            conn.close(); flash("New passwords must match and be at least 12 characters.", "error")
        else:
            conn.execute("UPDATE owner_auth SET password_hash=? WHERE id=1", (generate_password_hash(new),))
            conn.commit(); conn.close(); flash("Password changed successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("password.html")

@app.route("/owner")
@owner_required
def dashboard():
    conn = db()
    stats = {
        "products": conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"],
        "stock": conn.execute("SELECT COALESCE(SUM(stock),0) c FROM products").fetchone()["c"],
        "orders": conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"],
        "sales": conn.execute("SELECT COALESCE(SUM(total),0) c FROM orders WHERE status!='Cancelled'").fetchone()["c"],
    }
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 30").fetchall()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, orders=orders, products=products)

@app.route("/owner/product/new", methods=["GET","POST"])
@owner_required
def product_new():
    if request.method == "POST":
        return save_product(None)
    return render_template("product_form.html", product=None)

@app.route("/owner/product/<int:pid>/edit", methods=["GET","POST"])
@owner_required
def product_edit(pid):
    p = get_product(pid)
    if request.method == "POST":
        return save_product(pid)
    return render_template("product_form.html", product=p)

def save_product(pid):
    name=request.form.get("name","").strip(); category=request.form.get("category","").strip()
    size=request.form.get("size","").strip(); colour=request.form.get("colour","").strip()
    ok, price=valid_int(request.form.get("price"),0,10000000)
    ok2, stock=valid_int(request.form.get("stock"),0,1000000)
    if not all([2<=len(name)<=100, 1<=len(category)<=60, 1<=len(size)<=30, 1<=len(colour)<=80, ok, ok2]):
        flash("Please fill all product fields correctly.", "error")
        return redirect(request.url)
    conn=db()
    old=conn.execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone() if pid else None
    image=old["image"] if old else ""
    try:
        if request.files.get("image") and request.files["image"].filename:
            image=save_upload(request.files["image"])
        now=datetime.utcnow().isoformat(timespec="seconds")
        if pid:
            conn.execute("UPDATE products SET name=?,price=?,category=?,size=?,colour=?,stock=?,image=? WHERE id=?",
                         (name,price,category,size,colour,stock,image,pid))
            msg="Product updated."
        else:
            conn.execute("INSERT INTO products(name,price,category,size,colour,stock,image,created_at) VALUES(?,?,?,?,?,?,?,?)",
                         (name,price,category,size,colour,stock,image,now))
            msg="Product added."
        conn.commit(); conn.close(); flash(msg,"success")
        return redirect(url_for("dashboard"))
    except Exception as e:
        conn.rollback(); conn.close(); flash(str(e),"error"); return redirect(request.url)

@app.post("/owner/product/<int:pid>/delete")
@owner_required
def product_delete(pid):
    conn=db()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit(); conn.close()
    flash("Product deleted.","success")
    return redirect(url_for("dashboard"))

@app.post("/owner/order/<int:oid>/status")
@owner_required
def order_status(oid):
    status=request.form.get("status")
    allowed={"Pending","Confirmed","Ready","Delivered","Cancelled"}
    if status not in allowed: abort(400)
    conn=db()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status,oid))
    conn.commit(); conn.close()
    flash("Order status updated.","success")
    return redirect(url_for("dashboard"))

@app.errorhandler(413)
def too_large(e):
    flash("Image is too large. Maximum upload size is 5 MB.","error")
    return redirect(request.referrer or url_for("dashboard"))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
