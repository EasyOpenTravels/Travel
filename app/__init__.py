import os, secrets, logging, traceback
from pathlib import Path
from flask import Flask, request
from .db import init_db, get_db

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
    def _rotating_image(images, key=''):
        import hashlib, time
        vals=[x.strip() for x in str(images or '').split('|') if x.strip()]
        if not vals: return ''
        # Same place changes on the hour; a stable key keeps the change tied to the place.
        hour=int(time.time()//3600)
        seed=int(hashlib.sha256(str(key).lower().encode('utf-8')).hexdigest()[:12],16)
        return vals[(hour + seed) % len(vals)]
    app.jinja_env.filters['rotating_image'] = _rotating_image
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
    init_db(app)
    from .routes import bp
    from .admin import admin_bp
    app.register_blueprint(bp)
    app.register_blueprint(admin_bp, url_prefix='/'+app.config['ADMIN_PATH'])
    @app.errorhandler(404)
    def not_found(err):
        try:
            db=get_db(); uid=request.cookies.get('visitor_key','')
            db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),404,request.path,request.method,type(err).__name__,str(err),'',request.args.get('_uid'),uid,request.headers.get('User-Agent','')[:600],request.remote_addr or '')); db.commit()
        except Exception: app.logger.exception('Could not persist 404 analytics')
        return __import__('flask').render_template('not_found.html'), 404
    @app.errorhandler(500)
    def server_error(err):
        tb=traceback.format_exc()
        try:
            db=get_db(); db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),500,request.path,request.method,type(err).__name__,str(err),tb[-12000:],request.cookies.get('_uid'),request.cookies.get('visitor_key',''),request.headers.get('User-Agent','')[:600],request.remote_addr or '')); db.commit()
        except Exception: app.logger.exception('Could not persist 500 analytics')
        return __import__('flask').render_template('error.html'), 500
    @app.after_request
    def headers(resp):
        resp.headers['X-Content-Type-Options']='nosniff'; resp.headers['X-Frame-Options']='DENY'; resp.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        if request.path.startswith('/'+app.config['ADMIN_PATH']): resp.headers['Cache-Control']='no-store'
        return resp
    return app
app = create_app()
