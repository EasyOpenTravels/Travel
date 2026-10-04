import os, secrets, logging
from pathlib import Path
from flask import Flask, request, session, render_template
from .db import init_db, get_db
from .system_errors import record_error, ensure_error_log_table, DatabaseErrorHandler

def _secret(path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text().strip()
        if value: return value
    value = secrets.token_urlsafe(48); path.write_text(value)
    try: os.chmod(path, 0o600)
    except OSError: pass
    return value

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    import base64
    app.jinja_env.filters['b64encode'] = lambda b: base64.b64encode(b).decode('ascii')
    app.jinja_env.filters['fromjson'] = lambda s: __import__('json').loads(s or '[]')
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or _secret(Path(app.instance_path)/'session-secret.key'),
        DATABASE_PATH=os.environ.get('DATABASE_PATH', str(Path(app.instance_path)/'adventures.sqlite3')),
        UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', str(Path(app.instance_path)/'uploads')),
        BRAND_NAME=os.environ.get('BRAND_NAME','Open Road Adventures'),
        ADMIN_PATH=os.environ.get('ADMIN_PATH','promise212324').strip('/'),
        ADMIN_USERNAME=os.environ.get('ADMIN_USERNAME',''),
        ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD',''),
        MAX_CONTENT_LENGTH=12*1024*1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=True,
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        ensure_error_log_table(db)
        db.commit()
    if not any(isinstance(h, DatabaseErrorHandler) for h in app.logger.handlers):
        app.logger.addHandler(DatabaseErrorHandler())
    app.logger.setLevel(logging.ERROR)
    init_db(app)
    from .routes import bp
    from .admin import admin_bp
    app.register_blueprint(bp)
    app.register_blueprint(admin_bp, url_prefix='/'+app.config['ADMIN_PATH'])
    @app.errorhandler(404)
    def not_found(err):
        record_error(status_code=404,error_type=type(err).__name__,message=str(err),exc=None)
        return render_template('not_found.html'), 404

    @app.errorhandler(500)
    def server_error(err):
        record_error(status_code=500,error_type=type(err).__name__,message=str(err),exc=err)
        return render_template('error.html'), 500

    @app.errorhandler(Exception)
    def unhandled_exception(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            record_error(status_code=err.code or 500,error_type=type(err).__name__,message=str(err),exc=None)
            return err
        record_error(status_code=500,error_type=type(err).__name__,message=str(err),exc=err)
        return render_template('error.html'), 500

    @app.after_request
    def headers(resp):
        resp.headers['X-Content-Type-Options']='nosniff'; resp.headers['X-Frame-Options']='DENY'; resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        if request.path.startswith('/'+app.config['ADMIN_PATH']): resp.headers['Cache-Control']='no-store'
        return resp
    return app
app = create_app()
