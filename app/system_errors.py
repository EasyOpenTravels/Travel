import logging, os, traceback
from datetime import datetime, timezone
from flask import current_app, request, session, has_request_context
from .db import get_db

_MAX_TRACE = 18000

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    return (forwarded or request.remote_addr or '')[:120]

def ensure_error_log_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            path TEXT NOT NULL,
            method TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL,
            traceback TEXT DEFAULT '',
            user_id INTEGER,
            visitor_key TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            ip_address TEXT DEFAULT '',
            resolved INTEGER NOT NULL DEFAULT 0,
            context TEXT DEFAULT ''
        )
    """)
    cols = {r[1] for r in db.execute('PRAGMA table_info(error_logs)').fetchall()}
    if 'resolved' not in cols:
        db.execute("ALTER TABLE error_logs ADD COLUMN resolved INTEGER NOT NULL DEFAULT 0")
    if 'context' not in cols:
        db.execute("ALTER TABLE error_logs ADD COLUMN context TEXT DEFAULT ''")
    db.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_occurred ON error_logs(occurred_at)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_error_logs_status ON error_logs(status_code)')

def _emergency_file(line):
    try:
        path = os.path.join(current_app.instance_path, 'system-errors.log')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(line.rstrip() + '\n')
    except Exception:
        pass

def record_error(*, status_code=500, error_type='Exception', message='', exc=None,
                 path=None, method=None, user_id=None, context=''):
    """Best-effort persistence. The error recorder must never break the request."""
    tb = ''
    if exc is not None:
        tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    elif status_code >= 500:
        tb = traceback.format_exc()
    tb = tb[-_MAX_TRACE:]
    path = (path if path is not None else getattr(request, 'path', ''))[:1000]
    method = (method if method is not None else getattr(request, 'method', ''))[:20]
    message = str(message or (exc if exc is not None else ''))[:5000]
    if has_request_context():
        user_id = user_id if user_id is not None else session.get('user_id')
        visitor_key = request.cookies.get('visitor_key', '')[:300]
        ua = request.headers.get('User-Agent', '')[:800]
        ip = client_ip()
    else:
        visitor_key = ''
        ua = ''
        ip = ''
    context = str(context or '')[:4000]
    line = f"{utc_now()} [{status_code}] {method} {path} {error_type}: {message}"
    try:
        db = get_db()
        ensure_error_log_table(db)
        db.execute("""
            INSERT INTO error_logs
            (occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address,context)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (utc_now(), int(status_code), path, method, str(error_type)[:200], message, tb,
              user_id, visitor_key, ua, ip, context))
        db.commit()
    except Exception:
        _emergency_file(line + ('\n' + tb if tb else ''))
    return None

class DatabaseErrorHandler(logging.Handler):
    """Persist app.logger ERROR/CRITICAL records without ever re-raising."""
    def emit(self, record):
        try:
            exc = record.exc_info[1] if record.exc_info else None
            record_error(status_code=500, error_type=record.name + '.' + record.levelname,
                         message=record.getMessage(), exc=exc, context='python logger')
        except Exception:
            pass
