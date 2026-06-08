import sqlite3
import hashlib
import os
import random
import json
import uuid
import socket
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, abort

app = Flask(__name__)
app.secret_key = "super-secret-casino-key-12345"
DB_PATH = Path(__file__).parent / "casino.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                balance INTEGER DEFAULT 1000
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)


def hash_pw(password):
    return hashlib.sha256(password.encode()).hexdigest()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_user():
    user = None
    if "user_id" in session:
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return dict(user=user)


def get_local_ip():
    host_ip = os.environ.get("HOST_IP")
    if host_ip:
        return host_ip
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ─── ROUTES ──────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = hash_pw(request.form["password"].strip())
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
            if user:
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
            exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            return render_template("login.html", error="Неверный пароль")
        return render_template("login.html", error="Пользователь не найден")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        if len(username) < 3 or len(password) < 3:
            return render_template("register.html", error="Минимум 3 символа")
        with get_db() as conn:
            try:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                             (username, hash_pw(password)))
                conn.commit()
                user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
            except sqlite3.IntegrityError:
                return render_template("register.html", error="Имя занято")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login"))


# ─── DEPOSIT / QR PAYMENT ────────────────────────────────────

@app.route("/deposit")
@login_required
def deposit_form():
    return render_template("deposit_form.html")


@app.route("/deposit/create", methods=["POST"])
@login_required
def deposit_create():
    amount = int(request.form.get("amount", 0))
    if amount <= 0:
        return render_template("deposit_form.html", error="Сумма должна быть > 0")

    token = uuid.uuid4().hex[:16]
    with get_db() as conn:
        conn.execute("INSERT INTO payments (user_id, amount, token) VALUES (?, ?, ?)",
                     (session["user_id"], amount, token))
        conn.commit()

    ip = get_local_ip()
    pay_url = f"http://{ip}:5000/pay/{token}"
    return render_template("deposit.html", token=token, amount=amount, pay_url=pay_url)


@app.route("/deposit/status/<token>")
@login_required
def deposit_status(token):
    with get_db() as conn:
        pay = conn.execute(
            "SELECT * FROM payments WHERE token = ? AND user_id = ?",
            (token, session["user_id"])
        ).fetchone()
    if not pay:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": pay["status"], "amount": pay["amount"]})


@app.route("/pay/<token>")
def pay_confirm_page(token):
    with get_db() as conn:
        pay = conn.execute("SELECT * FROM payments WHERE token = ?", (token,)).fetchone()
    if not pay:
        return "Платёж не найден", 404
    if pay["status"] == "confirmed":
        return "<h2>✅ Платёж уже подтверждён</h2><p>Можешь закрыть страницу.</p>"
    return render_template("pay.html", amount=pay["amount"], token=token)


@app.route("/api/balance")
@login_required
def api_balance():
    with get_db() as conn:
        row = conn.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if row is None:
        return jsonify({"error": "user not found"}), 404
    return jsonify({"balance": row["balance"]})


@app.route("/pay/<token>/confirm")
def pay_do_confirm(token):
    with get_db() as conn:
        pay = conn.execute("SELECT * FROM payments WHERE token = ?", (token,)).fetchone()
        if not pay:
            return jsonify({"error": "not found"}), 404
        if pay["status"] == "confirmed":
            return jsonify({"status": "already_confirmed"})
        conn.execute("UPDATE payments SET status = 'confirmed' WHERE token = ?", (token,))
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (pay["amount"], pay["user_id"]))
        conn.commit()
    return jsonify({"status": "confirmed"})


# ─── BLACKJACK ───────────────────────────────────────────────

