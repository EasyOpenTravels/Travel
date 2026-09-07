import re, secrets, sqlite3, os
from datetime import datetime, timezone
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort, jsonify, send_from_directory, send_file
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
    db=get_db(); trips=[]; destinations=[]; services=[]
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


# ---------------------------------------------------------------------------
# EVENT TICKETING
# Deliberately separate from ordinary Travel Tickets.
def event_ticket_owner(event):
    return bool(session.get('user_id')) and session.get('user_id') == event['owner_user_id']

def event_ticket_signature(code):
    return ticket_signature(code)

def event_public_slug(db, title, exclude_event_id=None):
    base = slugify(title)
    return base + '-' + secrets.token_hex(3)

def event_image_upload():
    f = request.files.get('cover_image')
    if not f or not f.filename:
        return ''
    from werkzeug.utils import secure_filename
    fn = secure_filename(f.filename)
    ext = fn.rsplit('.', 1)[-1].lower() if '.' in fn else ''
    if ext not in {'jpg','jpeg','png','webp','gif'}:
        return ''
    fn = f"event-{secrets.token_hex(5)}.{ext}"
    os.makedirs(current_app.config['UPLOAD_FOLDER'], exist_ok=True)
    f.save(os.path.join(current_app.config['UPLOAD_FOLDER'], fn))
    return '/media/' + fn

def _tier_for_amount(event, amount, requested='auto'):
    mapping = [
        ('regular', int(event['regular_price'] or 0)),
        ('vip', int(event['vip_price'] or 0)),
        ('vvip', int(event['vvip_price'] or 0)),
    ]
    requested=(requested or 'auto').lower()
    if requested in {'regular','vip','vvip'}:
        return requested
    for tier, price in mapping:
        if price and amount == price:
            return tier
    return 'regular'

def _new_ticket_code():
    return 'EVT-' + secrets.token_hex(7).upper()

def _make_event_ticket(db, event, *, name, gender, amount, mpesa_code='', tier='auto', source='visitor'):
    code=_new_ticket_code(); signature=event_ticket_signature(code); access=secrets.token_urlsafe(28)
    chosen=_tier_for_amount(event, amount, tier)
    status='approved' if source=='host' else 'pending'
    payment_status='verified' if source=='host' else 'submitted'
    db.execute(
        """INSERT INTO event_tickets\n        (event_id,attendee_user_id,attendee_name,attendee_gender,ticket_code,signature,payment_method,payment_reference,amount,ticket_tier,source,access_token,payment_status,approval_status,ticket_status,created_at)\n        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event['id'], session.get('user_id') if source=='visitor' and session.get('user_id') else None,
         name,gender,code,signature,'M-Pesa',mpesa_code,amount,chosen,source,access,payment_status,status,'valid',now())
    )
    return code, access

def _event_ticket_row_by_access(access_token):
    return get_db().execute(
        """SELECT t.*,e.title event_title,e.slug event_slug,e.event_date,e.event_time,e.venue,e.cover_image,e.ticket_note,e.owner_user_id,
                  e.currency,e.regular_price,e.vip_price,e.vvip_price,e.active
           FROM event_tickets t JOIN event_ticket_events e ON e.id=t.event_id
           WHERE t.access_token=?""", (access_token,)
    ).fetchone()

def _event_qr_url(row):
    return url_for('public.event_scan', ticket_code=row['ticket_code'], sig=row['signature'], _external=True)

@bp.get('/ticketing')
def ticketing_home():
    db=get_db(); my_events=[]
    if session.get('user_id'):
        my_events=db.execute(
            """SELECT e.*,COUNT(t.id) ticket_count,
                      SUM(CASE WHEN t.approval_status='pending' THEN 1 ELSE 0 END) pending_count,
                      SUM(CASE WHEN t.approval_status='approved' AND t.ticket_status='valid' THEN 1 ELSE 0 END) active_count,
                      SUM(CASE WHEN t.ticket_status='used' THEN 1 ELSE 0 END) used_count
               FROM event_ticket_events e LEFT JOIN event_tickets t ON t.event_id=e.id
               WHERE e.owner_user_id=? AND e.active=1 GROUP BY e.id ORDER BY e.id DESC""",(session['user_id'],)
        ).fetchall()
    return render_template('ticketing_home.html',my_events=my_events)

@bp.route('/ticketing/host',methods=['GET','POST'])
def ticketing_host():
    if not session.get('user_id'):
        session['next_url']=url_for('public.ticketing_host')
        return redirect(url_for('public.register',next=url_for('public.ticketing_host')))
    if request.method=='POST':
        title=request.form.get('title','').strip()
        if not title:
            flash('Give your event a name first.','error'); return render_template('ticketing_host.html')
        try:
            regular=max(0,int(request.form.get('regular_price','0') or 0)); vip=max(0,int(request.form.get('vip_price','0') or 0)); vvip=max(0,int(request.form.get('vvip_price','0') or 0))
        except ValueError: regular=vip=vvip=0
        pin=request.form.get('scanners_pin','').strip()
        if not pin.isdigit() or not 4<=len(pin)<=8:
            flash('Scanner PIN must be 4–8 digits.','error'); return render_template('ticketing_host.html')
        db=get_db(); cover=event_image_upload(); slug=event_public_slug(db,title); scanner_code='SCN-'+secrets.token_hex(4).upper()
        cur=db.execute(
            """INSERT INTO event_ticket_events
            (owner_user_id,slug,title,description,event_date,event_time,venue,price,currency,payment_instructions,cover_image,ticket_note,regular_price,vip_price,vvip_price,scanner_code,scanners_pin_hash,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session['user_id'],slug,title,request.form.get('description','').strip(),request.form.get('event_date','').strip(),request.form.get('event_time','').strip(),request.form.get('venue','').strip(),regular,request.form.get('currency','KES').strip().upper()[:6] or 'KES',request.form.get('payment_instructions','').strip(),cover,request.form.get('ticket_note','').strip(),regular,vip,vvip,scanner_code,hash_pin(pin),now())
        ); db.commit()
        flash('Event created. You now have a private host desk for it.','success')
        return redirect(url_for('public.event_manage',event_id=cur.lastrowid))
    return render_template('ticketing_host.html')

