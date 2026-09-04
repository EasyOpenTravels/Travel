import re, secrets, sqlite3
from datetime import datetime, timezone
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort, jsonify, send_from_directory
from .db import get_db
from .security import now, ticket_signature, verify_ticket, token, hash_pin, verify_pin, hash_answer, verify_answer
from .qr import make_qr_bytes

bp = Blueprint('public', __name__)

def slugify(text):
    s=re.sub(r'[^a-z0-9]+','-',text.lower()).strip('-')
    return s or token(5)

def setting(key, default=''):
    row=get_db().execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    return row['value'] if row else default

def promo_value():
    try: base=int(setting('promo_counter','3401')); growth=int(setting('promo_growth_daily','17'))
    except ValueError: return 3401
    # Public-facing marketing counter; real visitor counts remain admin-only.
    anchor=setting('promo_anchor', datetime.now(timezone.utc).date().isoformat())
    try: days=max(0,(datetime.now(timezone.utc).date()-datetime.fromisoformat(anchor).date()).days)
    except ValueError: days=0
    return base + days*growth

def log_visit():
    if request.path.startswith('/static/') or request.path.startswith('/media/') or request.path.startswith('/api/'):
        return
    key=request.cookies.get('visitor_key') or secrets.token_urlsafe(16)
    db=get_db(); db.execute('INSERT INTO visits(visitor_key,path,created_at) VALUES(?,?,?)',(key,request.path,now())); db.commit(); request._visitor_key=key

@bp.before_request
def before(): log_visit()

@bp.after_request
def visitor_cookie(response):
    key=getattr(request,'_visitor_key',None)
    if key and not request.cookies.get('visitor_key'):
        response.set_cookie('visitor_key',key,max_age=31536000,httponly=True,samesite='Lax',secure=request.is_secure)
    return response

@bp.get('/health')
def health(): return jsonify(ok=True, service='open-road-adventures')
@bp.route('/pulse_receiver',methods=['GET','POST'])
def pulse_receiver(): return jsonify(ok=True, received=True)

@bp.get('/')
def home():
    db=get_db()
    trips=list(db.execute("SELECT * FROM trips WHERE status='published' ORDER BY date").fetchall())
    destinations=list(db.execute('SELECT * FROM destinations WHERE active=1 ORDER BY sort_order,id').fetchall())
    posts=list(db.execute('SELECT * FROM posts WHERE published=1 ORDER BY id DESC').fetchall())
    # Small rotation keeps the public page feeling alive without changing admin data.
    day=datetime.now(timezone.utc).date().toordinal()
    if destinations:
        shift=day % len(destinations); destinations=(destinations[shift:]+destinations[:shift])[:12]
    else: destinations=[]
    if trips:
        shift=day % len(trips); trips=(trips[shift:]+trips[:shift])[:12]
    else: trips=[]
    posts=posts[:6]
    return render_template('home.html',trips=trips,destinations=destinations,posts=posts,promo=promo_value(),q='')

@bp.get('/search')
def search():
    q=request.args.get('q','').strip()
    db=get_db(); trips=[]; destinations=[]
    if q:
        like='%'+q+'%'
        trips=db.execute("SELECT * FROM trips WHERE status='published' AND (title LIKE ? OR destination LIKE ? OR description LIKE ?) ORDER BY date LIMIT 24",(like,like,like)).fetchall()
        destinations=db.execute("SELECT * FROM destinations WHERE active=1 AND (title LIKE ? OR subtitle LIKE ? OR vibe LIKE ?) ORDER BY sort_order,id LIMIT 24",(like,like,like)).fetchall()
    posts=db.execute("SELECT * FROM posts WHERE published=1 AND (title LIKE ? OR excerpt LIKE ? OR body LIKE ?) ORDER BY id DESC LIMIT 12",('%'+q+'%','%'+q+'%','%'+q+'%')).fetchall() if q else []
    return render_template('search.html',q=q,trips=trips,destinations=destinations,posts=posts,promo=promo_value())

@bp.get('/destination/<slug>')
def destination(slug):
    d=get_db().execute('SELECT * FROM destinations WHERE slug=? AND active=1',(slug,)).fetchone()
    if not d: abort(404)
    related=get_db().execute("SELECT * FROM trips WHERE status='published' AND destination LIKE ? ORDER BY date LIMIT 8",('%'+d['title'].split()[0]+'%',)).fetchall()
    return render_template('destination.html',destination=d,related=related)

