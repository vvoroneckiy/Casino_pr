import sys
import json
import sqlite3
import random
from pathlib import Path

DB_PATH = Path(__file__).parent / "casino.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─── TOOLS ──────────────────────────────────────────────────

def get_user(username):
    with get_db() as conn:
        user = conn.execute("SELECT id, username, balance FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return {"error": f"Пользователь '{username}' не найден"}
    return {"id": user["id"], "username": user["username"], "balance": user["balance"]}


def list_users():
    with get_db() as conn:
        users = conn.execute("SELECT id, username, balance FROM users ORDER BY id").fetchall()
    return [{"id": u["id"], "username": u["username"], "balance": u["balance"]} for u in users]


def play_roulette(username, bet_type, value, amount):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return {"error": f"Пользователь '{username}' не найден"}
    if amount <= 0 or amount > user["balance"]:
        return {"error": "Недостаточно средств или неверная ставка"}

    number = random.randint(0, 36)
    color = "red" if number in (1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36) else \
            "black" if number != 0 else "green"

    win = False
    multiplier = 0
    if bet_type == "number" and value == number:
        win = True
        multiplier = 36
    elif bet_type == "color" and value == color:
        win = True
        multiplier = 36 if color == "green" else 2
    elif bet_type == "parity":
        if (value == "even" and number != 0 and number % 2 == 0) or \
           (value == "odd" and number % 2 == 1):
            win = True
            multiplier = 2
    elif bet_type == "range":
        if (value == "1-18" and 1 <= number <= 18) or \
           (value == "19-36" and 19 <= number <= 36):
            win = True
            multiplier = 2

    payout = amount * multiplier if win else 0
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user["id"]))
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (payout, user["id"]))
        conn.commit()
        new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()[0]

    colors_ru = {"red": "🔴 красное", "black": "⚫ чёрное", "green": "🟢 зеро"}
    result_text = f"🎡 Выпало {number} ({colors_ru[color]})\n"
    if win:
        result_text += f"🎉 Выигрыш! +{payout}₽ (x{multiplier})\n"
    else:
        result_text += f"😞 Проигрыш: -{amount}₽\n"
    result_text += f"💰 Баланс: {new_balance}₽"
    return {"result": result_text, "number": number, "color": color, "win": win, "payout": payout, "balance": new_balance}


def blackjack(username, bet):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return {"error": f"Пользователь '{username}' не найден"}
    if bet <= 0 or bet > user["balance"]:
        return {"error": "Недостаточно средств или неверная ставка"}

    suits = ["♠", "♥", "♦", "♣"]
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
    deck = [{"s": s, "r": r} for s in suits for r in ranks]
    random.shuffle(deck)

    def cv(c):
        if c["r"] in ("J", "Q", "K"):
            return 10
        if c["r"] == "A":
            return 11
        return int(c["r"])

    def hv(hand):
        v = sum(cv(c) for c in hand)
        aces = sum(1 for c in hand if c["r"] == "A")
        while v > 21 and aces:
            v -= 10
            aces -= 1
        return v

    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    pv = hv(player)
    dv = hv(dealer)

    # Auto-play dealer
    while dv < 17:
        dealer.append(deck.pop())
        dv = hv(dealer)

    result = "push"
    if dv > 21 or pv > dv:
        result = "win"
        payout = bet
    elif pv < dv:
        result = "lose"
        payout = -bet
    else:
        payout = 0

    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (payout, user["id"]))
        conn.commit()
        new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()[0]

    def fc(c):
        return f"{c['s']}{c['r']}"

    result_text = f"🃏 Игрок: {' '.join(fc(c) for c in player)} ({pv})\n"
    result_text += f"🃏 Дилер: {' '.join(fc(c) for c in dealer)} ({dv})\n"
    if result == "win":
        result_text += f"🎉 Победа! +{bet}₽\n"
    elif result == "lose":
        result_text += f"😞 Проигрыш: -{bet}₽\n"
    else:
        result_text += f"🤝 Ничья\n"
    result_text += f"💰 Баланс: {new_balance}₽"
    return {"result": result_text, "player": pv, "dealer": dv, "result_type": result, "balance": new_balance}


def deposit_user(username, amount):
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        return {"error": f"Пользователь '{username}' не найден"}
    if amount <= 0:
        return {"error": "Сумма должна быть > 0"}
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user["id"]))
        conn.commit()
        new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()[0]
    return {"result": f"✅ Баланс пополнен на {amount}₽. Текущий баланс: {new_balance}₽", "balance": new_balance}


TOOLS = [
    {
        "name": "list_users",
        "description": "Список всех пользователей казино",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_user",
        "description": "Информация о пользователе (баланс, id)",
        "inputSchema": {
            "type": "object",
            "properties": {"username": {"type": "string", "description": "Имя пользователя"}},
            "required": ["username"],
        },
    },
    {
        "name": "play_roulette",
        "description": "Сделать ставку в рулетке",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Имя пользователя"},
                "bet_type": {"type": "string", "description": "Тип ставки: number, color, parity, range"},
                "value": {"type": "string", "description": "Значение: число 0-36, red/black/green, even/odd, 1-18/19-36"},
                "amount": {"type": "integer", "description": "Сумма ставки в ₽"},
            },
            "required": ["username", "bet_type", "value", "amount"],
        },
    },
    {
        "name": "blackjack",
        "description": "Сыграть в блэкджек (автоматическая игра до конца)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Имя пользователя"},
                "bet": {"type": "integer", "description": "Ставка в ₽"},
            },
            "required": ["username", "bet"],
        },
    },
    {
        "name": "deposit",
        "description": "Пополнить баланс пользователя",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Имя пользователя"},
                "amount": {"type": "integer", "description": "Сумма пополнения в ₽"},
            },
            "required": ["username", "amount"],
        },
    },
]


def handle_tool_call(name, args):
    try:
        if name == "list_users":
            return list_users()
        elif name == "get_user":
            return get_user(args["username"])
        elif name == "play_roulette":
            return play_roulette(args["username"], args["bet_type"], args["value"], args["amount"])
        elif name == "blackjack":
            return blackjack(args["username"], args["bet"])
        elif name == "deposit":
            return deposit_user(args["username"], args["amount"])
        return {"error": f"Неизвестный инструмент: {name}"}
    except Exception as e:
        return {"error": str(e)}


def send_response(request_id, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": request_id}
    if error:
        msg["error"] = {"code": -32603, "message": str(error)}
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            req = json.loads(line.strip())
        except json.JSONDecodeError:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            send_response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "casino-mcp", "version": "1.0.0"},
            })
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send_response(req_id, {"tools": TOOLS})
        elif method == "tools/call":
            result = handle_tool_call(params["name"], params.get("arguments", {}))
            if "error" in result:
                content = [{"type": "text", "text": result["error"]}]
            elif "result" in result:
                content = [{"type": "text", "text": result["result"]}]
            else:
                content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            send_response(req_id, {"content": content})
        elif method == "shutdown":
            send_response(req_id, {})
            break
        else:
            send_response(req_id, error=f"Unknown method: {method}")


if __name__ == "__main__":
    main()
