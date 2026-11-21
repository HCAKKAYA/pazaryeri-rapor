"""Panel kullanıcıları ve oturumlar (SQLite, yalnız standart kütüphane).

- Parolalar scrypt ile tuzlanıp özetlenir; düz metin hiçbir yerde tutulmaz.
- Oturum çerezi rastgele bir belirteçtir; veritabanında yalnız SHA-256 özeti durur,
  veritabanı sızsa bile çerez üretilemez.
- Kayıt yok: kullanıcıları yönetici (`cli.py kullanici-ekle`) açar, her kullanıcı tek mağazaya bağlıdır.
- Hatalı girişler e-posta ve IP başına sınırlanır.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

SESSION_TTL = 14 * 24 * 3600          # 14 gün
MAX_FAILS, FAIL_WINDOW = 5, 15 * 60   # 15 dakikada 5 hatalı deneme
MIN_PASSWORD = 10
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)


class AuthError(Exception):
    pass


@dataclass
class User:
    id: int
    email: str
    store: str          # mağaza slug'ı


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${dk.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        algo, salt, dk = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    got = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt), **_SCRYPT)
    return hmac.compare_digest(got.hex(), dk)


# Kullanıcı yokken de parola özeti hesaplanır: yanıt süresinden e-postanın var olup olmadığı anlaşılmasın.
_DUMMY = hash_password(secrets.token_hex(8))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self._fails: dict[str, list[float]] = {}
        with self._lock:
            self._db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    pw TEXT NOT NULL, store TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires REAL NOT NULL);
            """)

    # ------------------------------------------------------------ yönetim
    def add_user(self, email: str, password: str, store: str) -> None:
        email = email.strip().lower()
        if "@" not in email:
            raise AuthError("Geçersiz e-posta")
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Parola en az {MIN_PASSWORD} karakter olmalı")
        with self._lock:
            try:
                self._db.execute("INSERT INTO users (email, pw, store, created) VALUES (?,?,?,?)",
                                 (email, hash_password(password), store, time.time()))
                self._db.commit()
            except sqlite3.IntegrityError as e:
                raise AuthError("Bu e-posta zaten kayıtlı") from e

    def set_password(self, email: str, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise AuthError(f"Parola en az {MIN_PASSWORD} karakter olmalı")
        with self._lock:
            cur = self._db.execute("UPDATE users SET pw=? WHERE email=?", (hash_password(password), email.strip().lower()))
            if cur.rowcount == 0:
                raise AuthError("Kullanıcı yok")
            # Parola değişince açık oturumlar kapanır.
            self._db.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)", (email.strip().lower(),))
            self._db.commit()

    def remove_user(self, email: str) -> bool:
        with self._lock:
            uid = self._db.execute("SELECT id FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
            if not uid:
                return False
            self._db.execute("DELETE FROM sessions WHERE user_id=?", uid)
            self._db.execute("DELETE FROM users WHERE id=?", uid)
            self._db.commit()
            return True

    def list_users(self) -> list[tuple[str, str]]:
        with self._lock:
            return self._db.execute("SELECT email, store FROM users ORDER BY email").fetchall()

    # ------------------------------------------------------------ giriş
    def _limited(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW]
        self._fails[key] = recent
        return len(recent) >= MAX_FAILS

    def login(self, email: str, password: str, ip: str) -> str:
        """Başarılıysa oturum belirteci döndürür; değilse AuthError (hep aynı mesaj)."""
        email = (email or "").strip().lower()
        keys = (f"e:{email}", f"i:{ip}")
        if any(self._limited(k) for k in keys):
            raise AuthError("Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.")
        with self._lock:
            row = self._db.execute("SELECT id, pw FROM users WHERE email=?", (email,)).fetchone()
        ok = check_password(password or "", row[1] if row else _DUMMY) and row is not None
        if not ok:
            for k in keys:
                self._fails.setdefault(k, []).append(time.time())
            raise AuthError("E-posta ya da parola hatalı.")
        self._fails.pop(f"e:{email}", None)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            self._db.execute("INSERT INTO sessions VALUES (?,?,?)", (_token_hash(token), row[0], time.time() + SESSION_TTL))
            self._db.commit()
        return token

    def user_for(self, token: str | None) -> User | None:
        if not token:
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT u.id, u.email, u.store FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token=? AND s.expires > ?", (_token_hash(token), time.time())).fetchone()
        return User(*row) if row else None

    def logout(self, token: str | None) -> None:
        if token:
            with self._lock:
                self._db.execute("DELETE FROM sessions WHERE token=?", (_token_hash(token),))
                self._db.commit()
