import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "facilities.db"
HTML_PATH = APP_DIR / "facilities-manager.html"
SESSION_COOKIE = "fm_session"
DEFAULT_ADMIN_USER = os.environ.get("FM_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("FM_ADMIN_PASSWORD", "ChangeMe123!")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return salt, base64.b64encode(digest).decode("ascii")


def verify_password(password, salt, stored_hash):
    _, candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored_hash)


def init_db():
    with db() as conn:
        conn.execute("""
            create table if not exists users (
                id integer primary key autoincrement,
                username text not null unique,
                password_salt text not null,
                password_hash text not null,
                role text not null default 'admin',
                created_at integer not null
            )
        """)
        conn.execute("""
            create table if not exists sessions (
                token text primary key,
                user_id integer not null,
                expires_at integer not null,
                foreign key(user_id) references users(id)
            )
        """)
        conn.execute("""
            create table if not exists app_state (
                id integer primary key check (id = 1),
                payload text not null,
                updated_at integer not null,
                updated_by integer
            )
        """)
        conn.execute("""
            create table if not exists backups (
                id integer primary key autoincrement,
                payload text not null,
                created_at integer not null,
                created_by integer
            )
        """)
        user_count = conn.execute("select count(*) from users").fetchone()[0]
        if user_count == 0:
            salt, password_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            conn.execute(
                "insert into users (username, password_salt, password_hash, role, created_at) values (?, ?, ?, ?, ?)",
                (DEFAULT_ADMIN_USER, salt, password_hash, "admin", int(time.time())),
            )


