import os, re, shutil, sqlite3, hmac, secrets, tempfile, zipfile, json, pathlib
from datetime import datetime, timezone
from flask import Blueprint,current_app,render_template,request,redirect,url_for,session,flash,send_file,abort,g
from werkzeug.utils import secure_filename
from .db import get_db,SCHEMA,ensure_schema_upgrades
from .security import now, encrypt_secret, verify_pin, hash_pin
from .system_errors import record_error, ensure_error_log_table
from .qr import make_qr_bytes
import io

admin_bp=Blueprint('admin',__name__)

def guard():
    if not session.get('admin_auth'): return redirect(url_for('admin.login'))
    return None

def slugify(s):
    return re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-') or 'item'

def unique_slug(db,base,table,ignore_id=None):
    slug=slugify(base); candidate=slug; n=2
    while True:
        q=f'SELECT id FROM {table} WHERE slug=?'; params=[candidate]
        if ignore_id: q+=' AND id!=?'; params.append(ignore_id)
        if not db.execute(q,params).fetchone(): return candidate
        candidate=f'{slug}-{n}'; n+=1

@admin_bp.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u=request.form.get('username',''); p=request.form.get('password',''); tries=int(session.get('admin_attempts',0))
        if tries>=8: flash('Too many attempts. Please try again later.','error'); return render_template('admin_login.html')
        good=bool(current_app.config['ADMIN_USERNAME'] and current_app.config['ADMIN_PASSWORD']) and hmac.compare_digest(u,current_app.config['ADMIN_USERNAME']) and hmac.compare_digest(p,current_app.config['ADMIN_PASSWORD'])
        if good:
            session.clear(); session['admin_auth']=True; session.permanent=True; return redirect(url_for('admin.dashboard'))
        session['admin_attempts']=tries+1; flash('Those admin details are not correct.','error')
    return render_template('admin_login.html')

@admin_bp.get('/logout')
def logout(): session.clear(); return redirect(url_for('admin.login'))