def new_deck():
    suits = ["♠", "♥", "♦", "♣"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    return [{"suit": s, "rank": r} for s in suits for r in ranks]


def card_value(card):
    if card["rank"] in ("J", "Q", "K"):
        return 10
    if card["rank"] == "A":
        return 11
    return int(card["rank"])


def hand_value(hand):
    v = sum(card_value(c) for c in hand)
    aces = sum(1 for c in hand if c["rank"] == "A")
    while v > 21 and aces:
        v -= 10
        aces -= 1
    return v


@app.route("/blackjack")
@login_required
def blackjack():
    return render_template("blackjack.html")


@app.route("/blackjack/start", methods=["POST"])
@login_required
def blackjack_start():
    bet = request.json.get("bet", 0)
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if bet <= 0 or bet > user["balance"]:
            return jsonify({"error": "Недостаточно средств или неверная ставка"}), 400
        deck = new_deck()
        random.shuffle(deck)
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        session["bj_deck"] = deck
        session["bj_player"] = player
        session["bj_dealer"] = dealer
        session["bj_bet"] = bet
    return jsonify({
        "player": player,
        "dealer": [dealer[0], {"suit": "?", "rank": "?"}],
        "player_value": hand_value(player),
    })


@app.route("/blackjack/hit", methods=["POST"])
@login_required
def blackjack_hit():
    deck = session.get("bj_deck", [])
    player = session.get("bj_player", [])
    player.append(deck.pop())
    session["bj_deck"] = deck
    session["bj_player"] = player
    v = hand_value(player)
    if v > 21:
        return jsonify({"player": player, "player_value": v, "bust": True})
    return jsonify({"player": player, "player_value": v})


@app.route("/blackjack/stand", methods=["POST"])
@login_required
def blackjack_stand():
    deck = session.get("bj_deck", [])
    player = session.get("bj_player", [])
    dealer = session.get("bj_dealer", [])
    bet = session.get("bj_bet", 0)

    while hand_value(dealer) < 17:
        dealer.append(deck.pop())

    pv = hand_value(player)
    dv = hand_value(dealer)
    result = "push"
    if dv > 21 or pv > dv:
        result = "win"
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (bet, session["user_id"]))
            conn.commit()
    elif pv < dv:
        result = "lose"
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet, session["user_id"]))
            conn.commit()

    with get_db() as conn:
        balance = conn.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],)).fetchone()[0]

    session.pop("bj_deck", None)
    session.pop("bj_player", None)
    session.pop("bj_dealer", None)
    session.pop("bj_bet", None)

    return jsonify({"dealer": dealer, "dealer_value": dv, "result": result, "balance": balance})


# ─── ROULETTE ────────────────────────────────────────────────

@app.route("/roulette")
@login_required
def roulette():
    return render_template("roulette.html")


@app.route("/roulette/spin", methods=["POST"])
@login_required
def roulette_spin():
    data = request.json
    bet_type = data["type"]
    bet_value = data.get("value")
    bet_amount = int(data["amount"])

    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if bet_amount <= 0 or bet_amount > user["balance"]:
            return jsonify({"error": "Недостаточно средств"}), 400
        conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (bet_amount, session["user_id"]))
        conn.commit()

    number = random.randint(0, 36)
    color = "red" if number in (1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36) else \
            "black" if number != 0 else "green"

    win = False
    multiplier = 0
    if bet_type == "number" and bet_value == number:
        win = True
        multiplier = 36
    elif bet_type == "color" and bet_value == color:
        win = True
        multiplier = 36 if color == "green" else 2
    elif bet_type == "parity":
        if (bet_value == "even" and number != 0 and number % 2 == 0) or \
           (bet_value == "odd" and number % 2 == 1):
            win = True
            multiplier = 2
    elif bet_type == "range":
        if (bet_value == "1-18" and 1 <= number <= 18) or \
           (bet_value == "19-36" and 19 <= number <= 36):
            win = True
            multiplier = 2

    payout = bet_amount * multiplier if win else 0
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (payout, session["user_id"]))
        conn.commit()
        balance = conn.execute("SELECT balance FROM users WHERE id = ?", (session["user_id"],)).fetchone()[0]

    return jsonify({
        "number": number, "color": color,
        "win": win, "payout": payout,
        "multiplier": multiplier if win else 0,
        "balance": balance,
    })


if __name__ == "__main__":
    init_db()
    local_ip = get_local_ip()
    print(f"🌐 Сервер доступен в локальной сети: http://{local_ip}:5000")
    print("📱 Сканируй QR с телефона для пополнения")
    app.run(host="0.0.0.0", port=5000, debug=True)