def read_body(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    return handler.rfile.read(length)


def safe_json_loads(raw):
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


class FacilitiesHandler(BaseHTTPRequestHandler):
    server_version = "FacilitiesManager/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self.send_login()
            return
        if parsed.path == "/logout":
            self.logout()
            return
        if parsed.path == "/api/state":
            self.require_user_then(self.get_state)
            return
        if parsed.path == "/api/backup":
            self.require_user_then(self.download_backup)
            return
        if parsed.path in ("/", "/facilities-manager.html"):
            self.require_user_then(self.send_app)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":
            self.login()
            return
        if parsed.path == "/api/state":
            self.require_user_then(self.save_state)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def current_user(self):
        cookies = self.headers.get("Cookie", "")
        token = ""
        for part in cookies.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE:
                token = value
                break
        if not token:
            return None
        now = int(time.time())
        with db() as conn:
            row = conn.execute(
                "select users.* from sessions join users on users.id = sessions.user_id where sessions.token = ? and sessions.expires_at > ?",
                (token, now),
            ).fetchone()
        return row

    def require_user_then(self, callback):
        user = self.current_user()
        if not user:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/login")
            self.end_headers()
            return
        callback(user)

    def send_text(self, text, content_type="text/html; charset=utf-8", status=HTTPStatus.OK, extra_headers=None):
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=HTTPStatus.OK):
        self.send_text(json.dumps(payload), "application/json; charset=utf-8", status)

    def send_login(self):
        self.send_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Facilities Manager Login</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: Arial, Helvetica, sans-serif; background: #f6f5f1; color: #202327; }}
    form {{ width: min(380px, calc(100vw - 28px)); background: #fff; border: 1px solid #d9ddd4; border-radius: 8px; padding: 22px; box-shadow: 0 8px 28px rgba(33,37,41,.08); display: grid; gap: 12px; }}
    h1 {{ margin: 0 0 4px; font-size: 24px; }}
    p {{ margin: 0 0 12px; color: #6b7280; font-size: 14px; }}
    label {{ display: grid; gap: 6px; font-size: 13px; font-weight: 700; }}
    input {{ min-height: 40px; border: 1px solid #cfd5cc; border-radius: 8px; padding: 9px 10px; font: inherit; }}
    button {{ min-height: 40px; border: 0; border-radius: 8px; background: #2f6f4e; color: #fff; font: inherit; cursor: pointer; }}
    .hint {{ color: #6b7280; font-size: 12px; line-height: 1.4; }}
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>Facilities Manager</h1>
    <p>Sign in to the shared business system.</p>
    <label>Username<input name="username" autocomplete="username" required></label>
    <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Sign in</button>
    <div class="hint">First run default: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}. Change this by setting FM_ADMIN_USER and FM_ADMIN_PASSWORD before first launch.</div>
  </form>
</body>
</html>""")

    def login(self):
        fields = parse_qs(read_body(self).decode("utf-8"))
        username = fields.get("username", [""])[0]
        password = fields.get("password", [""])[0]
        with db() as conn:
            user = conn.execute("select * from users where username = ?", (username,)).fetchone()
            if not user or not verify_password(password, user["password_salt"], user["password_hash"]):
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", "/login")
                self.end_headers()
                return
            token = secrets.token_urlsafe(32)
            conn.execute(
                "insert into sessions (token, user_id, expires_at) values (?, ?, ?)",
                (token, user["id"], int(time.time()) + 60 * 60 * 12),
            )
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200")
        self.end_headers()

    def logout(self):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.end_headers()

    def get_state_payload(self):
        with db() as conn:
            row = conn.execute("select payload from app_state where id = 1").fetchone()
        return row["payload"] if row else ""

    def send_app(self, user):
        html = HTML_PATH.read_text(encoding="utf-8")
        payload = self.get_state_payload()
        bootstrap = f"""
<script>
  window.__FM_SERVER_MODE__ = true;
  window.__FM_SERVER_STATE__ = {payload if payload else "null"};
  (function () {{
    const syncKey = 'facilities-manager-v1';
    if (window.__FM_SERVER_STATE__) {{
      localStorage.setItem(syncKey, JSON.stringify(window.__FM_SERVER_STATE__));
    }}
    const originalSetItem = localStorage.setItem.bind(localStorage);
    let syncTimer = null;
    localStorage.setItem = function (key, value) {{
      originalSetItem(key, value);
      if (key !== syncKey) return;
      clearTimeout(syncTimer);
      syncTimer = setTimeout(function () {{
        fetch('/api/state', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: value
        }}).catch(function () {{}});
      }}, 250);
    }};
  }})();
</script>
"""
        html = html.replace("<script>\n    const storeKey", bootstrap + "\n  <script>\n    const storeKey")
        html = html.replace('<button class="btn" id="importData">', '<a class="btn" href="/api/backup" style="text-decoration:none;">Server Backup</a><a class="btn" href="/logout" style="text-decoration:none;">Sign out</a><button class="btn" id="importData">')
        self.send_text(html)

    def get_state(self, user):
        payload = self.get_state_payload()
        self.send_text(payload or "null", "application/json; charset=utf-8")

    def save_state(self, user):
        raw = read_body(self)
        parsed = safe_json_loads(raw)
        if not isinstance(parsed, dict):
            self.send_json({"ok": False, "error": "Invalid state"}, HTTPStatus.BAD_REQUEST)
            return
        payload = json.dumps(parsed, separators=(",", ":"))
        now = int(time.time())
        with db() as conn:
            conn.execute("insert into backups (payload, created_at, created_by) values (?, ?, ?)", (payload, now, user["id"]))
            conn.execute(
                "insert into app_state (id, payload, updated_at, updated_by) values (1, ?, ?, ?) on conflict(id) do update set payload = excluded.payload, updated_at = excluded.updated_at, updated_by = excluded.updated_by",
                (payload, now, user["id"]),
            )
        self.send_json({"ok": True, "updated_at": now})

    def download_backup(self, user):
        payload = self.get_state_payload() or "{}"
        filename = f"facilities-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
        self.send_text(
            payload,
            "application/json; charset=utf-8",
            HTTPStatus.OK,
            {"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


def main():
    init_db()
    host = os.environ.get("FM_HOST", "127.0.0.1")
    port = int(os.environ.get("FM_PORT", "8088"))
    server = ThreadingHTTPServer((host, port), FacilitiesHandler)
    print(f"Facilities Manager running at http://{host}:{port}")
    print(f"Login: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}")
    print("Keep this window open while using the system.")
    server.serve_forever()


if __name__ == "__main__":
    main()
