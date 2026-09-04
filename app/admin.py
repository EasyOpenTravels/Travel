import os, re, shutil, sqlite3, hmac, secrets
from datetime import datetime, timezone
from flask import Blueprint,current_app,render_template,request,redirect,url_for,session,flash,send_file,abort,g
from werkzeug.utils import secure_filename
from .db import get_db,SCHEMA
from .security import now
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
    }
    rows={r['key']:r['value'] for r in db.execute('SELECT key,value FROM settings').fetchall()}
    trips=db.execute('SELECT * FROM trips ORDER BY date').fetchall(); destinations=db.execute('SELECT * FROM destinations ORDER BY sort_order,id').fetchall(); posts=db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall()
    return render_template('admin_dashboard.html',stats=stats,settings=rows,trips=trips,destinations=destinations,posts=posts)

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

@admin_bp.post('/settings')
def settings():
    g=guard()
    if g:return g
    db=get_db()
    allowed=['promo_counter','promo_growth_daily','payment_paybill','payment_till','payment_name','contact_phone','contact_email','site_tagline']
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
    db=get_db(); db.execute('PRAGMA wal_checkpoint(FULL)'); db.commit(); path=current_app.config['DATABASE_PATH']; return send_file(path,as_attachment=True,download_name='open-road-adventures-backup.sqlite3',mimetype='application/x-sqlite3')

@admin_bp.post('/restore')
def restore():
    g=guard()
    if g:return g
    f=request.files.get('backup')
    if not f: flash('Choose a SQLite backup.','error'); return redirect(url_for('admin.dashboard'))
    temp=current_app.config['DATABASE_PATH']+'.restore'
    try:
        f.save(temp); conn=sqlite3.connect(temp); conn.execute('PRAGMA integrity_check'); conn.executescript(SCHEMA); conn.commit(); conn.close();
        conn=get_db(); conn.close(); g.pop('db', None); shutil.copy2(temp,current_app.config['DATABASE_PATH']); flash('Backup restored. Reload the dashboard.','success')
    except Exception as exc: flash('Restore rejected: '+str(exc),'error')
    finally:
        try:os.remove(temp)
        except OSError:pass
    return redirect(url_for('admin.dashboard'))
