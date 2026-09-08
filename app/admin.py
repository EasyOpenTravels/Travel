import os, re, shutil, sqlite3, hmac, secrets, zipfile, pathlib
from datetime import datetime, timezone
from flask import Blueprint,current_app,render_template,request,redirect,url_for,session,flash,send_file,abort,g
from werkzeug.utils import secure_filename
from .db import get_db,SCHEMA
from .security import now, encrypt_secret, decrypt_secret
from .qr import make_qr_bytes
from .payments import payment_callback_url
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
    }
    rows={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings').fetchall()}
    trips=db.execute('SELECT * FROM trips ORDER BY date').fetchall(); destinations=db.execute('SELECT * FROM destinations ORDER BY sort_order,id').fetchall(); posts=db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall(); services=db.execute('SELECT * FROM services ORDER BY sort_order,id').fetchall(); service_requests=db.execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id ORDER BY sr.id DESC LIMIT 12').fetchall()
    return render_template('admin_dashboard.html',stats=stats,settings=rows,trips=trips,destinations=destinations,posts=posts,services=services,service_requests=service_requests)

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

@admin_bp.route('/payment-settings', methods=['GET','POST'])
def payment_settings():
    gate=guard()
    if gate:return gate
    db=get_db()
    secret_fields=['mpesa_consumer_key','mpesa_consumer_secret','mpesa_passkey','mpesa_callback_token']
    if request.method=='POST':
        section=request.form.get('section','collection')
        if section=='credentials':
            for key in secret_fields:
                raw=request.form.get(key,'').strip()
                if raw:
                    db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(key,encrypt_secret(raw)))
            db.commit(); flash('Daraja connection saved securely.','success')
        elif section=='collection':
            for key in ['payment_till','payment_paybill','payment_name','payment_business_shortcode','payment_transaction_type','payment_currency']:
                db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(key,request.form.get(key,'').strip()))
            try: fee=max(0.0,min(100.0,float(request.form.get('ticketing_fee_percent','5') or 0)))
            except ValueError: fee=5.0
            db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',('ticketing_fee_percent',str(fee)))
            db.commit(); flash('Collection settings saved.','success')
        else:
            abort(400)
        return redirect(url_for('admin.payment_settings'))
    vals={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings').fetchall()}
    states={k:bool(decrypt_secret(vals.get(k,''))) for k in secret_fields}
    from .payments import mpesa_configured
    return render_template('admin_payment_settings.html',settings=vals,secret_state=states,mpesa_ready=mpesa_configured(),callback_url=payment_callback_url())

@admin_bp.post('/settings')
def settings():
    g=guard()
    if g:return g
    db=get_db()
    allowed=['promo_counter','promo_growth_daily','payment_paybill','payment_till','payment_name','ticketing_fee_percent','contact_phone','contact_email','site_tagline']
    for key in allowed:
        value=request.form.get(key,'').strip()
        if key in ('promo_counter','promo_growth_daily'):
            try:value=str(max(0,int(value)))
            except ValueError:value='0'
        if key == 'ticketing_fee_percent':
            try: value=str(max(0.0,min(100.0,float(value or 0))))
            except ValueError: value='5'
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


@admin_bp.get('/group-retreats')
def group_retreats_admin():
    g=guard()
    if g:return g
    db=get_db(); groups=db.execute("SELECT g.*,COUNT(m.id) member_count,SUM(CASE WHEN m.payment_status='submitted' THEN 1 ELSE 0 END) submitted_count,SUM(CASE WHEN m.payment_status='approved' THEN 1 ELSE 0 END) approved_count FROM group_retreats g LEFT JOIN group_members m ON m.retreat_id=g.id GROUP BY g.id ORDER BY g.id DESC").fetchall()
    members=db.execute('SELECT * FROM group_members ORDER BY retreat_id,id').fetchall()
    g_member_rows={}
    for m in members: g_member_rows.setdefault(m['retreat_id'],[]).append(m)
    return render_template('admin_group_retreats.html',groups=groups,g_member_rows=g_member_rows)

@admin_bp.post('/group-retreats/<int:group_id>/status')
def group_retreat_status(group_id):
    g=guard()
    if g:return g
    status=request.form.get('status','pending')
    if status not in {'pending','approved','active','completed','cancelled'}: abort(400)
    try: agreed=max(0,int(request.form.get('agreed_price','0') or 0))
    except ValueError: agreed=0
    db=get_db(); db.execute('UPDATE group_retreats SET status=?,agreed_price=?,approved_at=? WHERE id=?',(status,agreed,now() if status=='approved' else None,group_id)); db.commit(); flash('Group retreat updated.','success'); return redirect(url_for('admin.group_retreats_admin'))

@admin_bp.post('/group-retreats/<int:group_id>/member/<int:member_id>/payment')
def group_member_payment_admin(group_id,member_id):
    g=guard()
    if g:return g
    status=request.form.get('status','pending')
    if status not in {'pending','approved','rejected'}: abort(400)
    db=get_db(); db.execute('UPDATE group_members SET payment_status=? WHERE id=? AND retreat_id=?',(status,member_id,group_id)); db.commit(); flash('Member payment updated.','success'); return redirect(url_for('admin.group_retreats_admin'))

@admin_bp.post('/group-retreats/<int:group_id>/delete')
def group_retreat_delete(group_id):
    g=guard()
    if g:return g
    db=get_db(); db.execute('DELETE FROM group_members WHERE retreat_id=?',(group_id,)); db.execute('DELETE FROM group_retreats WHERE id=?',(group_id,)); db.commit(); flash('Group retreat deleted.','success'); return redirect(url_for('admin.group_retreats_admin'))

@admin_bp.get('/payments')
def payments():
    g=guard()
    if g:return g
    rows=get_db().execute('SELECT * FROM payment_intents ORDER BY id DESC LIMIT 250').fetchall()
    return render_template('admin_payments.html',payments=rows,mpesa_ready=bool(os.environ.get('MPESA_CONSUMER_KEY') and os.environ.get('MPESA_CONSUMER_SECRET') and os.environ.get('MPESA_PASSKEY') and os.environ.get('MPESA_CALLBACK_TOKEN') and get_db().execute("SELECT value FROM settings WHERE key='payment_till'").fetchone() and get_db().execute("SELECT value FROM settings WHERE key='payment_till'").fetchone()['value']),callback_url=payment_callback_url())

@admin_bp.post('/event-ticketing/<int:event_id>/ticket/<int:ticket_id>/reverse')
def admin_event_ticket_reverse(event_id,ticket_id):
    g=guard()
    if g:return g
    db=get_db()
    row=db.execute('SELECT * FROM event_tickets WHERE id=? AND event_id=?',(ticket_id,event_id)).fetchone()
    if not row: abort(404)
    db.execute("UPDATE event_tickets SET approval_status='reversed' WHERE id=? AND event_id=?",(ticket_id,event_id))
    db.commit(); flash('Ticket decision reversed. The payment record remains preserved.','success'); return redirect(url_for('admin.event_ticketing'))

@admin_bp.post('/event-ticketing/<int:event_id>/ticket/<int:ticket_id>/restore')
def admin_event_ticket_restore(event_id,ticket_id):
    g=guard()
    if g:return g
    db=get_db(); row=db.execute("SELECT t.*,p.status payment_tx_status FROM event_tickets t LEFT JOIN payment_intents p ON p.kind='event_ticket' AND p.target_id=t.id AND p.status='paid' WHERE t.id=? AND t.event_id=? ORDER BY p.id DESC LIMIT 1",(ticket_id,event_id)).fetchone()
    if not row: abort(404)
    if row['payment_tx_status']=='paid':
        db.execute("UPDATE event_tickets SET approval_status='approved',payment_status='verified',ticket_status=CASE WHEN ticket_status='void' THEN 'valid' ELSE ticket_status END,approved_at=? WHERE id=? AND event_id=?",(now(),ticket_id,event_id)); db.commit(); flash('Confirmed paid ticket restored.','success')
    else:
        flash('Ticket cannot be restored until a confirmed payment exists.','error')
    return redirect(url_for('admin.event_ticketing'))

@admin_bp.post('/group-retreats/<int:group_id>/reverse')
def admin_group_reverse(group_id):
    g=guard()
    if g:return g
    db=get_db(); row=db.execute('SELECT id FROM group_retreats WHERE id=?',(group_id,)).fetchone()
    if not row: abort(404)
    db.execute("UPDATE group_retreats SET status='pending',approved_at=NULL WHERE id=?",(group_id,)); db.commit(); flash('Group retreat decision reversed and reopened.','success'); return redirect(url_for('admin.group_retreats_admin'))

@admin_bp.get('/event-ticketing')
def event_ticketing():
    g=guard()
    if g:return g
    db=get_db()
    events=db.execute(
        "SELECT e.*,u.name owner_name,COUNT(t.id) ticket_count,"
        "SUM(CASE WHEN t.approval_status='pending' THEN 1 ELSE 0 END) pending_count "
        "FROM event_ticket_events e JOIN users u ON u.id=e.owner_user_id "
        "LEFT JOIN event_tickets t ON t.event_id=e.id "
        "GROUP BY e.id ORDER BY e.id DESC"
    ).fetchall()
    tickets=db.execute("SELECT t.*,e.title event_title FROM event_tickets t JOIN event_ticket_events e ON e.id=t.event_id ORDER BY t.id DESC LIMIT 300").fetchall()
    return render_template('admin_event_ticketing.html',events=events,tickets=tickets)

@admin_bp.post('/event-ticketing/<int:event_id>/approve/<int:ticket_id>')
def admin_event_ticket_approve(event_id,ticket_id):
    g=guard()
    if g:return g
    db=get_db()
    db.execute(
        "UPDATE event_tickets SET approval_status='approved',payment_status='verified',approved_at=? "
        "WHERE id=? AND event_id=? AND approval_status='pending'",
        (now(),ticket_id,event_id)
    )
    db.commit()
    flash('Event ticket approved.','success')
    return redirect(url_for('admin.event_ticketing'))

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

@admin_bp.get('/backup')
def backup():
    g=guard()
    if g:return g
    db=get_db(); db.execute('PRAGMA wal_checkpoint(FULL)'); db.commit()
    db_path=current_app.config['DATABASE_PATH']; upload=current_app.config['UPLOAD_FOLDER']; buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(db_path,'database/adventures.sqlite3')
        if os.path.isdir(upload):
            for path in pathlib.Path(upload).rglob('*'):
                if path.is_file(): z.write(path,'uploads/'+path.relative_to(upload).as_posix())
    buf.seek(0); return send_file(buf,as_attachment=True,download_name='travel-full-backup.zip',mimetype='application/zip')

@admin_bp.post('/restore')
def restore():
    g=guard()
    if g:return g
    f=request.files.get('backup')
    if not f: flash('Choose a full .zip backup from this system.','error'); return redirect(url_for('admin.dashboard'))
    temp_dir=os.path.join(current_app.instance_path,'restore_tmp_'+secrets.token_hex(4)); os.makedirs(temp_dir,exist_ok=True); temp_zip=os.path.join(temp_dir,'backup.zip')
    try:
        f.save(temp_zip)
        with zipfile.ZipFile(temp_zip) as z:
            names=z.namelist()
            if 'database/adventures.sqlite3' not in names: raise ValueError('The backup does not contain the system database.')
            for name in names:
                p=pathlib.PurePosixPath(name)
                if p.is_absolute() or '..' in p.parts: raise ValueError('Unsafe backup path.')
            z.extractall(temp_dir)
        restored=os.path.join(temp_dir,'database','adventures.sqlite3'); test=sqlite3.connect(restored); result=test.execute('PRAGMA integrity_check').fetchone()[0]; test.executescript(SCHEMA); test.commit(); test.close()
        if result!='ok': raise ValueError('Database integrity check failed.')
        conn=get_db(); conn.close(); g.pop('db',None); shutil.copy2(restored,current_app.config['DATABASE_PATH'])
        restore_upload=os.path.join(temp_dir,'uploads')
        if os.path.isdir(restore_upload):
            shutil.rmtree(current_app.config['UPLOAD_FOLDER'],ignore_errors=True)
            os.makedirs(current_app.config['UPLOAD_FOLDER'],exist_ok=True)
            for path in pathlib.Path(restore_upload).rglob('*'):
                if path.is_file():
                    dest=pathlib.Path(current_app.config['UPLOAD_FOLDER'])/path.relative_to(restore_upload); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,dest)
        flash('Full backup restored successfully.','success')
    except Exception as exc: flash('Restore rejected: '+str(exc),'error')
    finally: shutil.rmtree(temp_dir,ignore_errors=True)
    return redirect(url_for('admin.dashboard'))