@bp.get('/ticketing/event/<slug>')
def event_public(slug):
    event=get_db().execute('SELECT * FROM event_ticket_events WHERE slug=? AND active=1',(slug,)).fetchone()
    if not event: abort(404)
    return render_template('event_public.html',event=event)

@bp.post('/ticketing/event/<slug>/request')
def event_request_ticket(slug):
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE slug=? AND active=1',(slug,)).fetchone()
    if not event: abort(404)
    name=request.form.get('name','').strip(); gender=request.form.get('gender','').strip().lower(); raw=request.form.get('amount','').strip()
    if not name or gender not in {'male','female'}:
        flash('Enter the visitor name and choose male or female.','error'); return redirect(url_for('public.event_public',slug=slug))
    try: amount=max(0,int(raw))
    except ValueError:
        flash('Enter the amount paid.','error'); return redirect(url_for('public.event_public',slug=slug))
    code,access=_make_event_ticket(db,event,name=name,gender=gender,amount=amount,source='visitor')
    db.commit(); flash('Your request is submitted. Keep the ticket link on this device; it will unlock after approval.','success')
    return redirect(url_for('public.event_ticket_access',access_token=access))

@bp.post('/ticketing/event/<int:event_id>/add-attendee')
def event_add_attendee(event_id):
    if not session.get('user_id') and not session.get('admin_auth'):
        return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not session.get('admin_auth') and not event_ticket_owner(event): abort(403)
    name=request.form.get('name','').strip(); gender=request.form.get('gender','').strip().lower(); mpesa=request.form.get('mpesa_code','').strip(); tier=request.form.get('ticket_tier','auto').lower()
    try: amount=max(0,int(request.form.get('amount','0') or 0))
    except ValueError: amount=0
    if not name or gender not in {'male','female'} or len(mpesa)<3:
        flash('Add name, gender, amount and the M-Pesa code.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    _make_event_ticket(db,event,name=name,gender=gender,amount=amount,mpesa_code=mpesa,tier=tier,source='host'); db.commit()
    flash('Ticket generated and added to the event list.','success'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.get('/ticketing/ticket/<ticket_code>')
def event_ticket_view(ticket_code):
    row=get_db().execute("SELECT access_token FROM event_tickets WHERE ticket_code=?",(ticket_code,)).fetchone()
    if not row: abort(404)
    return redirect(url_for('public.event_ticket_access',access_token=row['access_token']))

@bp.get('/ticketing/my-ticket/<access_token>')
def event_ticket_access(access_token):
    row=_event_ticket_row_by_access(access_token)
    if not row: abort(404)
    qrdata=_event_qr_url(row) if row['approval_status']=='approved' and row['ticket_status']!='void' else ''
    qr=make_qr_bytes(qrdata) if qrdata else b''
    return render_template('event_ticket.html',ticket=row,qr=qr,access_token=access_token)

@bp.get('/ticketing/my-ticket/<access_token>/download')
def event_ticket_download(access_token):
    row=_event_ticket_row_by_access(access_token)
    if not row: abort(404)
    if row['approval_status']!='approved' or row['ticket_status']=='void':
        return redirect(url_for('public.event_ticket_access',access_token=access_token))
    from io import BytesIO
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    import base64
    buf=BytesIO(); W,H=A4; c=canvas.Canvas(buf,pagesize=A4)
    design=request.args.get('design','classic')
    bg={'classic':('#fbf6ea','#12212b'),'bold':('#d8f36a','#12212b'),'split':('#77e1d2','#12212b')}.get(design,('#fbf6ea','#12212b'))
    c.setFillColor(bg[0]); c.roundRect(14*mm,25*mm,W-28*mm,H-50*mm,10*mm,fill=1,stroke=0)
    c.setFillColor(bg[1]); c.setFont('Helvetica-Bold',9); c.drawString(20*mm,H-39*mm,'EVENT TICKET')
    c.setFont('Helvetica-Bold',25); c.drawString(20*mm,H-58*mm,(row['event_title'] or '')[:36])
    y=H-82*mm
    for label,val in [('NAME',row['attendee_name']),('GENDER',row['attendee_gender'].title()),('TICKET',row['ticket_tier'].upper()),('CODE',row['ticket_code']),('DATE',f"{row['event_date'] or '—'} {row['event_time'] or ''}".strip()),('VENUE',row['venue'] or '—')]:
        c.setFont('Helvetica-Bold',7); c.drawString(20*mm,y,label); y-=5*mm; c.setFont('Helvetica',12); c.drawString(20*mm,y,str(val)[:44]); y-=12*mm
    qrbytes=make_qr_bytes(_event_qr_url(row)); tmp=BytesIO(qrbytes); c.drawImage(ImageReader(tmp),W-74*mm,29*mm,width=52*mm,height=52*mm,mask='auto')
    c.setFillColor(bg[1]); c.setFont('Helvetica-Bold',7); c.drawString(20*mm,31*mm,'SCAN ONCE · SERVER VERIFIED · QR EXPIRES AFTER ENTRY')
    c.showPage(); c.save(); buf.seek(0)
    safe_title=re.sub(r'[^A-Za-z0-9_-]','-',row['event_title']); return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f"{safe_title}-{row['ticket_code']}.pdf")

@bp.get('/ticketing/api/events')
def ticketing_events_api():
    q=request.args.get('q','').strip(); db=get_db(); events=db.execute('SELECT id,slug,title,description,event_date,event_time,venue,cover_image FROM event_ticket_events WHERE active=1 ORDER BY id DESC LIMIT 120').fetchall()
    from difflib import SequenceMatcher
    ranked=[]
    for e in events:
        title=(e['title'] or '').lower(); query=q.lower(); score=.5 if not query else SequenceMatcher(None,query,title).ratio()
        if query and query in title: score=.99
        if query and any(term in title for term in re.findall(r"[\w']+",query)): score=max(score,.83)
        if score>=.4: ranked.append((score,e))
    ranked.sort(key=lambda x:(x[0],x[1]['id']),reverse=True); return jsonify([{**dict(e),'score':round(score,3)} for score,e in ranked[:12]])

@bp.get('/ticketing/find')
def ticketing_find():
    q=request.args.get('q','').strip(); db=get_db(); events=db.execute('SELECT id,slug,title,description,event_date,event_time,venue,cover_image FROM event_ticket_events WHERE active=1 ORDER BY id DESC').fetchall()
    if q:
        from difflib import SequenceMatcher
        ranked=[]
        for e in events:
            title=(e['title'] or '').lower(); score=SequenceMatcher(None,q.lower(),title).ratio()
            if q.lower() in title: score=.99
            if any(term in title for term in re.findall(r"[\w']+",q.lower())): score=max(score,.83)
            if score>=.4: ranked.append((score,e))
        ranked.sort(key=lambda x:(x[0],x[1]['id']),reverse=True); events=[e for _,e in ranked[:30]]
    else: events=list(events[:30])
    return render_template('ticketing_find.html',events=events,q=q)

@bp.post('/ticketing/event/<int:event_id>/edit')
def event_edit(event_id):
    if not session.get('user_id') and not session.get('admin_auth'): return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not event_ticket_owner(event) and not session.get('admin_auth'): abort(403)
    title=request.form.get('title','').strip()
    if not title: flash('Your event needs a name.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    try: regular=max(0,int(request.form.get('regular_price','0') or 0)); vip=max(0,int(request.form.get('vip_price','0') or 0)); vvip=max(0,int(request.form.get('vvip_price','0') or 0))
    except ValueError: regular=vip=vvip=0
    cover=event_image_upload() or event['cover_image']; slug=event['slug'] if title.lower()==event['title'].lower() else event_public_slug(db,title)
    db.execute("""UPDATE event_ticket_events SET title=?,slug=?,description=?,event_date=?,event_time=?,venue=?,price=?,currency=?,payment_instructions=?,ticket_note=?,cover_image=?,regular_price=?,vip_price=?,vvip_price=? WHERE id=?""",(title,slug,request.form.get('description','').strip(),request.form.get('event_date','').strip(),request.form.get('event_time','').strip(),request.form.get('venue','').strip(),regular,request.form.get('currency','KES').strip().upper()[:6] or 'KES',request.form.get('payment_instructions','').strip(),request.form.get('ticket_note','').strip(),cover,regular,vip,vvip,event_id)); db.commit()
    flash('Event details updated.','success'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.post('/ticketing/event/<int:event_id>/delete')
def event_delete(event_id):
    if not session.get('user_id') and not session.get('admin_auth'): return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not event_ticket_owner(event) and not session.get('admin_auth'): abort(403)
    db.execute('UPDATE event_ticket_events SET active=0 WHERE id=?',(event_id,)); db.execute("UPDATE event_tickets SET ticket_status='void' WHERE event_id=? AND ticket_status='valid'",(event_id,)); db.commit(); flash('Event removed from public ticketing. Existing tickets are void.','success'); return redirect(url_for('public.ticketing_home'))

@bp.post('/ticketing/event/<int:event_id>/scanner-pin')
def event_scanner_pin(event_id):
    if not session.get('user_id') and not session.get('admin_auth'): return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not event_ticket_owner(event) and not session.get('admin_auth'): abort(403)
    pin=request.form.get('scanners_pin','').strip()
    if not pin.isdigit() or not 4<=len(pin)<=8: flash('Scanner PIN must be 4–8 digits.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    db.execute('UPDATE event_ticket_events SET scanners_pin_hash=? WHERE id=?',(hash_pin(pin),event_id)); db.commit(); flash('Scanner PIN updated.','success'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.route('/ticketing/event/<int:event_id>/manage',methods=['GET'])
def event_manage(event_id):
    if not session.get('user_id') and not session.get('admin_auth'): return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not event_ticket_owner(event) and not session.get('admin_auth'): abort(403)
    tickets=db.execute('SELECT * FROM event_tickets WHERE event_id=? ORDER BY CASE WHEN ticket_status=\'used\' THEN 2 WHEN approval_status=\'pending\' THEN 0 ELSE 1 END,id DESC',(event_id,)).fetchall()
    return render_template('event_manage.html',event=event,tickets=tickets)

@bp.post('/ticketing/event/<int:event_id>/approve/<int:ticket_id>')
def event_approve(event_id,ticket_id):
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not session.get('admin_auth') and not event_ticket_owner(event): abort(403)
    code=request.form.get('mpesa_code','').strip(); tier=request.form.get('ticket_tier','auto').lower()
    if len(code)<3: flash('Enter the M-Pesa code before approving.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    row=db.execute('SELECT * FROM event_tickets WHERE id=? AND event_id=? AND approval_status=\'pending\'',(ticket_id,event_id)).fetchone()
    if not row: flash('That payment request is no longer pending.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    chosen=_tier_for_amount(event,row['amount'],tier)
    cur=db.execute("UPDATE event_tickets SET payment_reference=?,payment_status='verified',ticket_tier=?,approval_status='approved',approved_at=? WHERE id=? AND event_id=? AND approval_status='pending'",(code,chosen,now(),ticket_id,event_id)); db.commit(); flash('Payment approved and ticket unlocked.' if cur.rowcount else 'Could not approve that ticket.','success' if cur.rowcount else 'error'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.post('/ticketing/event/<int:event_id>/reject/<int:ticket_id>')
def event_reject(event_id,ticket_id):
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not session.get('admin_auth') and not event_ticket_owner(event): abort(403)
    db.execute("UPDATE event_tickets SET approval_status='rejected',payment_status='rejected',ticket_status='void' WHERE id=? AND event_id=? AND approval_status='pending'",(ticket_id,event_id)); db.commit(); flash('Request rejected.','success'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.route('/ticketing/staff-scanner',methods=['GET','POST'])
def staff_scanner():
    if request.method=='POST':
        code=request.form.get('scanner_code','').strip().upper(); pin=request.form.get('pin','').strip(); db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE scanner_code=? AND active=1',(code,)).fetchone()
        if event and verify_pin(event['scanners_pin_hash'],pin):
            session['event_scanner_event_id']=event['id']; session['event_scanner_unlocked']=True; return redirect(url_for('public.staff_scanner_live'))
        flash('That event code or Scanner PIN is not correct.','error')
    return render_template('event_scanner.html',authorized=False)

@bp.get('/ticketing/staff-scanner/live')
def staff_scanner_live():
    if not session.get('event_scanner_unlocked') or not session.get('event_scanner_event_id'):
        return redirect(url_for('public.staff_scanner'))
    db=get_db(); event=db.execute('SELECT id,title,event_date,event_time,venue FROM event_ticket_events WHERE id=? AND active=1',(session['event_scanner_event_id'],)).fetchone()
    if not event: session.pop('event_scanner_event_id',None); session.pop('event_scanner_unlocked',None); return redirect(url_for('public.staff_scanner'))
    tickets=db.execute("SELECT id,attendee_name,attendee_gender,ticket_tier,amount,ticket_status FROM event_tickets WHERE event_id=? AND approval_status='approved' ORDER BY attendee_name COLLATE NOCASE,id",(event['id'],)).fetchall()
    return render_template('event_scanner_live.html',event=event,tickets=tickets)

@bp.post('/ticketing/staff-scanner/exit')
def staff_scanner_exit():
    session.pop('event_scanner_event_id',None); session.pop('event_scanner_unlocked',None); return redirect(url_for('public.ticketing_home'))

@bp.get('/ticketing/scan/<ticket_code>')
def event_scan(ticket_code):
    sig=request.args.get('sig','')
    if not verify_ticket(ticket_code,sig):
        return jsonify(ok=False,reason='This QR is not authentic.') if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,reason='This QR is not authentic.')
    db=get_db(); row=db.execute("SELECT t.*,e.title event_title,e.id event_id,e.event_date,e.event_time,e.venue FROM event_tickets t JOIN event_ticket_events e ON e.id=t.event_id WHERE t.ticket_code=?",(ticket_code,)).fetchone()
    if not row:
        return jsonify(ok=False,reason='Ticket not found.') if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,reason='Ticket not found.')
    if session.get('event_scanner_event_id') != row['event_id'] or not session.get('event_scanner_unlocked'):
        reason='Open the staff scanner and enter its assigned Event Code and Scanner PIN first.'
        return jsonify(ok=False,reason=reason) if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,reason=reason)
    try: db.execute('BEGIN IMMEDIATE')
    except sqlite3.OperationalError: pass
    fresh=db.execute('SELECT * FROM event_tickets WHERE id=?',(row['id'],)).fetchone()
    if fresh['approval_status']!='approved':
        db.rollback(); reason='This ticket is waiting for approval.'
        return jsonify(ok=False,reason=reason) if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,ticket=row,reason=reason)
    if fresh['ticket_status']!='valid':
        from datetime import datetime, timezone
        recent=False
        if fresh['checked_in_at']:
            try: recent=(datetime.now(timezone.utc)-datetime.fromisoformat(fresh['checked_in_at'])).total_seconds() < 30
            except ValueError: recent=False
        db.rollback()
        if recent:
            guidance = 'VVIP — priority attention.' if row['ticket_tier']=='vvip' else ('VIP — priority attention.' if row['ticket_tier']=='vip' else 'Regular ticket.')
            return jsonify(ok=True,grace=True,ticket_id=row['id'],ticket_code=row['ticket_code'],name=row['attendee_name'],tier=row['ticket_tier'].upper(),guidance='Already approved — '+guidance,reason='APPROVED') if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=True,ticket=row,reason=guidance)
        reason='This ticket has already been used or voided.'
        return jsonify(ok=False,reason=reason,used=True) if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,ticket=row,reason=reason)
    cur=db.execute("UPDATE event_tickets SET ticket_status='used',checked_in_at=? WHERE id=? AND ticket_status='valid'",(now(),row['id'])); db.commit()
    if cur.rowcount!=1:
        reason='This ticket was approved moments ago.'
        return jsonify(ok=False,reason=reason,used=True) if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=False,ticket=row,reason=reason)
    guidance = 'VVIP — priority attention.' if row['ticket_tier']=='vvip' else ('VIP — priority attention.' if row['ticket_tier']=='vip' else 'Regular ticket.')
    return jsonify(ok=True,ticket_id=row['id'],ticket_code=row['ticket_code'],name=row['attendee_name'],tier=row['ticket_tier'].upper(),guidance=guidance,reason='APPROVED') if request.args.get('ajax')=='1' else render_template('event_scan_result.html',valid=True,ticket=row,reason=guidance)

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
    service_requests=db.execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id WHERE sr.user_id=? ORDER BY sr.id DESC',(u['id'],)).fetchall()
    event_tickets=db.execute("SELECT t.*,e.title event_title,e.event_date FROM event_tickets t JOIN event_ticket_events e ON e.id=t.event_id WHERE t.attendee_user_id=? ORDER BY t.id DESC",(u['id'],)).fetchall()
    return render_template('account.html',user=u,bookings=bookings,suggestions=suggestions,posts=posts,service_requests=service_requests,event_tickets=event_tickets)

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