@admin_bp.get('/')
def dashboard():
    g=guard()
    if g:return g
    db=get_db();
    stats={
        'users':db.execute('SELECT COUNT(*) n FROM users WHERE deleted_at IS NULL').fetchone()['n'],
        'bookings':db.execute("SELECT COUNT(*) n FROM bookings WHERE payment_status!='cancelled'").fetchone()['n'],
        'paid':db.execute("SELECT COUNT(*) n FROM bookings WHERE payment_status IN ('paid','confirmed')").fetchone()['n'],
        'tickets':db.execute('SELECT COUNT(*) n FROM tickets').fetchone()['n'],
        'visitors':db.execute("SELECT COUNT(DISTINCT visitor_key) n FROM visits WHERE created_at>=datetime('now','-1 day')").fetchone()['n'],
        'messages':db.execute("SELECT COUNT(*) n FROM messages WHERE status='unread'").fetchone()['n'],
        'event_tickets':db.execute('SELECT COUNT(*) n FROM event_tickets').fetchone()['n'],
        'event_pending':db.execute("SELECT COUNT(*) n FROM event_tickets WHERE approval_status='pending'").fetchone()['n'],
        'groups':db.execute('SELECT COUNT(*) n FROM group_retreats WHERE active=1').fetchone()['n'],
        'group_pending':db.execute("SELECT COUNT(*) n FROM group_retreats WHERE status='pending' AND active=1").fetchone()['n'],
        'payment_intents':db.execute('SELECT COUNT(*) n FROM payment_intents').fetchone()['n'],
        'accesses_24h':db.execute("SELECT COUNT(*) n FROM access_logs WHERE created_at>=datetime('now','-1 day')").fetchone()['n'],
        'devices_24h':db.execute("SELECT COUNT(DISTINCT device_key_hash) n FROM access_logs WHERE created_at>=datetime('now','-1 day')").fetchone()['n'],
        'jobs':db.execute("SELECT COUNT(*) n FROM jobs WHERE status='published'").fetchone()['n'],
    }
    rows={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings').fetchall()}
    trips=db.execute('SELECT * FROM trips ORDER BY date').fetchall(); destinations=db.execute('SELECT * FROM destinations ORDER BY sort_order,id').fetchall(); posts=db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall(); services=db.execute('SELECT * FROM services ORDER BY sort_order,id').fetchall(); service_requests=db.execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id ORDER BY sr.id DESC LIMIT 12').fetchall()
    return render_template('admin_dashboard.html',stats=stats,settings=rows,trips=trips,destinations=destinations,posts=posts,services=services,service_requests=service_requests, events=db.execute('SELECT * FROM event_ticket_events ORDER BY id DESC LIMIT 12').fetchall(), groups=db.execute('SELECT * FROM group_retreats WHERE active=1 ORDER BY id DESC LIMIT 12').fetchall())

@admin_bp.route('/trips/new',methods=['GET','POST'])
@admin_bp.route('/trips/<int:trip_id>/edit',methods=['GET','POST'])
def trip_edit(trip_id=None):
    g=guard()
    if g:return g
    db=get_db(); t=db.execute('SELECT * FROM trips WHERE id=?',(trip_id,)).fetchone() if trip_id else None
    if request.method=='POST':
        data={k:request.form.get(k,'').strip() for k in ['title','destination','description','date','pickup','itinerary','included','excluded','cover_image','gallery']}
        try: price=max(0,int(request.form.get('price','0'))); cap=max(1,int(request.form.get('capacity','1')))
        except ValueError: price,cap=0,1
        status=request.form.get('status','published'); status=status if status in ('published','draft','completed') else 'draft'
        slug=t['slug'] if t else unique_slug(db,data['title'],'trips')
        vals=(data['title'],data['destination'],data['description'],data['date'],price,cap,data['pickup'],data['itinerary'],data['included'],data['excluded'],data['cover_image'],data['gallery'],status)
        if trip_id: db.execute('UPDATE trips SET title=?,destination=?,description=?,date=?,price=?,capacity=?,pickup=?,itinerary=?,included=?,excluded=?,cover_image=?,gallery=?,status=? WHERE id=?',vals+(trip_id,))
        else: db.execute('INSERT INTO trips(slug,title,destination,description,date,price,capacity,pickup,itinerary,included,excluded,cover_image,gallery,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(slug,)+vals+(now(),))
        db.commit(); flash('Adventure saved.','success'); return redirect(url_for('admin.dashboard'))
    return render_template('admin_trip.html',trip=t)

@admin_bp.route('/destinations/new',methods=['GET','POST'])
@admin_bp.route('/destinations/<int:destination_id>/edit',methods=['GET','POST'])
def destination_edit(destination_id=None):
    g=guard()
    if g:return g
    db=get_db(); d=db.execute('SELECT * FROM destinations WHERE id=?',(destination_id,)).fetchone() if destination_id else None
    if request.method=='POST':
        title=request.form.get('title','').strip(); subtitle=request.form.get('subtitle','').strip(); vibe=request.form.get('vibe','').strip(); image=request.form.get('cover_image','').strip(); credit=request.form.get('credit','').strip(); source=request.form.get('source_url','').strip(); active=1 if request.form.get('active')=='1' else 0
        try: price=max(0,int(request.form.get('price_from','0'))); order=int(request.form.get('sort_order','0'))
        except ValueError: price,order=0,0
        slug=d['slug'] if d else unique_slug(db,title,'destinations')
        vals=(title,subtitle,vibe,price,image,credit,source,active,order)
        if destination_id: db.execute('UPDATE destinations SET title=?,subtitle=?,vibe=?,price_from=?,cover_image=?,credit=?,source_url=?,active=?,sort_order=? WHERE id=?',vals+(destination_id,))
        else: db.execute('INSERT INTO destinations(slug,title,subtitle,vibe,price_from,cover_image,credit,source_url,active,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(slug,)+vals+(now(),))
        db.commit(); flash('Place saved.','success'); return redirect(url_for('admin.dashboard'))
    return render_template('admin_destination.html',destination=d)

@admin_bp.route('/posts/new',methods=['GET','POST'])
@admin_bp.route('/posts/<int:post_id>/edit',methods=['GET','POST'])
def post_edit(post_id=None):
    g=guard()
    if g:return g
    db=get_db(); p=db.execute('SELECT * FROM posts WHERE id=?',(post_id,)).fetchone() if post_id else None
    if request.method=='POST':
        title=request.form.get('title','').strip(); excerpt=request.form.get('excerpt','').strip(); body=request.form.get('body','').strip(); image=request.form.get('image','').strip(); media=request.form.get('media_url','').strip(); category=request.form.get('category','From the road').strip(); published=1 if request.form.get('published')=='1' else 0
        if not title or not body: flash('Give the post a title and story.','error'); return render_template('admin_post.html',post=p)
        if p: db.execute('UPDATE posts SET title=?,excerpt=?,body=?,image=?,media_url=?,category=?,published=? WHERE id=?',(title,excerpt,body,image,media,category,published,post_id))
        else: db.execute('INSERT INTO posts(title,excerpt,body,image,media_url,category,published,created_at) VALUES(?,?,?,?,?,?,?,?)',(title,excerpt,body,image,media,category,published,now()))
        db.commit(); flash('Road post published.','success'); return redirect(url_for('admin.dashboard'))
    return render_template('admin_post.html',post=p)

@admin_bp.route('/services/new',methods=['GET','POST'])
@admin_bp.route('/services/<int:service_id>/edit',methods=['GET','POST'])
def service_edit(service_id=None):
    g=guard()
    if g:return g
    db=get_db(); svc=db.execute('SELECT * FROM services WHERE id=?',(service_id,)).fetchone() if service_id else None
    if request.method=='POST':
        title=request.form.get('title','').strip(); category=request.form.get('category','Events').strip(); subtitle=request.form.get('subtitle','').strip(); description=request.form.get('description','').strip(); image=request.form.get('cover_image','').strip(); accent=request.form.get('accent','lime').strip(); ticketing=1 if request.form.get('ticketing_available')=='1' else 0; published=1 if request.form.get('published')=='1' else 0
        if not title or not subtitle or not description: flash('Give the service a title, subtitle and description.','error'); return render_template('admin_service.html',service=svc)
        slug=svc['slug'] if svc else unique_slug(db,title,'services')
        if service_id: db.execute('UPDATE services SET category=?,title=?,subtitle=?,description=?,cover_image=?,accent=?,ticketing_available=?,published=? WHERE id=?',(category,title,subtitle,description,image,accent,ticketing,published,service_id))
        else:
            n=db.execute('SELECT COALESCE(MAX(sort_order),0)+1 n FROM services').fetchone()['n']; db.execute('INSERT INTO services(slug,category,title,subtitle,description,cover_image,accent,ticketing_available,published,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(slug,category,title,subtitle,description,image,accent,ticketing,published,n,now()))
        db.commit(); flash('Service saved.','success'); return redirect(url_for('admin.dashboard'))
    return render_template('admin_service.html',service=svc)

@admin_bp.get('/service-requests')
def service_requests():
    g=guard()
    if g:return g
    rows=get_db().execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id ORDER BY sr.id DESC').fetchall()
    return render_template('admin_service_requests.html',requests=rows)

@admin_bp.post('/service-requests/<int:request_id>/status')
def service_request_status(request_id):
    g=guard()
    if g:return g
    status=request.form.get('status','new')
    if status not in ('new','contacted','planning','complete','closed'): abort(400)
    db=get_db(); db.execute('UPDATE service_requests SET status=? WHERE id=?',(status,request_id)); db.commit(); flash('Service request updated.','success'); return redirect(url_for('admin.service_requests'))

@admin_bp.post('/settings')
def settings():
    g=guard()
    if g:return g
    db=get_db()
    allowed=['promo_counter','promo_growth_daily','payment_paybill','payment_till','payment_name','contact_phone','contact_email','site_tagline','payment_business_shortcode','payment_transaction_type','payment_currency','ticketing_fee_percent','event_mpesa_listener_token']
    for key in allowed:
        value=request.form.get(key,'').strip()
        if key in ('promo_counter','promo_growth_daily'):
            try:value=str(max(0,int(value)))
            except ValueError:value='0'
        db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(key,value))
    db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('promo_anchor',?)",(datetime.now(timezone.utc).date().isoformat(),)); db.commit(); flash('Settings saved.','success'); return redirect(url_for('admin.dashboard'))

@admin_bp.get('/visitor-qr')
def visitor_qr():
    gate=guard()
    if gate:return gate
    image=make_qr_bytes(url_for('public.home', _external=True))
    return send_file(io.BytesIO(image), mimetype='image/png', download_name='open-road-visitor-qr.png')

@admin_bp.get('/bookings')
def bookings():
    g=guard()
    if g:return g
    rows=get_db().execute('SELECT b.*,t.title,t.date FROM bookings b JOIN trips t ON t.id=b.trip_id ORDER BY b.id DESC').fetchall(); return render_template('admin_bookings.html',bookings=rows)

@admin_bp.post('/bookings/<int:booking_id>/status')
def booking_status(booking_id):
    g=guard()
    if g:return g
    status=request.form.get('status','awaiting_payment')
    if status not in ('awaiting_payment','payment_submitted','paid','confirmed','cancelled'): abort(400)
    db=get_db(); db.execute('UPDATE bookings SET payment_status=?,paid_at=? WHERE id=?',(status,now() if status in ('paid','confirmed') else None,booking_id)); db.commit(); flash('Booking status updated.','success'); return redirect(url_for('admin.bookings'))

@admin_bp.route('/messages')
def messages():
    g=guard()
    if g:return g
    return render_template('admin_messages.html',messages=get_db().execute('SELECT * FROM messages ORDER BY id DESC').fetchall())
@admin_bp.post('/messages/<int:message_id>/reply')
def reply(message_id):
    g=guard()
    if g:return g
    db=get_db(); db.execute("UPDATE messages SET admin_reply=?,status='replied' WHERE id=?",(request.form.get('reply','').strip(),message_id)); db.commit(); return redirect(url_for('admin.messages'))

@admin_bp.get('/users')
def users():
    g=guard()
    if g:return g
    return render_template('admin_users.html',users=get_db().execute('SELECT * FROM users ORDER BY id DESC').fetchall())
@admin_bp.get('/access')
def access():
    g=guard()
    if g:return g
    db=get_db()
    rows=db.execute("SELECT a.*,u.name user_name,u.email user_email,COALESCE(NULLIF(a.phone,''),u.phone,'') shown_phone FROM access_logs a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 300").fetchall()
    devices=db.execute("SELECT device_key_hash,MAX(created_at) last_seen,COUNT(*) hits,COUNT(DISTINCT COALESCE(user_id,0)) identities,MAX(phone) phone,MAX(latitude) latitude,MAX(longitude) longitude FROM access_logs GROUP BY device_key_hash ORDER BY last_seen DESC LIMIT 120").fetchall()
    return render_template('admin_access.html',rows=rows,devices=devices)

@admin_bp.get('/jobs')
def jobs():
    g=guard()
    if g:return g
    rows=get_db().execute("SELECT j.*,u.name poster_name,u.phone poster_phone,u.email poster_email FROM jobs j JOIN users u ON u.id=j.posted_by_user_id ORDER BY j.id DESC").fetchall()
    return render_template('admin_jobs.html',jobs=rows)

@admin_bp.post('/jobs/<int:job_id>/status')
def job_status(job_id):
    g=guard()
    if g:return g
    status=request.form.get('status','published')
    if status not in {'published','hidden'}: status='hidden'
    db=get_db(); db.execute('UPDATE jobs SET status=? WHERE id=?',(status,job_id)); db.commit()
    return redirect(url_for('admin.jobs'))

@admin_bp.get('/tickets')
def tickets():
    g=guard()
    if g:return g
    rows=get_db().execute('SELECT tk.*,b.ref,b.name,b.phone,t.title,t.date FROM tickets tk JOIN bookings b ON b.id=tk.booking_id JOIN trips t ON t.id=b.trip_id ORDER BY tk.id DESC').fetchall(); return render_template('admin_tickets.html',tickets=rows)
@admin_bp.get('/scanner')
def scanner():
    g=guard()
    if g:return g
    return render_template('admin_scanner.html')
@admin_bp.get('/votes/<int:trip_id>')
def votes(trip_id):
    g=guard()
    if g:return g
    db=get_db(); t=db.execute('SELECT * FROM trips WHERE id=?',(trip_id,)).fetchone(); rows=db.execute('SELECT * FROM votes WHERE trip_id=? ORDER BY id DESC',(trip_id,)).fetchall(); stats=db.execute('SELECT COUNT(*) n,ROUND(AVG(rating),1) avg FROM votes WHERE trip_id=?',(trip_id,)).fetchone(); return render_template('admin_votes.html',trip=t,votes=rows,stats=stats)

@admin_bp.post('/upload')
def upload():
    g=guard()
    if g:return g
    f=request.files.get('file')
    if not f or not f.filename: flash('Choose an image.','error'); return redirect(url_for('admin.dashboard'))
    fn=secure_filename(f.filename); ext=fn.rsplit('.',1)[-1].lower() if '.' in fn else ''
    if ext not in {'jpg','jpeg','png','webp','gif'}: flash('Use JPG, PNG, WEBP or GIF.','error'); return redirect(url_for('admin.dashboard'))
    stem,ext=fn.rsplit('.',1); fn=f'{stem}-{secrets.token_hex(3)}.{ext}' if os.path.exists(os.path.join(current_app.config['UPLOAD_FOLDER'],fn)) else fn
    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'],fn)); flash('Uploaded. Use this URL in a trip/place/post image field: /media/'+fn,'success'); return redirect(url_for('admin.dashboard'))

def _copy_database_snapshot(source_path, target_path):
    src=sqlite3.connect(source_path, timeout=60)
    try:
        dst=sqlite3.connect(target_path, timeout=60)
        try:
            src.backup(dst)
            dst.commit()
            check=dst.execute('PRAGMA integrity_check').fetchone()[0]
            if str(check).lower()!='ok':
                raise RuntimeError('Database snapshot failed integrity check: '+str(check))
        finally:
            dst.close()
    finally:
        src.close()


def _validate_and_normalize_backup(source_path):
    conn=sqlite3.connect(source_path, timeout=60)
    try:
        result=conn.execute('PRAGMA integrity_check').fetchone()[0]
        if str(result).lower()!='ok':
            raise RuntimeError('The backup is corrupt or incomplete (integrity check: %s).' % result)
        conn.row_factory=sqlite3.Row
        ensure_schema_upgrades(conn)
        result=conn.execute('PRAGMA integrity_check').fetchone()[0]
        if str(result).lower()!='ok':
            raise RuntimeError('The backup could not be upgraded safely (integrity check: %s).' % result)
    finally:
        conn.close()


@admin_bp.get('/backup')
def backup():
    gate=guard()
    if gate:return gate
    db_path=current_app.config['DATABASE_PATH']
    work=tempfile.mkdtemp(prefix='openroad-backup-')
    db_copy=pathlib.Path(work)/'database.sqlite3'
    zip_path=pathlib.Path(work)/'open-road-adventures-backup.zip'
    try:
        live=get_db()
        try:
            live.execute('PRAGMA wal_checkpoint(FULL)'); live.commit()
        finally:
            live.close(); g.pop('db',None)
        _copy_database_snapshot(db_path,db_copy)
        manifest={'format':'open-road-backup-v2','created_at':now(),'database':'database.sqlite3','uploads_included':True}
        upload_root=pathlib.Path(current_app.config['UPLOAD_FOLDER'])
        with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
            z.write(db_copy,'database.sqlite3')
            z.writestr('manifest.json',json.dumps(manifest,indent=2))
            if upload_root.exists():
                for file in upload_root.rglob('*'):
                    if file.is_file(): z.write(file,file.relative_to(upload_root).as_posix())
        response=send_file(str(zip_path),as_attachment=True,download_name='open-road-adventures-backup.zip',mimetype='application/zip')
        response.call_on_close(lambda: shutil.rmtree(work,ignore_errors=True))
        return response
    except Exception as exc:
        shutil.rmtree(work,ignore_errors=True)
        record_error(status_code=500,error_type='BackupExportError',message=str(exc),exc=exc,context='admin backup')
        flash('Backup could not be created: '+str(exc),'error')
        return redirect(url_for('admin.dashboard'))


@admin_bp.post('/restore')
def restore():
    gate=guard()
    if gate:return gate
    uploaded=request.files.get('backup')
    if not uploaded or not uploaded.filename:
        flash('Choose a backup file. ZIP backups and .sqlite3/.db files are accepted.','error')
        return redirect(url_for('admin.dashboard'))
    work=tempfile.mkdtemp(prefix='openroad-restore-')
    name=uploaded.filename.lower()
    try:
        incoming=pathlib.Path(work)/'incoming'
        uploaded.save(str(incoming))
        source=incoming
        restored_uploads=None
        if name.endswith('.zip') or zipfile.is_zipfile(incoming):
            extract=pathlib.Path(work)/'unzipped'; extract.mkdir(parents=True,exist_ok=True)
            with zipfile.ZipFile(incoming) as z:
                safe=[]
                for member in z.infolist():
                    parts=pathlib.PurePosixPath(member.filename).parts
                    if member.filename.startswith('/') or '..' in parts: continue
                    safe.append(member)
                db_member=next((m.filename for m in safe if m.filename=='database.sqlite3'),None)
                if not db_member:
                    db_member=next((m.filename for m in safe if m.filename.lower().endswith(('.sqlite3','.db','.sqlite'))),None)
                if not db_member: raise ValueError('This ZIP does not contain a SQLite database.')
                z.extractall(str(extract),members=safe)
            source=extract/db_member
            candidate=extract/'uploads'
            if candidate.is_dir(): restored_uploads=candidate
        elif not name.endswith(('.sqlite3','.db','.sqlite')):
            raise ValueError('Unsupported backup format. Use the new ZIP backup or a SQLite .sqlite3/.db/.sqlite file.')

        normalized=pathlib.Path(work)/'normalized.sqlite3'
        _copy_database_snapshot(source,normalized)
        _validate_and_normalize_backup(normalized)
        # Make a safety snapshot before changing the active database.
        # Keep a persistent rollback copy outside the temporary restore workspace.
        backup_dir=pathlib.Path(current_app.instance_path)/'backups'; backup_dir.mkdir(parents=True,exist_ok=True)
        safety=backup_dir/f"pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.sqlite3"
        current=current_app.config['DATABASE_PATH']
        live=get_db()
        try:
            live.execute('PRAGMA wal_checkpoint(FULL)'); live.commit()
        except Exception: pass
        finally:
            live.close(); g.pop('db',None)
        _copy_database_snapshot(current,safety)
        # Keep the newest five rollback snapshots only.
        safety_files=sorted(backup_dir.glob('pre-restore-*.sqlite3'), key=lambda x:x.stat().st_mtime, reverse=True)
        for old_safety in safety_files[5:]:
            try: old_safety.unlink()
            except OSError: pass

        target=sqlite3.connect(current,timeout=60)
        src=sqlite3.connect(normalized,timeout=60)
        try:
            src.backup(target)
            target.commit()
            check=target.execute('PRAGMA integrity_check').fetchone()[0]
            if str(check).lower()!='ok': raise RuntimeError('Restored database failed integrity check: '+str(check))
        finally:
            src.close(); target.close()

        from .db import init_db
        init_db(current_app)
        if restored_uploads:
            dest=pathlib.Path(current_app.config['UPLOAD_FOLDER']); dest.mkdir(parents=True,exist_ok=True)
            for file in restored_uploads.rglob('*'):
                if file.is_file():
                    rel=file.relative_to(restored_uploads); out=dest/rel; out.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(file,out)
        flash('Backup restored successfully. It was integrity-checked and upgraded before activation.','success')
    except Exception as exc:
        record_error(status_code=500,error_type='BackupRestoreError',message=str(exc),exc=exc,context='admin restore')
        flash('Restore rejected: '+str(exc),'error')
    finally:
        shutil.rmtree(work,ignore_errors=True)
    return redirect(url_for('admin.dashboard'))


@admin_bp.get('/errors')
def system_errors():
    gate=guard()
    if gate:return gate
    try:
        db=get_db(); ensure_error_log_table(db)
        rows=db.execute('SELECT * FROM error_logs ORDER BY id DESC LIMIT 250').fetchall()
        summary=db.execute('SELECT COUNT(*) total,SUM(CASE WHEN status_code>=500 THEN 1 ELSE 0 END) server,SUM(CASE WHEN status_code=404 THEN 1 ELSE 0 END) not_found,SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) open FROM error_logs').fetchone()
        return render_template('admin_errors.html',errors=rows,summary=summary)
    except Exception as exc:
        record_error(status_code=500,error_type='ErrorPageFailure',message=str(exc),exc=exc,context='admin system errors page')
        return 'System errors page could not be loaded.',500


@admin_bp.post('/errors/<int:error_id>/resolve')
def resolve_system_error(error_id):
    gate=guard()
    if gate:return gate
    db=get_db(); ensure_error_log_table(db)
    db.execute('UPDATE error_logs SET resolved=1 WHERE id=?',(error_id,)); db.commit()
    flash('System error marked resolved.','success')
    return redirect(url_for('admin.system_errors'))


@admin_bp.post('/errors/clear-resolved')
def clear_resolved_errors():
    gate=guard()
    if gate:return gate
    db=get_db(); ensure_error_log_table(db)
    db.execute('DELETE FROM error_logs WHERE resolved=1'); db.commit()
    flash('Resolved system errors cleared.','success')
    return redirect(url_for('admin.system_errors'))


@admin_bp.get('/events')
def events():
    gate=guard()
    if gate:return gate
    db=get_db()
    rows=db.execute("""SELECT e.*,u.name owner_name,
      COUNT(t.id) ticket_count,
      SUM(CASE WHEN t.approval_status='pending' THEN 1 ELSE 0 END) pending_count,
      SUM(CASE WHEN t.approval_status='approved' THEN 1 ELSE 0 END) approved_count,
      SUM(CASE WHEN t.ticket_status='used' THEN 1 ELSE 0 END) used_count
      FROM event_ticket_events e JOIN users u ON u.id=e.owner_user_id
      LEFT JOIN event_tickets t ON t.event_id=e.id GROUP BY e.id ORDER BY e.id DESC""").fetchall()
    return render_template('admin_event_ticketing.html',events=rows)

@admin_bp.post('/events/<int:event_id>/status')
def event_status(event_id):
    gate=guard()
    if gate:return gate
    status=request.form.get('status','active')
    active=1 if status in {'active','open'} else 0
    db=get_db(); db.execute('UPDATE event_ticket_events SET active=? WHERE id=?',(active,event_id)); db.commit()
    flash('Event status updated.','success')
    return redirect(url_for('admin.events'))

@admin_bp.post('/events/<int:event_id>/ticket/<int:ticket_id>')
def event_ticket_action(event_id,ticket_id):
    gate=guard()
    if gate:return gate
    action=request.form.get('action','').strip().lower(); db=get_db()
    row=db.execute('SELECT * FROM event_tickets WHERE id=? AND event_id=?',(ticket_id,event_id)).fetchone()
    if not row: abort(404)
    if action=='approve':
        event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
        tier=row['ticket_tier'] if row['ticket_tier'] in {'regular','vip','vvip'} else 'regular'
        expected=int(event['regular_price'] or event['price'] or 0) if (event['ticket_style'] or 'tiers')=='single' else int(event[f'{tier}_price'] or 0)
        if int(row['amount'])!=expected or expected<=0:
            flash('This ticket cannot be approved because its amount does not exactly match the configured ticket price.','error')
        else:
            db.execute("UPDATE event_tickets SET approval_status='approved',payment_status='verified',approval_method='admin',approved_at=? WHERE id=?",(now(),ticket_id)); db.commit(); flash('Ticket approved.','success')
    elif action in {'reject','void'}:
        db.execute("UPDATE event_tickets SET approval_status='rejected',payment_status='rejected',ticket_status='void' WHERE id=?",(ticket_id,)); db.commit(); flash('Ticket rejected/voided.','success')
    return redirect(url_for('admin.events'))

@admin_bp.get('/groups')
def groups():
    gate=guard()
    if gate:return gate
    db=get_db(); rows=db.execute("""SELECT g.*,COUNT(m.id) member_count,
      SUM(CASE WHEN m.payment_status='approved' THEN 1 ELSE 0 END) paid_count
      FROM group_retreats g LEFT JOIN group_members m ON m.retreat_id=g.id
      GROUP BY g.id ORDER BY g.id DESC""").fetchall()
    return render_template('admin_group_retreats.html',groups=rows)

@admin_bp.post('/groups/<int:group_id>/status')
def group_status(group_id):
    gate=guard()
    if gate:return gate
    status=request.form.get('status','pending')
    allowed={'pending','approved','active','complete','closed'}
    if status not in allowed: abort(400)
    db=get_db(); db.execute('UPDATE group_retreats SET status=?,approved_at=? WHERE id=?',(status,now() if status in {'approved','active'} else None,group_id)); db.commit(); flash('Group plan status updated.','success'); return redirect(url_for('admin.groups'))

@admin_bp.post('/groups/<int:group_id>/member/<int:member_id>/payment')
def group_member_payment(group_id,member_id):
    gate=guard()
    if gate:return gate
    status=request.form.get('status','pending');
    if status not in {'pending','approved','rejected'}: abort(400)
    db=get_db(); db.execute('UPDATE group_members SET payment_status=? WHERE id=? AND retreat_id=?',(status,member_id,group_id)); db.commit(); flash('Group member payment updated.','success'); return redirect(url_for('admin.groups'))

@admin_bp.post('/groups/<int:group_id>/message')
def group_message(group_id):
    gate=guard()
    if gate:return gate
    message=request.form.get('admin_message','').strip()[:1500]
    db=get_db(); db.execute('UPDATE group_retreats SET admin_message=? WHERE id=?',(message,group_id)); db.commit(); flash('Reply saved for the group leader.','success'); return redirect(url_for('admin.groups'))

@admin_bp.post('/groups/<int:group_id>/delete')
def group_delete(group_id):
    gate=guard()
    if gate:return gate
    db=get_db(); db.execute('UPDATE group_retreats SET active=0,status=\'closed\' WHERE id=?',(group_id,)); db.commit(); flash('Group archived.','success'); return redirect(url_for('admin.groups'))

@admin_bp.get('/payments')
def payments():
    gate=guard()
    if gate:return gate
    rows=get_db().execute('SELECT * FROM payment_intents ORDER BY id DESC LIMIT 200').fetchall()
    return render_template('admin_payments.html',payments=rows)

@admin_bp.route('/payment-settings',methods=['GET','POST'])
def payment_settings():
    gate=guard()
    if gate:return gate
    db=get_db()
    from .payments import mpesa_configured, payment_callback_url, _secret
    if request.method=='POST':
        section=request.form.get('section','collection')
        if section=='credentials':
            for key in ('mpesa_consumer_key','mpesa_consumer_secret','mpesa_passkey','mpesa_callback_token'):
                value=request.form.get(key,'').strip()
                if value:
                    db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(key,encrypt_secret(value)))
            db.commit(); flash('Daraja credentials saved securely.','success')
        elif section=='collection':
            for key in ('payment_till','payment_paybill','payment_business_shortcode','payment_transaction_type','payment_name','payment_currency'):
                db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(key,request.form.get(key,'').strip()))
            try: fee=min(100,max(0,float(request.form.get('ticketing_fee_percent','5') or 5)))
            except ValueError: fee=5
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('ticketing_fee_percent',str(fee)))
            db.commit(); flash('Payment collection settings saved.','success')
        elif section=='change_password':
            # The main admin login password is environment-backed in this build.
            flash('Admin login credentials are managed by the deployment environment. Payment secrets can be changed here without exposing them.','success')
        elif section=='delete_configuration':
            # Keep historical payment records; remove only provider credentials/configuration.
            for key in ('mpesa_consumer_key','mpesa_consumer_secret','mpesa_passkey','mpesa_callback_token','payment_till','payment_paybill','payment_business_shortcode'):
                db.execute('DELETE FROM settings WHERE key=?',(key,))
            db.commit(); flash('Payment provider configuration removed. Historical payment records remain.','success')
        return redirect(url_for('admin.payment_settings'))
    settings={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings').fetchall()}
    secret_state={k:bool(_secret(k)) for k in ('mpesa_consumer_key','mpesa_consumer_secret','mpesa_passkey','mpesa_callback_token')}
    ready=mpesa_configured()
    return render_template('admin_payment_settings.html',settings=settings,secret_state=secret_state,mpesa_ready=ready,callback_url=payment_callback_url())