@bp.get('/trip/<slug>')
def trip(slug):
    db=get_db(); t=db.execute("SELECT * FROM trips WHERE slug=? AND status IN ('published','completed')",(slug,)).fetchone()
    if not t: abort(404)
    sold=db.execute("SELECT COALESCE(SUM(quantity),0) n FROM bookings WHERE trip_id=? AND payment_status NOT IN ('cancelled')",(t['id'],)).fetchone()['n']
    unlocked=bool(session.get('user_id'))
    return render_template('trip.html',trip=t,sold=sold,unlocked=unlocked)

@bp.route('/book/<slug>',methods=['GET','POST'])
def book(slug):
    if not session.get('user_id'):
        session['next_url']=request.path
        return redirect(url_for('public.register', next=request.path))
    db=get_db(); t=db.execute("SELECT * FROM trips WHERE slug=? AND status='published'",(slug,)).fetchone()
    if not t: abort(404)
    sold=db.execute("SELECT COALESCE(SUM(quantity),0) n FROM bookings WHERE trip_id=? AND payment_status!='cancelled'",(t['id'],)).fetchone()['n']
    if request.method=='POST':
        user=db.execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL',(session['user_id'],)).fetchone()
        try: qty=min(10,max(1,int(request.form.get('quantity','1'))))
        except ValueError: qty=1
        method=request.form.get('payment_method','M-Pesa')
        db.execute('BEGIN IMMEDIATE')
        try:
            sold=db.execute("SELECT COALESCE(SUM(quantity),0) n FROM bookings WHERE trip_id=? AND payment_status!='cancelled'",(t['id'],)).fetchone()['n']
            if sold+qty>t['capacity']:
                db.rollback(); flash('Those seats just disappeared. Try a smaller group or another adventure.','error'); return render_template('book.html',trip=t,sold=sold)
            ref='ADV-'+secrets.token_hex(5).upper()
            cur=db.execute('INSERT INTO bookings(trip_id,user_id,name,phone,email,quantity,total,ref,payment_status,payment_method,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(t['id'],user['id'],user['name'],user['phone'],user['email'],qty,t['price']*qty,ref,'awaiting_payment',method,now()))
            bid=cur.lastrowid
            for i in range(qty):
                code='TK-'+secrets.token_hex(9).upper()
                db.execute('INSERT INTO tickets(booking_id,passenger_name,ticket_code,signature,seat,created_at) VALUES(?,?,?,?,?,?)',(bid,user['name'],code,ticket_signature(code),str(sold+i+1),now()))
            db.commit()
        except Exception:
            db.rollback(); raise
        return redirect(url_for('public.booking',ref=ref))
    return render_template('book.html',trip=t,sold=sold)

@bp.get('/booking/<ref>')
def booking(ref):
    db=get_db(); b=db.execute('SELECT b.*,t.title,t.destination,t.date,t.pickup,t.cover_image FROM bookings b JOIN trips t ON t.id=b.trip_id WHERE b.ref=?',(ref,)).fetchone()
    if not b: abort(404)
    if session.get('user_id') != b['user_id']: return redirect(url_for('public.login', next=url_for('public.booking',ref=ref)))
    tickets=db.execute('SELECT * FROM tickets WHERE booking_id=?',(b['id'],)).fetchall()
    return render_template('booking.html',booking=b,tickets=tickets,paybill=setting('payment_paybill'),till=setting('payment_till'),payname=setting('payment_name','Open Road Adventures'))

@bp.post('/booking/<ref>/payment')
def payment_reference(ref):
    db=get_db(); b=db.execute('SELECT * FROM bookings WHERE ref=?',(ref,)).fetchone()
    if not b or session.get('user_id') != b['user_id']: abort(403)
    reference=request.form.get('payment_reference','').strip()
    method=request.form.get('payment_method','M-Pesa').strip()
    if len(reference)<3: flash('Add your payment reference so the Adventure Team can match it.','error')
    else:
        db.execute("UPDATE bookings SET payment_status='payment_submitted',payment_reference=?,payment_method=? WHERE id=? AND payment_status='awaiting_payment'",(reference,method,b['id'])); db.commit(); flash('Payment reference received. Your place is reserved while we confirm it.','success')
    return redirect(url_for('public.booking',ref=ref))

@bp.get('/ticket/<code>')
def ticket(code):
    row=get_db().execute('SELECT tk.*,b.ref,b.payment_status,t.title,t.destination,t.date,t.pickup FROM tickets tk JOIN bookings b ON b.id=tk.booking_id JOIN trips t ON t.id=b.trip_id WHERE tk.ticket_code=?',(code,)).fetchone()
    if not row: abort(404)
    if session.get('user_id') is None: return redirect(url_for('public.login'))
    data=url_for('public.scan_ticket',code=code,sig=row['signature'],_external=True)
    return render_template('ticket.html',ticket=row,qr=make_qr_bytes(data))

@bp.get('/scan/<code>')
def scan_ticket(code):
    sig=request.args.get('sig',''); db=get_db()
    if not verify_ticket(code,sig): return render_template('scan_result.html',valid=False,reason='This QR signature is not valid.')
    db.execute('BEGIN IMMEDIATE')
    row=db.execute('SELECT tk.*,b.ref,b.payment_status,t.title,t.destination,t.date,t.pickup FROM tickets tk JOIN bookings b ON b.id=tk.booking_id JOIN trips t ON t.id=b.trip_id WHERE tk.ticket_code=?',(code,)).fetchone()
    if not row: db.rollback(); return render_template('scan_result.html',valid=False,reason='Ticket not found.')
    if row['payment_status'] not in ('paid','confirmed'):
        db.rollback(); return render_template('scan_result.html',valid=False,reason='Payment is not confirmed yet.',ticket=row)
    if row['status']!='valid':
        db.rollback(); return render_template('scan_result.html',valid=False,reason='This ticket has already been used.',ticket=row)
    cur=db.execute("UPDATE tickets SET status='used',checked_in_at=? WHERE id=? AND status='valid'",(now(),row['id'])); db.commit()
    if cur.rowcount != 1: return render_template('scan_result.html',valid=False,reason='This ticket was just redeemed elsewhere.',ticket=row)
    return render_template('scan_result.html',valid=True,ticket=row)

@bp.get('/media/<path:filename>')
def media(filename): return send_from_directory(current_app.config['UPLOAD_FOLDER'],filename)

@bp.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        name=request.form.get('name','').strip(); email=request.form.get('email','').strip().lower(); phone=request.form.get('phone','').strip(); pin=request.form.get('pin','').strip(); question=request.form.get('question','').strip(); answer=request.form.get('answer','').strip()
        if not name or not email or not phone or not pin.isdigit() or not 4<=len(pin)<=8 or len(question)<3 or len(answer)<2:
            flash('Keep it easy: name, phone, email, a 4–8 digit PIN and a recovery answer.','error'); return render_template('register.html')
        try:
            db=get_db(); cur=db.execute('INSERT INTO users(name,phone,email,pin_hash,recovery_question,recovery_answer_hash,created_at) VALUES(?,?,?,?,?,?,?)',(name,phone,email,hash_pin(pin),question,hash_answer(answer),now())); db.commit(); session.permanent=True; session['user_id']=cur.lastrowid
        except sqlite3.IntegrityError:
            flash('That email is already registered. Sign in and keep moving.','error'); return render_template('register.html')
        return redirect(session.pop('next_url',None) or url_for('public.account'))
    return render_template('register.html')

@bp.route('/login',methods=['GET','POST'])
def login():
    nxt=request.args.get('next') or request.form.get('next') or session.get('next_url')
    if request.method=='POST':
        identity=request.form.get('identity','').strip().lower(); pin=request.form.get('pin','').strip(); u=get_db().execute('SELECT * FROM users WHERE (lower(email)=? OR phone=?) AND deleted_at IS NULL',(identity,identity)).fetchone()
        if u and verify_pin(u['pin_hash'],pin): session.permanent=True; session['user_id']=u['id']; return redirect(nxt or url_for('public.account'))
        flash('That PIN did not unlock your adventure account.','error')
    return render_template('login.html',next=nxt)

@bp.get('/recover')
def recover(): return render_template('recover.html')
@bp.post('/recover')
def recover_post():
    identity=request.form.get('identity','').strip().lower(); answer=request.form.get('answer','')
    u=get_db().execute('SELECT * FROM users WHERE (lower(email)=? OR phone=?) AND deleted_at IS NULL',(identity,identity)).fetchone()
    if u and verify_answer(u['recovery_answer_hash'],answer): session['recovery_user_id']=u['id']; return redirect(url_for('public.reset_pin'))
    flash('We could not verify that answer.','error'); return redirect(url_for('public.recover'))
@bp.post('/recover/question')
def recovery_question():
    identity=request.form.get('identity','').strip().lower(); u=get_db().execute('SELECT recovery_question FROM users WHERE (lower(email)=? OR phone=?) AND deleted_at IS NULL',(identity,identity)).fetchone()
    return jsonify(ok=bool(u),question=u['recovery_question'] if u else '')
@bp.route('/reset-pin',methods=['GET','POST'])
def reset_pin():
    uid=session.get('recovery_user_id')
    if not uid: return redirect(url_for('public.login'))
    if request.method=='POST':
        pin=request.form.get('pin','').strip()
        if not pin.isdigit() or not 4<=len(pin)<=8: flash('Use 4–8 digits.','error')
        else:
            db=get_db(); db.execute('UPDATE users SET pin_hash=? WHERE id=?',(hash_pin(pin),uid)); db.commit(); session.pop('recovery_user_id',None); session.permanent=True; session['user_id']=uid; return redirect(url_for('public.account'))
    return render_template('reset_pin.html')

@bp.get('/logout')
def logout(): session.clear(); return redirect(url_for('public.home'))

@bp.route('/account',methods=['GET','POST'])
def account():
    if not session.get('user_id'): return redirect(url_for('public.login'))
    db=get_db(); u=db.execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL',(session['user_id'],)).fetchone()
    if not u: session.clear(); return redirect(url_for('public.login'))
    if request.method=='POST' and request.form.get('action')=='delete':
        db.execute("UPDATE users SET deleted_at=?,remember_token=NULL WHERE id=?",(now(),u['id'])); db.commit(); session.clear(); flash('Your Adventure ID was removed.','success'); return redirect(url_for('public.home'))
    bookings=db.execute('SELECT b.*,t.title,t.date,t.destination,t.cover_image FROM bookings b JOIN trips t ON t.id=b.trip_id WHERE b.user_id=? ORDER BY b.id DESC',(u['id'],)).fetchall()
    suggestions=db.execute("SELECT * FROM trips WHERE status='published' ORDER BY date LIMIT 6").fetchall()
    posts=db.execute('SELECT * FROM posts WHERE published=1 ORDER BY id DESC LIMIT 5').fetchall()
    return render_template('account.html',user=u,bookings=bookings,suggestions=suggestions,posts=posts)

@bp.route('/contact',methods=['GET','POST'])
def contact():
    if request.method=='POST':
        db=get_db(); db.execute('INSERT INTO messages(user_id,name,email,phone,body,created_at) VALUES(?,?,?,?,?,?)',(session.get('user_id'),request.form.get('name','').strip(),request.form.get('email','').strip().lower(),request.form.get('phone','').strip(),request.form.get('body','').strip(),now())); db.commit(); flash('Sent. The Adventure Team will get back to you.','success'); return redirect(url_for('public.contact'))
    return render_template('contact.html')

@bp.route('/vote/<int:trip_id>',methods=['GET','POST'])
def vote(trip_id):
    db=get_db(); t=db.execute('SELECT * FROM trips WHERE id=?',(trip_id,)).fetchone()
    if not t: abort(404)
    if request.method=='POST':
        key=str(session.get('user_id') or request.cookies.get('visitor_key') or secrets.token_urlsafe(8)); rating=max(1,min(5,int(request.form.get('rating','5')))); choice=request.form.get('choice','Yes')
        try: db.execute('INSERT INTO votes(trip_id,voter_key,rating,choice,comment,created_at) VALUES(?,?,?,?,?,?)',(trip_id,key,rating,choice,request.form.get('comment','').strip(),now())); db.commit(); flash('Vote saved.','success')
        except sqlite3.IntegrityError: flash('One vote per adventure is enough.','error')
    stats=db.execute('SELECT COUNT(*) n,ROUND(AVG(rating),1) avg FROM votes WHERE trip_id=?',(trip_id,)).fetchone(); return render_template('vote.html',trip=t,stats=stats)

@bp.get('/post/<int:post_id>')
def post(post_id):
    p=get_db().execute('SELECT * FROM posts WHERE id=? AND published=1',(post_id,)).fetchone()
    if not p: abort(404)
    return render_template('post.html',post=p)


@bp.get('/join')
def join():
    target=url_for('public.home', _external=True)
    qr=make_qr_bytes(target)
    return render_template('join.html', target=target, qr=qr)

@bp.get('/manifest.json')
def manifest():
    return jsonify(name=current_app.config['BRAND_NAME'],short_name='Open Road',start_url='/',display='standalone',theme_color='#12212b',background_color='#fbf6ea',icons=[{'src':url_for('static',filename='icon.svg'),'sizes':'any','type':'image/svg+xml','purpose':'any maskable'}])