@bp.get('/services')
def services():
    rows=get_db().execute('SELECT * FROM services WHERE published=1 ORDER BY sort_order,id').fetchall()
    return render_template('services.html',services=rows)

@bp.get('/service/<slug>')
def service(slug):
    row=get_db().execute('SELECT * FROM services WHERE slug=? AND published=1',(slug,)).fetchone()
    if not row: abort(404)
    return render_template('service.html',service=row)

@bp.route('/service/<slug>/request',methods=['GET','POST'])
def service_request(slug):
    row=get_db().execute('SELECT * FROM services WHERE slug=? AND published=1',(slug,)).fetchone()
    if not row: abort(404)
    if not session.get('user_id'):
        session['next_url']=request.path
        return redirect(url_for('public.register',next=request.path))
    u=get_db().execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL',(session['user_id'],)).fetchone()
    if request.method=='POST':
        try: guests=max(1,min(100000,int(request.form.get('guest_count','1'))))
        except ValueError: guests=1
        db=get_db()
        db.execute('INSERT INTO service_requests(service_id,user_id,name,email,phone,event_date,guest_count,ticketing,budget,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(row['id'],u['id'],request.form.get('name',u['name']).strip(),request.form.get('email',u['email']).strip().lower(),request.form.get('phone',u['phone']).strip(),request.form.get('event_date','').strip(),guests,1 if request.form.get('ticketing')=='1' else 0,request.form.get('budget','').strip(),request.form.get('notes','').strip(),now()))
        db.commit(); flash('Request sent. The Adventure Team has it.','success'); return redirect(url_for('public.account'))
    return render_template('service_request.html',service=row,user=u)

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
