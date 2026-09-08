import hashlib, hmac, secrets, base64
from datetime import datetime, timezone
from flask import current_app
from werkzeug.security import generate_password_hash, check_password_hash
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def token(n=16): return secrets.token_urlsafe(n)

def hash_pin(pin): return generate_password_hash(pin)
def verify_pin(value, pin): return bool(value) and check_password_hash(value, pin)
def hash_answer(answer): return generate_password_hash(answer.strip().lower())
def verify_answer(value, answer): return bool(value) and check_password_hash(value, answer.strip().lower())

def ticket_secret():
    from .db import get_db
    row = get_db().execute("SELECT value FROM settings WHERE key='ticket_secret'").fetchone()
    return row['value'] if row else ''

def ticket_signature(code):
    return hmac.new(ticket_secret().encode(), code.encode(), hashlib.sha256).hexdigest()
def verify_ticket(code, sig):
    expected = ticket_signature(code)
    return bool(sig) and hmac.compare_digest(expected, sig)


def _secret_cipher():
    if Fernet is None:
        raise RuntimeError('Secure secret storage requires cryptography.')
    raw = hashlib.sha256(str(current_app.config.get('SECRET_KEY','')).encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(raw))

def encrypt_secret(value):
    value = str(value or '')
    return _secret_cipher().encrypt(value.encode('utf-8')).decode('ascii') if value else ''

def decrypt_secret(value):
    if not value:
        return ''
    try:
        return _secret_cipher().decrypt(str(value).encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError, TypeError):
        return ''
