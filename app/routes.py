from io import BytesIO
import re, secrets, sqlite3, os, hmac, json
from datetime import datetime, timezone
from pathlib import Path
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

def _request_ip():
    # Keep the first proxy address for admin diagnostics; deployment may sit behind a proxy.
    forwarded=request.headers.get('X-Forwarded-For','')
    return (forwarded.split(',')[0].strip() if forwarded else request.remote_addr or '')[:120]

def _ua_details(ua=''):
    ua=ua or ''
    platform='Android' if 'Android' in ua else ('iPhone/iPad' if ('iPhone' in ua or 'iPad' in ua) else ('Windows' if 'Windows' in ua else ('Mac' if 'Macintosh' in ua else ('Linux' if 'Linux' in ua else 'Other'))))
    browser='Chrome' if 'Chrome/' in ua and 'Edg/' not in ua else ('Edge' if 'Edg/' in ua else ('Safari' if 'Safari/' in ua and 'Chrome/' not in ua else ('Firefox' if 'Firefox/' in ua else 'Other')))
    model=''
    m=re.search(r'Android[^;)]*;\s*(?:[a-z]{2}-[A-Z]{2};\s*)?(?:wv;\s*)?([^;\)]+)',ua)
    if m: model=m.group(1).strip()
    if model in {'K','wv','Mobile'}: model=''
    return model[:120],platform,browser

def log_visit():
    if request.path.startswith(('/static/','/media/','/api/','/pulse_receiver','/health')):
        return
    key=request.cookies.get('visitor_key') or secrets.token_urlsafe(16)
    me=None
    try:
        uid=session.get('user_id')
        if uid: me=get_db().execute('SELECT id,name,email,phone FROM users WHERE id=? AND deleted_at IS NULL',(uid,)).fetchone()
    except Exception:
        me=None
    model,platform,browser=_ua_details(request.headers.get('User-Agent',''))
    db=get_db(); cur=db.execute(
        'INSERT INTO visits(visitor_key,path,created_at,user_id,name,email,phone,method,referrer,user_agent,ip_address,device_model,platform,browser) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (key,request.path,now(), me['id'] if me else None, me['name'] if me else '', me['email'] if me else '', me['phone'] if me else '', request.method, request.referrer or '', request.headers.get('User-Agent','')[:600], _request_ip(), model, platform, browser))
    db.commit(); request._visitor_key=key; request._visit_id=cur.lastrowid

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

@bp.post('/telemetry')
def telemetry():
    key=request.cookies.get('visitor_key')
    if not key: return jsonify(ok=True)
    data=request.get_json(silent=True) or {}
    model=str(data.get('model','') or '')[:120]
    platform=str(data.get('platform','') or '')[:120]
    browser=str(data.get('browser','') or '')[:200]
    try:
        db=get_db()
        db.execute(
            "UPDATE visits SET device_model=CASE WHEN ? <> '' THEN ? ELSE device_model END, platform=CASE WHEN ? <> '' THEN ? ELSE platform END, browser=CASE WHEN ? <> '' THEN ? ELSE browser END WHERE id=(SELECT id FROM visits WHERE visitor_key=? ORDER BY id DESC LIMIT 1)",
            (model, model, platform, platform, browser, browser, key)
        )
        db.commit()
    except Exception:
        current_app.logger.exception('Telemetry persistence failed')
    return jsonify(ok=True)

@bp.post('/client-error')
def client_error():
    data=request.get_json(silent=True) or {}
    db=get_db(); key=request.cookies.get('visitor_key','')
    uid=session.get('user_id')
    page=str(data.get('page') or request.referrer or request.path)[:500]
    message=str(data.get('message','Client-side error'))[:4000]
    kind=str(data.get('kind','ClientError'))[:100]
    extra='source='+str(data.get('source',''))[:300]+' line='+str(data.get('line',''))[:20]+' column='+str(data.get('column',''))[:20]
    stack=str(data.get('stack',''))[:10000]
    db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(now(),0,page,request.method,kind,message,extra+'\n'+stack,uid,key,request.headers.get('User-Agent','')[:600],_request_ip())); db.commit()
    return jsonify(ok=True)

@bp.get('/')
def home():
    db=get_db()
    trips=list(db.execute("SELECT * FROM trips WHERE status='published' ORDER BY date").fetchall())
    destinations=list(db.execute('SELECT * FROM destinations WHERE active=1 ORDER BY sort_order,id').fetchall())
    posts=list(db.execute('SELECT * FROM posts WHERE published=1 ORDER BY id DESC').fetchall())
    # Rotate the public selection several times a day without changing admin data.
    # Active destinations / published trips are always the source of truth, so additions
    # and removals made by the system flow into the public page automatically.
    rotation_slot=int(datetime.now(timezone.utc).timestamp() // (6*60*60))
    if destinations:
        # Deterministic per-slot rotation keeps a stable page for a few hours, then
        # presents a different starting place without reshuffling records in storage.
        shift=rotation_slot % len(destinations); destinations=(destinations[shift:]+destinations[:shift])[:12]
    else: destinations=[]
    if trips:
        shift=rotation_slot % len(trips); trips=(trips[shift:]+trips[:shift])[:12]
    else: trips=[]
    posts=posts[:6]
    return render_template('home.html',trips=trips,destinations=destinations,posts=posts,promo=promo_value(),q='')

@bp.get('/search')
def search():
    q=request.args.get('q','').strip()
    db=get_db(); trips=[]; destinations=[]; services=[]
    if q:
        like='%'+q+'%'
        trips=db.execute("SELECT * FROM trips WHERE status='published' AND (title LIKE ? OR destination LIKE ? OR description LIKE ? OR pickup LIKE ? OR itinerary LIKE ?) ORDER BY LOWER(title), date, id LIMIT 100",(like,like,like,like,like)).fetchall()
        destinations=db.execute("SELECT * FROM destinations WHERE active=1 AND (title LIKE ? OR subtitle LIKE ? OR vibe LIKE ?) ORDER BY sort_order,id LIMIT 24",(like,like,like)).fetchall()
    posts=db.execute("SELECT * FROM posts WHERE published=1 AND (title LIKE ? OR excerpt LIKE ? OR body LIKE ?) ORDER BY id DESC LIMIT 12",('%'+q+'%','%'+q+'%','%'+q+'%')).fetchall() if q else []
    return render_template('search.html',q=q,trips=trips,destinations=destinations,posts=posts,promo=promo_value())

@bp.get('/destination/<slug>')
def destination(slug):
    d=get_db().execute('SELECT * FROM destinations WHERE slug=? AND active=1',(slug,)).fetchone()
    if not d: abort(404)
    related=get_db().execute("SELECT * FROM trips WHERE status='published' AND (destination LIKE ? OR title LIKE ? OR description LIKE ?) ORDER BY LOWER(title), date, id LIMIT 24",('%'+d['title'].split()[0]+'%','%'+d['title'].split()[0]+'%','%'+d['title'].split()[0]+'%')).fetchall()
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
# GROUP RETREATS
# A lightweight group-planning workflow, independent of ordinary travel bookings.
def _new_group_code(db):
    while True:
        code='GRP-' + secrets.token_hex(3).upper()
        if not db.execute('SELECT 1 FROM group_retreats WHERE group_code=?',(code,)).fetchone():
            return code

def _new_group_pass_code(db):
    while True:
        code='GTP-' + secrets.token_hex(6).upper()
        if not db.execute('SELECT 1 FROM group_members WHERE pass_code=?',(code,)).fetchone():
            return code

def _group_row(code):
    return get_db().execute('SELECT * FROM group_retreats WHERE group_code=? AND active=1',(code.upper().strip(),)).fetchone()

def _group_pass_signature(code):
    return ticket_signature(code)

@bp.route('/group-retreats', methods=['GET','POST'])
def group_retreats():
    db=get_db()
    if request.method=='POST':
        leader_name=request.form.get('leader_name','').strip()
        leader_phone=request.form.get('leader_phone','').strip()
        leader_email=request.form.get('leader_email','').strip().lower()
        title=request.form.get('title','').strip()
        group_type=request.form.get('group_type','Group').strip() or 'Group'
        destination=request.form.get('destination','').strip()
        activities=request.form.get('activities','').strip()
        preferred_date=request.form.get('preferred_date','').strip()
        people=max(0,int(request.form.get('people_count','0') or 0))
        try: suggested=max(0,int(request.form.get('suggested_price','0') or 0))
        except ValueError: suggested=0
        notes=request.form.get('notes','').strip()
        pin=request.form.get('leader_pin','').strip()
        if not leader_name or not leader_phone or not title or not destination or not activities or people<5:
            flash('Give the useful details and plan for at least 5 people.','error'); return render_template('group_retreats.html')
        if not pin.isdigit() or not 4<=len(pin)<=8:
            flash('Choose a 4–8 digit Group Leader PIN.','error'); return render_template('group_retreats.html')
        code=_new_group_code(db)
        db.execute("INSERT INTO group_retreats(group_code,leader_pin_hash,leader_user_id,leader_name,leader_phone,leader_email,title,group_type,destination,activities,preferred_date,people_count,suggested_price,notes,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (code,hash_pin(pin),session.get('user_id'),leader_name,leader_phone,leader_email,title,group_type,destination,activities,preferred_date,people,suggested,notes,'pending',now()))
        db.commit(); flash('Group plan created. Save the Group ID and Leader PIN.','success'); return redirect(url_for('public.group_manage',code=code))
    return render_template('group_retreats.html')

@bp.get('/group-retreats/group/<code>')
def group_public(code):
    group=_group_row(code)
    if not group: abort(404)
    return render_template('group_public.html',group=group)

@bp.post('/group-retreats/group/<code>/join')
def group_join(code):
    group=_group_row(code)
    if not group: abort(404)
    name=request.form.get('name','').strip(); gender=request.form.get('gender','').strip().lower()
    if not name or gender not in {'male','female'}:
        flash('Enter the member name and choose male or female.','error'); return redirect(url_for('public.group_public',code=code))
    if group['status'] not in {'approved','active'}:
        flash('This group plan is not approved for members yet.','error'); return redirect(url_for('public.group_public',code=code))
    db=get_db(); pc=_new_group_pass_code(db)
    sig=_group_pass_signature(pc)
    db.execute("INSERT INTO group_members(retreat_id,name,gender,payment_status,pass_type,pass_code,signature,created_at) VALUES(?,?,?,?,?,?,?,?)",
               (group['id'],name,gender,'pending','individual',pc,sig,now()))
    db.commit(); flash('You joined the group list. Payment still needs approval before your pass unlocks.','success'); return redirect(url_for('public.group_public',code=code))

@bp.route('/group-retreats/manage/<code>',methods=['GET','POST'])
def group_manage(code):
    group=_group_row(code)
    if not group: abort(404)
    authenticated=session.get('group_leader_code')==group['group_code'] or (session.get('user_id') and session.get('user_id')==group['leader_user_id'])
    if request.method=='POST' and request.form.get('action')=='unlock':
        if verify_pin(group['leader_pin_hash'],request.form.get('leader_pin','').strip()):
            session['group_leader_code']=group['group_code']; authenticated=True
        else: flash('That Group Leader PIN is not correct.','error')
    if not authenticated: return render_template('group_unlock.html',group=group)
    db=get_db(); members=db.execute('SELECT * FROM group_members WHERE retreat_id=? ORDER BY id',(group['id'],)).fetchall()
    counts={
        'members':len(members),
        'paid':sum(1 for m in members if m['payment_status']=='approved'),
        'submitted':sum(1 for m in members if m['payment_status']=='submitted')
    }
    return render_template('group_manage.html',group=group,members=members,counts=counts)

@bp.post('/group-retreats/manage/<code>/member')
def group_add_member(code):
    group=_group_row(code)
    if not group or session.get('group_leader_code')!=group['group_code']: abort(403)
    if group['status'] not in {'approved','active'}:
        flash('The group plan must be approved before members are added.','error'); return redirect(url_for('public.group_manage',code=code))
    name=request.form.get('name','').strip(); gender=request.form.get('gender','').strip().lower()
    try: amount=max(0,int(request.form.get('amount','0') or 0))
    except ValueError: amount=0
    reference=request.form.get('payment_reference','').strip()
    if not name or gender not in {'male','female'}:
        flash('Enter the member name and gender.','error'); return redirect(url_for('public.group_manage',code=code))
    db=get_db(); pc=_new_group_pass_code(db)
    db.execute("INSERT INTO group_members(retreat_id,name,gender,amount_paid,payment_reference,payment_status,pass_type,pass_code,signature,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (group['id'],name,gender,amount,reference,'submitted' if amount and reference else 'pending','individual',pc,_group_pass_signature(pc),now()))
    db.commit(); flash('Member added. Payment can now be approved.','success'); return redirect(url_for('public.group_manage',code=code))

@bp.post('/group-retreats/manage/<code>/edit')
def group_edit(code):
    group=_group_row(code)
    if not group or session.get('group_leader_code')!=group['group_code']: abort(403)
    try: people=max(5,int(request.form.get('people_count','5') or 5)); suggested=max(0,int(request.form.get('suggested_price','0') or 0))
    except ValueError: people=5; suggested=0
    db=get_db(); db.execute("UPDATE group_retreats SET title=?,group_type=?,destination=?,activities=?,preferred_date=?,people_count=?,suggested_price=?,notes=? WHERE id=?",
        (request.form.get('title','').strip(),request.form.get('group_type','Group').strip() or 'Group',request.form.get('destination','').strip(),request.form.get('activities','').strip(),request.form.get('preferred_date','').strip(),people,suggested,request.form.get('notes','').strip(),group['id']))
    db.commit(); flash('Group plan updated.','success'); return redirect(url_for('public.group_manage',code=code))

@bp.get('/group-retreats/pass/<pass_code>/download')
def group_pass_download(pass_code):
    db=get_db(); row=db.execute("SELECT m.*,g.title,g.destination,g.preferred_date,g.group_code FROM group_members m JOIN group_retreats g ON g.id=m.retreat_id WHERE m.pass_code=? AND g.active=1",(pass_code,)).fetchone()
    if not row: abort(404)
    if row['payment_status']!='approved': flash('This pass is not approved yet.','error'); return redirect(url_for('public.group_public',code=row['group_code']))
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import io
    buf=io.BytesIO(); c=canvas.Canvas(buf,pagesize=A4); w,h=A4
    c.setFillColorRGB(.07,.13,.17); c.rect(0,h-150,w,150,fill=1,stroke=0); c.setFillColorRGB(1,1,1); c.setFont('Helvetica-Bold',22); c.drawString(40,h-58,'GROUP PASS'); c.setFont('Helvetica-Bold',10); c.drawString(40,h-82,row['group_code'])
    c.setFillColorRGB(.08,.08,.08); c.setFont('Helvetica-Bold',25); c.drawString(40,h-205,row['name']); c.setFont('Helvetica',12); c.drawString(40,h-232,f"{row['title']} · {row['destination']}"); c.drawString(40,h-252,row['preferred_date'] or 'Date to be confirmed')
    qr=make_qr_bytes(url_for('public.group_pass_verify',pass_code=row['pass_code'],sig=row['signature'],_external=True)); c.drawImage(ImageReader(io.BytesIO(qr)),w-210,h-400,width=150,height=150,mask='auto'); c.setFont('Helvetica-Bold',10); c.drawString(40,h-320,'APPROVED GROUP MEMBER'); c.setFont('Helvetica',10); c.drawString(40,h-340,'Present this pass for the group activity.'); c.showPage(); c.save(); buf.seek(0)
    return send_file(buf,as_attachment=True,download_name=f"{row['group_code']}-{row['name'].replace(' ','-')}.pdf",mimetype='application/pdf')

@bp.get('/group-retreats/pass/<pass_code>')
def group_pass_verify(pass_code):
    sig=request.args.get('sig',''); db=get_db(); row=db.execute("SELECT m.*,g.title,g.destination,g.preferred_date,g.group_code FROM group_members m JOIN group_retreats g ON g.id=m.retreat_id WHERE m.pass_code=? AND g.active=1",(pass_code,)).fetchone()
    if not row or not hmac.compare_digest(row['signature'],sig): return render_template('group_scan_result.html',valid=False,member=row,reason='Invalid group pass.')
    if row['payment_status']!='approved': return render_template('group_scan_result.html',valid=False,member=row,reason='Payment is not approved yet.')
    if row['checked_in_at']: return render_template('group_scan_result.html',valid=False,member=row,reason='This group pass has already been checked.')
    db.execute('UPDATE group_members SET checked_in_at=? WHERE id=? AND checked_in_at IS NULL',(now(),row['id'])); db.commit(); return render_template('group_scan_result.html',valid=True,member=row)

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
    """Resolve the ticket class from the event prices.

    Manual choices always win. In auto mode, an exact configured price wins;
    otherwise the amount falls into the highest configured tier it reaches.
    This makes 2,000 reliably map to VIP when, for example, Regular=1,000,
    VIP=2,000 and VVIP=5,000.
    """
    mapping = [
        ('regular', int(event['regular_price'] or 0)),
        ('vip', int(event['vip_price'] or 0)),
        ('vvip', int(event['vvip_price'] or 0)),
    ]
    requested=(requested or 'auto').lower()
    if requested in {'regular','vip','vvip'}:
        return requested
    amount=max(0, int(amount or 0))
    # Prefer an exact configured price, including when prices are entered out of order.
    for tier, price in mapping:
        if price > 0 and amount == price:
            return tier
    # Otherwise classify by the highest configured tier whose entry price is reached.
    reached=[(price,tier) for tier,price in mapping if price > 0 and amount >= price]
    if reached:
        reached.sort(key=lambda item:item[0])
        return reached[-1][1]
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

@bp.post('/ticketing/event/<int:event_id>/joint-ticket')
def event_joint_ticket(event_id):
    if not session.get('user_id') and not session.get('admin_auth'): return redirect(url_for('public.login',next=request.path))
    db=get_db(); event=db.execute('SELECT * FROM event_ticket_events WHERE id=?',(event_id,)).fetchone()
    if not event: abort(404)
    if not event_ticket_owner(event) and not session.get('admin_auth'): abort(403)
    raw=request.form.getlist('ticket_ids')
    ids=[]
    for x in raw:
        try: ids.append(int(x))
        except ValueError: pass
    ids=list(dict.fromkeys(ids))
    if len(ids)<2:
        flash('Select at least two approved VIP or VVIP tickets.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    q=','.join('?'*len(ids)); rows=db.execute(f"SELECT * FROM event_tickets WHERE event_id=? AND id IN ({q}) AND approval_status='approved' AND ticket_status='valid'", [event_id,*ids]).fetchall()
    if len(rows)!=len(ids):
        flash('Only approved, unused tickets can be joined.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    tiers={r['ticket_tier'].lower() for r in rows}
    if tiers not in ({'vip'},{'vvip'}):
        flash('Joint tickets are for VIP or VVIP members of the same tier.','error'); return redirect(url_for('public.event_manage',event_id=event_id))
    joint_code='JNT-'+secrets.token_hex(7).upper(); sig=ticket_signature(joint_code)
    db.execute('INSERT INTO event_joint_tickets(event_id,joint_code,signature,tier,ticket_codes,created_at) VALUES(?,?,?,?,?,?)',(event_id,joint_code,sig,next(iter(tiers)),','.join(r['ticket_code'] for r in rows),now())); db.commit()
    flash('Joint ticket created. Download the single pass for this VIP/VVIP group.','success'); return redirect(url_for('public.event_manage',event_id=event_id))

@bp.get('/ticketing/joint/<joint_code>/download')
def event_joint_download(joint_code):
    db=get_db(); j=db.execute('SELECT j.*,e.title event_title,e.event_date,e.event_time,e.venue,e.currency FROM event_joint_tickets j JOIN event_ticket_events e ON e.id=j.event_id WHERE j.joint_code=? AND e.active=1',(joint_code,)).fetchone()
    if not j: abort(404)
    codes=[c for c in j['ticket_codes'].split(',') if c]
    if not codes: abort(404)
    q=','.join('?'*len(codes)); rows=db.execute(f'SELECT * FROM event_tickets WHERE event_id=? AND ticket_code IN ({q}) ORDER BY id',[j['event_id'],*codes]).fetchall()
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from io import BytesIO
    buf=BytesIO(); W,H=A4; c=canvas.Canvas(buf,pagesize=A4)
    c.setFillColorRGB(.07,.13,.17); c.rect(0,H-150,W,150,fill=1,stroke=0); c.setFillColorRGB(1,1,1); c.setFont('Helvetica-Bold',22); c.drawString(40,H-58,'JOINT EVENT TICKET'); c.setFont('Helvetica-Bold',10); c.drawString(40,H-82,j['joint_code'])
    c.setFillColorRGB(.08,.08,.08); c.setFont('Helvetica-Bold',24); c.drawString(40,H-205,j['event_title'][:36]); c.setFont('Helvetica',11); c.drawString(40,H-228,f"{j['event_date'] or 'TBA'} {j['event_time'] or ''}".strip()); c.drawString(40,H-246,j['venue'] or 'Venue TBA'); c.setFont('Helvetica-Bold',15); c.drawString(40,H-285,j['tier'].upper())
    y=H-325; c.setFont('Helvetica-Bold',10); c.drawString(40,y,'NAMES ON THIS PASS'); y-=20; c.setFont('Helvetica',10)
    for idx,r in enumerate(rows,1): c.drawString(45,y,f'{idx}. {r["attendee_name"]}'); y-=17
    qr=make_qr_bytes(url_for('public.event_joint_verify',joint_code=j['joint_code'],sig=j['signature'],_external=True)); c.drawImage(ImageReader(BytesIO(qr)),W-215,H-440,width=150,height=150,mask='auto'); c.setFont('Helvetica-Bold',9); c.drawString(40,55,'ONE JOINT QR · SERVER VERIFIED · ALL NAMES ENTER TOGETHER'); c.showPage(); c.save(); buf.seek(0)
    safe=re.sub(r'[^A-Za-z0-9_-]','-',j['event_title']); return send_file(buf,mimetype='application/pdf',as_attachment=True,download_name=f'{safe}-{j["joint_code"]}.pdf')

@bp.get('/ticketing/joint/<joint_code>')
def event_joint_verify(joint_code):
    sig=request.args.get('sig',''); db=get_db()
    db.execute('BEGIN IMMEDIATE')
    j=db.execute('SELECT j.*,e.title event_title,e.event_date,e.event_time,e.venue FROM event_joint_tickets j JOIN event_ticket_events e ON e.id=j.event_id WHERE j.joint_code=? AND e.active=1',(joint_code,)).fetchone()
    if not j or not hmac.compare_digest(j['signature'],sig): db.rollback(); return render_template('event_scan_result.html',valid=False,reason='This joint ticket is not valid.')
    if j['status']!='valid': db.rollback(); return render_template('event_scan_result.html',valid=False,reason='This joint ticket has already been approved at the entrance.')
    codes=[c for c in j['ticket_codes'].split(',') if c]; q=','.join('?'*len(codes)); rows=db.execute(f'SELECT * FROM event_tickets WHERE event_id=? AND ticket_code IN ({q})',[j['event_id'],*codes]).fetchall()
    if len(rows)!=len(codes) or any(r['ticket_status']!='valid' for r in rows): db.rollback(); return render_template('event_scan_result.html',valid=False,reason='One or more tickets in this joint pass are no longer valid.')
    cur=db.execute("UPDATE event_joint_tickets SET status='used',used_at=? WHERE id=? AND status='valid'",(now(),j['id']))
    if cur.rowcount!=1: db.rollback(); return render_template('event_scan_result.html',valid=False,reason='This joint ticket was just approved at another scanner.')
    stamp=now()
    for r in rows: db.execute("UPDATE event_tickets SET ticket_status='used',checked_in_at=? WHERE id=? AND ticket_status='valid'",(stamp,r['id']))
    db.commit(); return render_template('event_scan_result.html',valid=True,ticket={'attendee_name':'Joint '+j['tier'].upper(),'ticket_tier':j['tier'],'event_title':j['event_title'],'event_date':j['event_date'],'venue':j['venue']})

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
    from pathlib import Path
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
    sig_path=Path(current_app.root_path)/'static'/'event-signature.png'
    if sig_path.exists():
        c.drawImage(ImageReader(str(sig_path)),20*mm,43*mm,width=48*mm,height=11*mm,mask='auto')
        c.setFillColor(bg[1]); c.setFont('Helvetica',6.5); c.drawString(20*mm,40*mm,'EVENT AUTHORIZATION')
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
    joints=db.execute('SELECT * FROM event_joint_tickets WHERE event_id=? ORDER BY id DESC',(event_id,)).fetchall()
    return render_template('event_manage.html',event=event,tickets=tickets,joints=joints)

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

@bp.before_request
def _ensure_stuff_session():
    # Backward compatibility only: older builds used a My Stuff-specific lock.
    # The current app uses one optional account-wide Open Road ID instead.
    uid = session.get('user_id')
    if session.get('_stuff_user_id') != uid:
        session.pop('stuff_unlocked', None)
        session['_stuff_user_id'] = uid


def _current_user_for_stuff():
    # My Stuff is an independent personal workspace. It never uses the
    # normal Adventure PIN/login gate. Authenticated users use their account;
    # visitors get a private anonymous workspace identified only by a session
    # token. This keeps Travel booking/authentication completely unchanged.
    uid = session.get('user_id') or session.get('stuff_user_id')
    if not uid:
        return _ensure_stuff_guest_user()
    return get_db().execute('SELECT * FROM users WHERE id=? AND deleted_at IS NULL', (uid,)).fetchone()


def _ensure_stuff_guest_user():
    existing = session.get('stuff_user_id')
    db = get_db()
    if existing:
        row = db.execute('SELECT * FROM users WHERE id=? AND is_stuff_guest=1 AND deleted_at IS NULL', (existing,)).fetchone()
        if row:
            return row
    guest_key = secrets.token_hex(16)
    # Guest rows are deliberately unusable for normal Travel login.
    cur = db.execute(
        "INSERT INTO users(name,phone,email,pin_hash,recovery_question,recovery_answer_hash,is_stuff_guest,created_at) VALUES(?,?,?,?,?,?,?,?)",
        ('My Stuff Guest', 'guest-' + guest_key[:12], 'stuff-' + guest_key + '@local.openroad', hash_pin(secrets.token_hex(16)), 'none', hash_answer(secrets.token_hex(16)), 1, now())
    )
    db.commit()
    session['stuff_user_id'] = cur.lastrowid
    return db.execute('SELECT * FROM users WHERE id=?', (cur.lastrowid,)).fetchone()


def _global_simple_id_hash(user):
    # Migrate the previous My Stuff ID into the single app-wide ID lazily.
    return user['simple_id_hash'] or user['stuff_id_hash']


def _stuff_colors():
    return ['lime', 'aqua', 'orange', 'pink', 'blue', 'yellow', 'teal', 'white', 'red', 'purple', 'navy', 'mint', 'rose', 'coral', 'sky', 'ink', 'peach', 'lemon', 'violet', 'sand', 'cyan', 'magenta']

def _journal_moods():
    return ['morning', 'midday', 'evening']

def _journal_secret_set(user):
    return bool(user['journal_secret_hash'])

def _journal_unlocked(user):
    return not _journal_secret_set(user) or session.get('journal_unlocked_user') == user['id']

def _journal_require_unlock(user):
    if _journal_unlocked(user):
        return None
    return render_template('journal_lock.html')

def _journal_excerpt(body, limit=190):
    text=re.sub(r'\s+', ' ', (body or '')).strip()
    return text if len(text) <= limit else text[:limit-1].rstrip() + '…'


def _safe_stuff_image_name(original):
    from werkzeug.utils import secure_filename
    base = secure_filename(original) or 'image'
    stem = base.rsplit('.', 1)[0][:55]
    return f"{stem}-{secrets.token_hex(5)}.jpg"


def _stuff_redirect(section='journal'):
    return redirect(url_for('public.my_stuff', section=section))



def _stuff_id_ready(user):
    return bool(_global_simple_id_hash(user))

def _cards_allowed(user):
    return _stuff_id_ready(user) or int(user['stuff_card_uses'] or 0) <= 5


def _stuff_use_and_context(user, column):
    db=get_db()
    db.execute(f"UPDATE users SET {column}=COALESCE({column},0)+1 WHERE id=?", (user['id'],))
    db.commit()
    refreshed=db.execute('SELECT * FROM users WHERE id=?', (user['id'],)).fetchone()
    return refreshed

def _render_stuff_id_form(next_endpoint):
    return url_for('public.my_stuff_id', next=next_endpoint)

def _journal_sidebar_data(user, view='active'):
    db=get_db()
    journals=db.execute("SELECT * FROM journal_entries WHERE user_id=? AND archived=? ORDER BY favorite DESC, updated_at DESC, id DESC", (user['id'], 1 if view=='archived' else 0)).fetchall()
    journal_count=db.execute('SELECT COUNT(*) n FROM journal_entries WHERE user_id=? AND archived=0',(user['id'],)).fetchone()['n']
    archived_count=db.execute('SELECT COUNT(*) n FROM journal_entries WHERE user_id=? AND archived=1',(user['id'],)).fetchone()['n']
    cards=db.execute('SELECT * FROM stuff_cards WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user['id'],)).fetchall()
    return journals, journal_count, archived_count, cards

@bp.get('/my-stuff')
def my_stuff():
    # My Stuff is always an open doorway. It must never show a PIN/login gate.
    # Journal, Cards, Copy & Paste and Edits Studio are all independently accessible.
    # None of them redirects to the normal Adventure PIN/login gate.
    return render_template('my_stuff.html')

@bp.get('/my-stuff/journal')
def my_stuff_journal():
    user=_current_user_for_stuff()
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    user=_stuff_use_and_context(user,'stuff_journal_uses')
    view=request.args.get('view','active').strip().lower()
    if view not in {'active','archived'}: view='active'
    selected=request.args.get('entry','').strip()
    edit_mode=request.args.get('edit')=='1' or request.args.get('write')=='1'
    journals,count,archived_count,_cards=_journal_sidebar_data(user,view)
    entry=None
    if selected.isdigit():
        entry=get_db().execute('SELECT * FROM journal_entries WHERE id=? AND user_id=?',(int(selected),user['id'])).fetchone()
    return render_template('my_journal.html',user=user,journals=journals,journal_count=count,archived_journal_count=archived_count,journal_view=view,entry=entry,moods=_journal_moods(),simple_id_exists=_stuff_id_ready(user),use_count=int(user['stuff_journal_uses'] or 0),edit_mode=edit_mode,journal_secret_set=_journal_secret_set(user))

@bp.get('/my-stuff/journal/settings')
def my_stuff_journal_settings():
    user=_current_user_for_stuff()
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    return render_template('journal_settings.html', journal_secret_set=_journal_secret_set(user), simple_id_exists=_stuff_id_ready(user))

@bp.post('/my-stuff/journal/settings')
def my_stuff_journal_settings_save():
    user=_current_user_for_stuff()
    action=request.form.get('action','').strip()
    db=get_db()
    if action=='set-secret':
        value=request.form.get('secret_id','').strip()
        if not re.fullmatch(r'[A-Za-z0-9]{4,12}', value):
            flash('Use 4–12 letters or numbers for your Journal secret.','error')
        else:
            db.execute('UPDATE users SET journal_secret_hash=? WHERE id=?',(hash_pin(value),user['id'])); db.commit(); session['journal_unlocked_user']=user['id']; flash('Journal secret is active. It protects Journal only.','success')
    elif action=='remove-secret':
        db.execute('UPDATE users SET journal_secret_hash=NULL WHERE id=?',(user['id'],)); db.commit(); session.pop('journal_unlocked_user',None); flash('Journal secret removed.','success')
    return redirect(url_for('public.my_stuff_journal'))

@bp.post('/my-stuff/journal/unlock')
def my_stuff_journal_unlock():
    user=_current_user_for_stuff(); value=request.form.get('secret_id','').strip()
    if _journal_secret_set(user) and verify_pin(user['journal_secret_hash'], value):
        session['journal_unlocked_user']=user['id']; return redirect(url_for('public.my_stuff_journal'))
    flash('That Journal secret is not correct.','error'); return redirect(url_for('public.my_stuff_journal'))

@bp.post('/my-stuff/id')
def my_stuff_id():
    user=_current_user_for_stuff()
    if not user: abort(403)
    value=request.form.get('simple_id','').strip()
    nxt=request.form.get('next','journal').strip().lower()
    destinations={'journal':'public.my_stuff_journal','cards':'public.my_stuff_cards','copy-paste':'public.my_stuff_copy_paste','color-cards':'public.my_stuff_color_cards','edits-studio':'public.my_stuff_edits_studio'}
    if not re.fullmatch(r'[A-Za-z0-9]{4,8}',value):
        flash('Choose a simple 4–8 character ID using letters and numbers.','error')
    elif _global_simple_id_hash(user):
        flash('You already have an Open Road ID. The same ID is used throughout the app.','error')
    else:
        db=get_db(); db.execute('UPDATE users SET simple_id_hash=? WHERE id=?',(hash_pin(value),user['id'])); db.commit()
        flash('Your Open Road ID is ready. Use the same ID throughout Open Road.','success')
    endpoint=destinations.get(nxt,'public.my_stuff_journal')
    return redirect(url_for(endpoint))

@bp.post('/my-stuff/journal/save')
def my_stuff_journal_save():
    user=_current_user_for_stuff()
    if not user: abort(403)
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    db=get_db(); entry_id=request.form.get('entry_id','').strip(); title=request.form.get('title','').strip()[:140]
    body=request.form.get('body','').strip(); mood=request.form.get('mood','morning').strip().lower(); segments_json=request.form.get('segments_json','').strip(); tags=request.form.get('tags','').strip()[:240]; cover_color=request.form.get('cover_color','cream').strip().lower()
    if mood not in _journal_moods(): mood='morning'
    if cover_color not in {'cream','lime','aqua','orange','pink','blue','sun'}: cover_color='cream'
    clean_tags=', '.join([x.strip()[:30] for x in tags.split(',') if x.strip()][:8])
    if not title or not body:
        flash('Give your journal story a title and some words first.','error'); return redirect(url_for('public.my_stuff_journal'))
    if entry_id:
        owned=db.execute('SELECT id FROM journal_entries WHERE id=? AND user_id=?',(entry_id,user['id'])).fetchone()
        if not owned: abort(404)
        db.execute('UPDATE journal_entries SET title=?,body=?,mood=?,tags=?,cover_color=?,segments_json=?,updated_at=? WHERE id=? AND user_id=?',(title,body,mood,clean_tags,cover_color,segments_json,now(),entry_id,user['id'])); saved_id=int(entry_id); msg='Journal story updated.'
    else:
        cur=db.execute('INSERT INTO journal_entries(user_id,title,body,mood,tags,cover_color,segments_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(user['id'],title,body,mood,clean_tags,cover_color,segments_json,now(),now())); saved_id=cur.lastrowid; msg='Journal story saved.'
    db.commit(); flash(msg,'success'); return redirect(url_for('public.my_stuff_journal',entry=saved_id))

@bp.get('/my-stuff/journal/<int:entry_id>')
def my_stuff_journal_view(entry_id):
    user=_current_user_for_stuff(); blocked=_journal_require_unlock(user)
    if blocked: return blocked
    row=get_db().execute('SELECT id FROM journal_entries WHERE id=? AND user_id=?',(entry_id,user['id'])).fetchone()
    if not row: abort(404)
    return redirect(url_for('public.my_stuff_journal', entry=entry_id, edit='1' if request.args.get('edit')=='1' else None))

@bp.post('/my-stuff/journal/<int:entry_id>/favorite')
def my_stuff_journal_favorite(entry_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    db=get_db(); row=db.execute('SELECT favorite FROM journal_entries WHERE id=? AND user_id=?',(entry_id,user['id'])).fetchone()
    if not row: abort(404)
    db.execute('UPDATE journal_entries SET favorite=? WHERE id=? AND user_id=?',(0 if row['favorite'] else 1,entry_id,user['id'])); db.commit()
    return redirect(request.form.get('next') or url_for('public.my_stuff_journal',entry=entry_id))

@bp.post('/my-stuff/journal/<int:entry_id>/archive')
def my_stuff_journal_archive(entry_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    db=get_db(); row=db.execute('SELECT archived FROM journal_entries WHERE id=? AND user_id=?',(entry_id,user['id'])).fetchone()
    if not row: abort(404)
    db.execute('UPDATE journal_entries SET archived=? WHERE id=? AND user_id=?',(0 if row['archived'] else 1,entry_id,user['id'])); db.commit(); flash('Journal story updated.','success')
    return redirect(url_for('public.my_stuff_journal',view='archived' if not row['archived'] else 'active'))

@bp.post('/my-stuff/journal/<int:entry_id>/delete')
def my_stuff_journal_delete(entry_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    blocked=_journal_require_unlock(user)
    if blocked: return blocked
    db=get_db(); cur=db.execute('DELETE FROM journal_entries WHERE id=? AND user_id=?',(entry_id,user['id'])); db.commit()
    if not cur.rowcount: abort(404)
    flash('Journal story deleted.','success'); return redirect(url_for('public.my_stuff_journal'))

@bp.post('/my-stuff/folder/save')
def my_stuff_folder_save():
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); folder_id=request.form.get('folder_id','').strip(); name=request.form.get('name','').strip()[:60]; color=request.form.get('color','lime')
    if color not in _stuff_colors(): color='lime'
    if not name: flash('Give the folder a name.','error'); return redirect(url_for('public.my_stuff_journal'))
    try:
        if folder_id: db.execute('UPDATE stuff_folders SET name=?,color=? WHERE id=? AND user_id=?',(name,color,folder_id,user['id']))
        else: db.execute('INSERT INTO stuff_folders(user_id,name,color,created_at) VALUES(?,?,?,?)',(user['id'],name,color,now()))
        db.commit(); flash('Folder saved.','success')
    except sqlite3.IntegrityError: flash('You already have a folder with that name.','error')
    return redirect(url_for('public.my_stuff_journal'))

@bp.post('/my-stuff/folder/<int:folder_id>/delete')
def my_stuff_folder_delete(folder_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); db.execute('DELETE FROM stuff_folders WHERE id=? AND user_id=?',(folder_id,user['id'])); db.commit(); flash('Folder deleted.','success')
    return redirect(url_for('public.my_stuff_journal'))

@bp.get('/my-stuff/cards')
def my_stuff_cards():
    user=_current_user_for_stuff()
    user=_stuff_use_and_context(user,'stuff_card_uses')
    use_count=int(user['stuff_card_uses'] or 0)
    has_id=_stuff_id_ready(user)
    if not has_id and use_count > 5:
        return render_template('my_cards.html',user=user,cards=get_db().execute('SELECT * FROM stuff_cards WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user['id'],)).fetchall(),folders=get_db().execute('SELECT * FROM stuff_folders WHERE user_id=? ORDER BY name',(user['id'],)).fetchall(),card_locked=True,card_use_count=use_count,simple_id_exists=False)
    db=get_db()
    cards=db.execute('SELECT * FROM stuff_cards WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user['id'],)).fetchall()
    folders=db.execute('SELECT * FROM stuff_folders WHERE user_id=? ORDER BY name',(user['id'],)).fetchall()
    return render_template('my_cards.html',user=user,cards=cards,folders=folders,card_locked=False,card_use_count=use_count,simple_id_exists=has_id)

@bp.post('/my-stuff/card/save')
def my_stuff_card_save():
    user=_current_user_for_stuff()
    if not user: abort(403)
    if not _cards_allowed(user):
        flash('Create your Open Road ID to keep using Card Maker.','error'); return redirect(url_for('public.my_stuff_cards'))
    db=get_db(); card_id=request.form.get('card_id','').strip(); title=request.form.get('title','').strip()[:100]; body=request.form.get('body','').strip(); color=request.form.get('color','lime'); folder_id=request.form.get('folder_id') or None
    font_style=request.form.get('font_style','bold').strip().lower(); shape_style=request.form.get('shape_style','sticky').strip().lower(); design_style=request.form.get('design_style','sunny').strip().lower(); background_style=request.form.get('background_style','solid').strip().lower()
    # QR is mandatory on exported cards; the user may only choose the optional brand footer.
    qr_enabled=1
    signature_enabled=1 if request.form.get('signature_enabled') in {'1','on','yes','true'} else 0
    decoration=request.form.get('decoration','spark').strip().lower()
    allowed_colors={'yellow','blue','pink','aqua','lime','orange','teal','white','red','purple','navy','mint','rose','coral','sky','ink','peach','lemon','violet','sand','cyan','magenta'}
    allowed_fonts={'bold','soft','mono','hand','serif','display','light','wide','typewriter','comic','caps','elegant'}
    allowed_shapes={'sticky','rounded','ticket','cloud','note','arch','diagonal','pill','flag','slant','polygon','ticketwide','wavy','stamp','circle','bubble','softbox','diary'}
    allowed_decoration={'spark','sun','moon','heart','bird','dots','none','verified','starblue','checkblue','crownblue','diamond','bolt','burst','seal'}
    if color not in allowed_colors: color='lime'
    if font_style not in allowed_fonts: font_style='bold'
    if shape_style not in allowed_shapes: shape_style='sticky'
    if design_style not in {'sunny','pastel','marker','minimal','night','playful'}: design_style='sunny'
    if background_style not in {'solid','gradient','sunset','ocean','paper','grid','dots','aurora','dark','cream','lavender','mintwash'}: background_style='solid'
    if decoration not in allowed_decoration: decoration='spark'
    if folder_id and not db.execute('SELECT id FROM stuff_folders WHERE id=? AND user_id=?',(folder_id,user['id'])).fetchone(): folder_id=None
    if not body and not title:
        flash('Write a topic or body on your card first.','error'); return redirect(url_for('public.my_stuff_edits_studio'))
    after_save=request.form.get('after_save','').strip().lower()
    if card_id:
        db.execute('UPDATE stuff_cards SET folder_id=?,title=?,body=?,color=?,font_style=?,shape_style=?,design_style=?,background_style=?,qr_enabled=?,signature_enabled=?,decoration=?,updated_at=? WHERE id=? AND user_id=?',(folder_id,title,body,color,font_style,shape_style,design_style,background_style,qr_enabled,signature_enabled,decoration,now(),card_id,user['id'])); msg='Card updated.'; saved_id=int(card_id)
    else:
        cur=db.execute('INSERT INTO stuff_cards(user_id,folder_id,title,body,color,font_style,shape_style,design_style,background_style,qr_enabled,signature_enabled,decoration,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(user['id'],folder_id,title,body,color,font_style,shape_style,design_style,background_style,qr_enabled,signature_enabled,decoration,now(),now())); msg='Card saved.'; saved_id=int(cur.lastrowid)
    db.commit(); flash(msg,'success')
    wants_json='application/json' in request.headers.get('Accept','') or request.headers.get('X-Requested-With')=='XMLHttpRequest'
    if after_save == 'png':
        download_url=url_for('public.my_stuff_card_download', card_id=saved_id, style=design_style, seed=saved_id, brand=('1' if signature_enabled else '0'))
        if wants_json:
            return jsonify(ok=True, saved_id=saved_id, message=msg, download_url=download_url)
        return redirect(download_url)
    if wants_json:
        return jsonify(ok=True, saved_id=saved_id, message=msg, download_url='')

    if after_save in {'stay','edits'}:
        return redirect(url_for('public.my_stuff_edits_studio', saved=saved_id))
    return redirect(url_for('public.my_stuff_cards'))



def _card_export_canvas(card, include_branding=True, qr_target='', brand_name='Open Road Adventures'):
    from PIL import Image, ImageDraw, ImageFont
    from io import BytesIO
    W,H=1600,1000
    palettes={
        'lime':('#dff579','#15201b','#82af43'),'aqua':('#a9e8df','#112027','#3faaa0'),
        'orange':('#ffc080','#261710','#cc6f33'),'pink':('#ffb9cf','#28121c','#cf5b83'),
        'blue':('#a9c9ff','#112031','#5679bc'),'yellow':('#ffe06a','#221d0d','#c2911d'),
        'teal':('#71d6c7','#10211f','#2e978d'),'white':('#fffdf8','#172028','#98a3a7'),
        'red':('#ff7a7a','#331616','#a83f3f'),'purple':('#c9a7ff','#281d3a','#8152c8'),'navy':('#223b67','#f8fbff','#6ea4ff'),'mint':('#b9f3d4','#153027','#55ae82'),'rose':('#f7a7ba','#34151d','#b64e6d'),'coral':('#ff9a7a','#351913','#bc5d43'),'sky':('#83d8ff','#142b38','#398cb4'),'ink':('#25313a','#fff','#83d8ff'),'peach':('#ffd1ad','#39251b','#cc7b44'),'lemon':('#f7f06a','#2d2b0e','#b9a92a'),'violet':('#a98bff','#24183f','#7653ba'),'sand':('#e8cf9d','#2f271a','#a9853b'),'cyan':('#69dce5','#122b2f','#329ca4'),'magenta':('#e58cc7','#351a2d','#ad4f91')}
    bg,ink,accent=palettes.get(card['color'],palettes['lime'])
    font_style=getattr(card,'_export_font','bold') or 'bold'
    shape=getattr(card,'_export_shape','sticky') or 'sticky'
    design=getattr(card,'_export_design','sunny') or 'sunny'
    background=getattr(card,'_export_background','solid') or 'solid'
    decoration=getattr(card,'_export_decoration','spark') or 'spark'
    custom_bg=getattr(card,'_export_custom_bg','') or ''
    custom_text=getattr(card,'_export_custom_text','') or ''
    text_align=getattr(card,'_export_text_align','left') or 'left'
    try: font_scale=max(75,min(140,int(getattr(card,'_export_font_scale',100) or 100)))
    except (TypeError,ValueError): font_scale=100
    border_style=getattr(card,'_export_border','classic') or 'classic'
    texture_style=getattr(card,'_export_texture','none') or 'none'
    bgc=tuple(int(bg.lstrip('#')[i:i+2],16) for i in (0,2,4)); inkc=tuple(int(ink.lstrip('#')[i:i+2],16) for i in (0,2,4)); acc=tuple(int(accent.lstrip('#')[i:i+2],16) for i in (0,2,4))
    if custom_bg:
        try: bgc=tuple(int(custom_bg.lstrip('#')[i:i+2],16) for i in (0,2,4))
        except Exception: pass
    if custom_text:
        try: inkc=tuple(int(custom_text.lstrip('#')[i:i+2],16) for i in (0,2,4))
        except Exception: pass
    if design=='night': inkc,acc=(248,251,250),(121,225,211)
    if background=='dark': bgc,inkc=(37,49,58),(248,251,250)
    img=Image.new('RGB',(W,H),(245,245,239)); d=ImageDraw.Draw(img)
    bg_overlays={
        'gradient':((255,255,255),(210,245,235)),
        'sunset':((255,210,150),(205,170,255)),
        'ocean':((165,235,255),(105,150,220)),
        'paper':((255,255,250),(235,240,230)),
        'dark':((28,40,48),(15,24,30)),
        'cream':((255,249,223),(245,237,206)),
        'lavender':((241,233,255),(220,207,255)),
        'mintwash':((234,255,247),(200,241,224))
    }
    if background in bg_overlays:
        a,b=bg_overlays[background]
        for yy in range(H):
            t=yy/max(1,H-1); col=tuple(int(a[i]*(1-t)+b[i]*t) for i in range(3)); d.line((0,yy,W,yy),fill=col)
    elif background=='grid':
        d.rectangle((0,0,W,H),fill=(247,247,242))
        for x in range(0,W,55): d.line((x,0,x,H),fill=(220,225,221),width=1)
        for y2 in range(0,H,55): d.line((0,y2,W,y2),fill=(220,225,221),width=1)
    elif background=='dots':
        d.rectangle((0,0,W,H),fill=(247,249,245))
        for yy in range(20,H,36):
            for xx in range(20,W,36): d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=(205,213,209))
    elif background=='aurora':
        d.rectangle((0,0,W,H),fill=(238,246,241))
        d.ellipse((-240,-180,700,700),fill=(180,245,224))
        d.ellipse((930,400,1800,1150),fill=(195,175,255))
    # soft playful background to match the live card stage
    if design in {'sunny','playful','pastel'}:
        d.ellipse((-180,-140,500,500),fill=tuple(min(255,c+10) for c in bgc))
        d.ellipse((1210,640,1820,1240),fill=tuple(min(255,c+14) for c in bgc))
    elif design=='night': d.rectangle((0,0,W,H),fill=(23,35,43))
    box=(150,100,1450,900)
    shadow=(box[0]+18,box[1]+22,box[2]+18,box[3]+22)
    d.rounded_rectangle(shadow,radius=44,fill=(54,62,62))
    if shape=='rounded': d.rounded_rectangle(box,radius=90,fill=bgc,outline=inkc,width=7)
    elif shape in {'circle','bubble'}:
        d.ellipse(box,fill=bgc,outline=inkc,width=7)
    elif shape in {'diagonal','slant','polygon','flag','ticketwide'}:
        if shape=='diagonal': pts=[(180,100),(1420,140),(1450,860),(150,900)]
        elif shape=='slant': pts=[(270,100),(1450,160),(1330,900),(150,840)]
        elif shape=='flag': pts=[(150,100),(1450,100),(1330,500),(1450,900),(150,900),(270,500)]
        elif shape=='polygon': pts=[(250,100),(1350,100),(1450,200),(1450,800),(1350,900),(250,900),(150,800),(150,200)]
        else: pts=[(180,100),(1420,100),(1420,250),(1470,250),(1470,750),(1420,750),(1420,900),(180,900),(180,750),(130,750),(130,250),(180,250)]
        d.polygon(pts,fill=bgc); d.line(pts+[pts[0]],fill=inkc,width=7,joint='curve')
    elif shape=='wavy':
        d.rounded_rectangle(box,radius=70,fill=bgc,outline=inkc,width=7)
    elif shape=='stamp':
        d.rounded_rectangle(box,radius=30,fill=bgc,outline=inkc,width=7)
        for x in range(175,1430,55): d.ellipse((x-8,92,x+8,108),fill=inkc); d.ellipse((x-8,892,x+8,908),fill=inkc)
    elif shape=='softbox':
        d.rounded_rectangle(box,radius=55,fill=bgc,outline=inkc,width=7)
    elif shape=='diary':
        d.rounded_rectangle(box,radius=24,fill=bgc,outline=inkc,width=7); d.rectangle((150,100,205,900),fill=inkc)
    elif shape=='pill': d.rounded_rectangle(box,radius=400,fill=bgc,outline=inkc,width=7)
    elif shape=='ticket':
        d.rounded_rectangle(box,radius=28,fill=bgc,outline=inkc,width=7)
        for yy in range(170,850,78):
            d.ellipse((139,yy-14,167,yy+14),fill=(245,245,239)); d.ellipse((1433,yy-14,1461,yy+14),fill=(245,245,239))
    elif shape=='cloud':
        pts=[(175,270),(240,175),(360,150),(470,205),(585,150),(700,165),(805,115),(965,150),(1070,205),(1200,145),(1360,220),(1435,315),(1408,735),(1285,845),(1120,875),(980,835),(815,900),(650,855),(500,895),(365,840),(235,865),(170,730)]
        d.polygon(pts,fill=bgc); d.line(pts+[pts[0]],fill=inkc,width=7,joint='curve')
    elif shape=='note':
        d.rectangle(box,fill=bgc,outline=inkc,width=7)
        for yy in range(220,820,72): d.line((215,yy,1385,yy),fill=tuple(min(255,c+18) for c in bgc),width=2)
    elif shape=='arch':
        d.rectangle((150,270,1450,900),fill=bgc,outline=inkc,width=7); d.ellipse((150,10,1450,510),fill=bgc,outline=inkc,width=7)
    else:
        d.rounded_rectangle(box,radius=26,fill=bgc,outline=inkc,width=7)
    # Independent card background styling: keep Colour as the base tone while the
    # Background choice adds its own visual treatment.  This is deliberately
    # applied after the shape is drawn so the live editor and PNG have the same feel.
    bg_tints={
        'gradient':((255,255,255),.34),'sunset':((255,165,185),.48),'ocean':((100,195,235),.45),
        'paper':((250,248,235),.42),'grid':((235,240,236),.46),'dots':((246,248,244),.36),
        'aurora':((190,180,250),.42),'dark':((24,34,42),.72),'cream':((255,247,215),.42),
        'lavender':((226,214,255),.42),'mintwash':((208,248,229),.42)
    }
    if background in bg_tints:
        tint,alpha=bg_tints[background]
        # Paint a soft transparent tint layer with the same shape footprint.
        layer=Image.new('RGBA',(W,H),(0,0,0,0)); ld=ImageDraw.Draw(layer)
        fill=tuple(tint)+(int(255*alpha),)
        if shape in {'circle','bubble'}: ld.ellipse(box,fill=fill)
        elif shape in {'diagonal','slant','polygon','flag','ticketwide','cloud'}:
            ld.polygon(pts if 'pts' in locals() else [(box[0],box[1]),(box[2],box[1]),(box[2],box[3]),(box[0],box[3])],fill=fill)
        elif shape=='pill': ld.rounded_rectangle(box,radius=400,fill=fill)
        elif shape=='rounded': ld.rounded_rectangle(box,radius=90,fill=fill)
        elif shape=='ticket': ld.rounded_rectangle(box,radius=28,fill=fill)
        elif shape in {'stamp','softbox','wavy'}: ld.rounded_rectangle(box,radius=45,fill=fill)
        elif shape=='arch': ld.rectangle((150,270,1450,900),fill=fill); ld.ellipse((150,10,1450,510),fill=fill)
        elif shape=='diary': ld.rounded_rectangle(box,radius=24,fill=fill)
        elif shape=='note': ld.rectangle(box,fill=fill)
        else: ld.rounded_rectangle(box,radius=26,fill=fill)
        img=Image.alpha_composite(img.convert('RGBA'),layer).convert('RGB'); d=ImageDraw.Draw(img)
        if background=='grid':
            for x in range(175,1430,55): d.line((x,120,x,880),fill=(20,33,30),width=1)
            for yy in range(140,880,55): d.line((180,yy,1420,yy),fill=(20,33,30),width=1)
        elif background=='dots':
            for yy in range(145,875,42):
                for xx in range(180,1425,42): d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=(80,90,86))
    if border_style == 'thin':
        outline_w=3
    elif border_style == 'dashed':
        outline_w=2
        for xx in range(box[0],box[2],35): d.line((xx,box[1],min(xx+18,box[2]),box[1]),fill=inkc,width=outline_w)
        for xx in range(box[0],box[2],35): d.line((xx,box[3],min(xx+18,box[2]),box[3]),fill=inkc,width=outline_w)
    elif border_style == 'double':
        d.rounded_rectangle((box[0]+12,box[1]+12,box[2]-12,box[3]-12),radius=32,outline=inkc,width=3)
    elif border_style == 'none':
        pass
    if texture_style == 'lines':
        for yy in range(box[1]+30,box[3],34): d.line((box[0]+25,yy,box[2]-25,yy),fill=tuple(min(255,int(v*.88)) for v in bgc),width=1)
    elif texture_style == 'soft-dots':
        for yy in range(box[1]+30,box[3],38):
            for xx in range(box[0]+30,box[2],38): d.ellipse((xx-2,yy-2,xx+2,yy+2),fill=tuple(min(255,int(v*.86)) for v in bgc))
    elif texture_style == 'grid':
        for xx in range(box[0]+20,box[2],50): d.line((xx,box[1]+15,xx,box[3]-15),fill=tuple(min(255,int(v*.9)) for v in bgc),width=1)
        for yy in range(box[1]+20,box[3],50): d.line((box[0]+15,yy,box[2]-15,yy),fill=tuple(min(255,int(v*.9)) for v in bgc),width=1)

    font_map={
        'bold':'/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        'soft':'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        'mono':'/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        'hand':'/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf',
        'serif':'/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf','display':'/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf','light':'/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf','wide':'/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf','typewriter':'/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf','comic':'/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','caps':'/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','elegant':'/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf'
    }
    def F(style,size):
        p=font_map.get(style,font_map['bold'])
        try:return ImageFont.truetype(p,size)
        except OSError:return ImageFont.load_default()
    align=text_align if text_align in {'left','center','right'} else ('center' if design in {'pastel','playful','night'} else 'left'); tx={'left':245,'center':800,'right':1355}[align]; anchor={'left':'la','center':'ma','right':'ra'}[align]
    title=card['title'] or ''; body=card['body'] or ''
    title_font=F(font_style,int(82*font_scale/100)); body_font=F('mono' if font_style=='mono' else 'soft',int(38*font_scale/100)); small=F('bold',24)
    def wrap(text,font,maxw):
        lines=[]; cur=''
        for word in str(text).split():
            test=(cur+' '+word).strip()
            if d.textbbox((0,0),test,font=font)[2] <= maxw: cur=test
            else:
                if cur: lines.append(cur)
                cur=word
        if cur: lines.append(cur)
        return lines
    tlines=wrap(title,title_font,1080)[:3] if title else []
    y=300
    for line in tlines: d.text((tx,y),line,font=title_font,fill=inkc,anchor=anchor); y+=94
    blines=wrap(body,body_font,1090)[:8] if body else []
    y=(y+20 if tlines else 450)
    for line in blines: d.text((tx,y),line,font=body_font,fill=inkc,anchor=anchor); y+=52
    # tiny decorative mark
    deco={'spark':'✦','sun':'☼','moon':'☾','heart':'♡','bird':'⌁','dots':'•••','none':'','verified':'✓','starblue':'★','checkblue':'✓','crownblue':'♛','diamond':'◆','bolt':'⚡','burst':'✹','seal':'●'}.get(decoration,'✦')
    if deco:
        df=F('bold',38); d.text((1280,160),deco,font=df,fill=acc,anchor='mm')
    # QR is mandatory on every card export. Branding is optional.
    try:
        from .qr import make_qr_bytes
        qr=Image.open(BytesIO(make_qr_bytes(qr_target or 'https://openroad.adventures'))).convert('RGB').resize((80,80),Image.Resampling.NEAREST)
        qx,qy=1360,790
        d.rounded_rectangle((qx-8,qy-8,qx+88,qy+88),radius=10,fill=(255,255,255),outline=inkc,width=3); img.paste(qr,(qx,qy))
    except Exception: pass
    if include_branding:
        d.line((245,820,1190,820),fill=inkc,width=2)
        d.text((245,846),'✦',font=small,fill=acc); d.text((275,847),brand_name.upper(),font=small,fill=inkc)
        d.text((1125,846),'✦',font=small,fill=acc)
    return img

@bp.get('/my-stuff/card/<int:card_id>/download')
def my_stuff_card_download(card_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    if not _cards_allowed(user): abort(403)
    row=get_db().execute('SELECT * FROM stuff_cards WHERE id=? AND user_id=?',(card_id,user['id'])).fetchone()
    if not row: abort(404)
    style=request.args.get('style','sunrise').strip().lower()
    allowed={'sunrise','editorial','poster','minimal','playful','night','sunny','pastel','marker'}
    if style not in allowed: style='sunny'
    try: seed=int(request.args.get('seed','0'))
    except ValueError: seed=0
    include=(bool(row['signature_enabled']) if 'signature_enabled' in row.keys() else True)
    if 'brand' in request.args and request.args.get('brand','1') in {'0','false','no'}: include=False
    class CardProxy:
        def __init__(self,r,style,seed):
            self._r=r; self._export_style=style; self._export_seed=seed
            self._export_font=r['font_style'] if 'font_style' in r.keys() else 'bold'
            self._export_shape=r['shape_style'] if 'shape_style' in r.keys() else 'sticky'
            self._export_design=r['design_style'] if 'design_style' in r.keys() else 'sunny'
            self._export_background=r['background_style'] if 'background_style' in r.keys() else 'solid'
            self._export_qr=bool(r['qr_enabled']) if 'qr_enabled' in r.keys() else True
            self._export_signature=bool(r['signature_enabled']) if 'signature_enabled' in r.keys() else True
            self._export_decoration=r['decoration'] if 'decoration' in r.keys() else 'spark'
            self._export_custom_bg=r['custom_bg'] if 'custom_bg' in r.keys() else ''
            self._export_custom_text=r['custom_text'] if 'custom_text' in r.keys() else ''
            self._export_text_align=r['text_align'] if 'text_align' in r.keys() else 'left'
            self._export_font_scale=r['font_scale'] if 'font_scale' in r.keys() else 100
            self._export_border=r['border_style'] if 'border_style' in r.keys() else 'classic'
            self._export_texture=r['texture_style'] if 'texture_style' in r.keys() else 'none'
        def __getitem__(self,k): return self._r[k]
    card=CardProxy(row,style,seed)
    image=_card_export_canvas(card,include,url_for('public.home', _external=True),current_app.config.get('BRAND_NAME','Open Road Adventures'))
    out=BytesIO(); image.save(out,'PNG',optimize=True); out.seek(0)
    safe=re.sub(r'[^a-zA-Z0-9_-]+','-',row['title']).strip('-')[:55] or 'quick-card'
    return send_file(out,mimetype='image/png',as_attachment=True,download_name=f'open-road-{safe}.png',max_age=0)

@bp.post('/my-stuff/card/<int:card_id>/delete')
def my_stuff_card_delete(card_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    if not _cards_allowed(user): abort(403)
    db=get_db(); row=db.execute('SELECT image_filename FROM stuff_cards WHERE id=? AND user_id=?',(card_id,user['id'])).fetchone(); db.execute('DELETE FROM stuff_cards WHERE id=? AND user_id=?',(card_id,user['id'])); db.commit()
    if row and row['image_filename']:
        try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'],row['image_filename']))
        except OSError: pass
    flash('Card deleted.','success'); return redirect(url_for('public.my_stuff_cards'))

@bp.get('/my-stuff/copy-paste')
def my_stuff_copy_paste():
    user=_current_user_for_stuff()
    user=_stuff_use_and_context(user,'stuff_copy_uses')
    db=get_db(); copies=db.execute('SELECT * FROM saved_copies WHERE user_id=? AND id IN (SELECT MAX(id) FROM saved_copies WHERE user_id=? GROUP BY label,value) ORDER BY updated_at DESC,id DESC',(user['id'],user['id'])).fetchall()
    edit_id=request.args.get('edit','').strip(); edit_item=db.execute('SELECT * FROM saved_copies WHERE id=? AND user_id=?',(edit_id,user['id'])).fetchone() if edit_id.isdigit() else None
    return render_template('my_copy_paste.html',user=user,copies=copies,edit_item=edit_item,simple_id_exists=_stuff_id_ready(user),use_count=int(user['stuff_copy_uses'] or 0))

@bp.post('/my-stuff/copy/save')
def my_stuff_copy_save():
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); item_id=request.form.get('item_id','').strip(); label=request.form.get('label','').strip()[:80]; value=request.form.get('value','').strip(); note=request.form.get('note','').strip()[:240]
    if not label or not value: flash('Add a name and the number or code you want to keep.','error'); return redirect(url_for('public.my_stuff_copy_paste'))
    if item_id:
        db.execute('UPDATE saved_copies SET label=?,value=?,note=?,updated_at=? WHERE id=? AND user_id=?',(label,value,note,now(),item_id,user['id'])); msg='Saved item updated.'
    else:
        existing=db.execute('SELECT id FROM saved_copies WHERE user_id=? AND label=? AND value=? ORDER BY id DESC LIMIT 1',(user['id'],label,value)).fetchone()
        if existing:
            db.execute('UPDATE saved_copies SET note=?,updated_at=? WHERE id=? AND user_id=?',(note,now(),existing['id'],user['id'])); msg='Already saved — updated.'
        else:
            db.execute('INSERT INTO saved_copies(user_id,label,value,note,created_at,updated_at) VALUES(?,?,?,?,?,?)',(user['id'],label,value,note,now(),now())); msg='Saved to Copy & Paste.'
    db.commit(); flash(msg,'success'); return redirect(url_for('public.my_stuff_copy_paste'))

@bp.post('/my-stuff/copy/<int:item_id>/delete')
def my_stuff_copy_delete(item_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); db.execute('DELETE FROM saved_copies WHERE id=? AND user_id=?',(item_id,user['id'])); db.commit(); flash('Saved item deleted.','success'); return redirect(url_for('public.my_stuff_copy_paste'))

@bp.get('/my-stuff/color-cards')
def my_stuff_color_cards():
    user=_current_user_for_stuff()
    user=_stuff_use_and_context(user,'stuff_card_uses')
    use_count=int(user['stuff_card_uses'] or 0)
    has_id=_stuff_id_ready(user)
    if not has_id and use_count > 5:
        _cards=get_db().execute('SELECT * FROM stuff_cards WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user['id'],)).fetchall()
        import base64 as _b64
        qr_b64=_b64.b64encode(make_qr_bytes(url_for('public.home', _external=True))).decode('ascii')
        return render_template('my_color_cards.html',user=user,cards=_cards,card_locked=True,card_use_count=use_count,qr_b64=qr_b64)
    cards=get_db().execute('SELECT * FROM stuff_cards WHERE user_id=? ORDER BY updated_at DESC,id DESC',(user['id'],)).fetchall()
    import base64 as _b64
    qr_b64=_b64.b64encode(make_qr_bytes(url_for('public.home', _external=True))).decode('ascii')
    return render_template('my_color_cards.html',user=user,cards=cards,card_locked=False,card_use_count=use_count,qr_b64=qr_b64)

@bp.post('/my-stuff/color-card/save')
def my_stuff_color_card_save():
    user=_current_user_for_stuff()
    if not user: abort(403)
    if not _cards_allowed(user):
        return jsonify(ok=False,message='Create your Open Road ID to keep using Color Cards.'),403
    db=get_db()
    card_id=request.form.get('card_id','').strip()
    title=request.form.get('title','').strip()[:100]
    body=request.form.get('body','').strip()[:1000]
    color=request.form.get('color','yellow').strip().lower()
    font_style=request.form.get('font_style','bold').strip().lower()
    shape_style=request.form.get('shape_style','sticky').strip().lower()
    design_style=request.form.get('design_style','sunny').strip().lower()
    background_style=request.form.get('background_style','solid').strip().lower()
    decoration=request.form.get('decoration','spark').strip().lower()
    custom_bg=request.form.get('custom_bg','').strip()[:20]
    custom_text=request.form.get('custom_text','').strip()[:20]
    text_align=request.form.get('text_align','left').strip().lower()
    try: font_scale=max(75,min(140,int(request.form.get('font_scale','100'))))
    except (TypeError,ValueError): font_scale=100
    border_style=request.form.get('border_style','classic').strip().lower()
    texture_style=request.form.get('texture_style','none').strip().lower()
    signature_enabled=1 if request.form.get('signature_enabled') in {'1','on','yes','true'} else 0
    allowed_colors={'yellow','blue','pink','aqua','lime','orange','teal','white','red','purple','navy','mint','rose','coral','sky','ink','peach','lemon','violet','sand','cyan','magenta'}
    allowed_fonts={'bold','soft','mono','hand','serif','display','light','wide','typewriter','comic','caps','elegant'}
    allowed_shapes={'sticky','rounded','ticket','cloud','note','arch','diagonal','pill','flag','slant','polygon','ticketwide','wavy','stamp','circle','bubble','softbox','diary'}
    allowed_designs={'sunny','pastel','marker','minimal','night','playful'}
    allowed_backgrounds={'solid','clean','gradient','sunset','ocean','paper','grid','dots','aurora','dark','cream','lavender','mintwash'}
    allowed_decos={'spark','sun','moon','heart','bird','dots','none','verified','starblue','checkblue','crownblue','diamond','bolt','burst','seal'}
    allowed_align={'left','center','right'}
    allowed_border={'classic','thin','dashed','double','none'}
    allowed_texture={'none','soft-dots','lines','grid','paper'}
    if color not in allowed_colors: color='yellow'
    if font_style not in allowed_fonts: font_style='bold'
    if shape_style not in allowed_shapes: shape_style='sticky'
    if design_style not in allowed_designs: design_style='sunny'
    if background_style not in allowed_backgrounds: background_style='solid'
    if decoration not in allowed_decos: decoration='spark'
    if text_align not in allowed_align: text_align='left'
    if border_style not in allowed_border: border_style='classic'
    if texture_style not in allowed_texture: texture_style='none'
    import re as _re
    def clean_hex(v, default=''):
        return v if _re.fullmatch(r'#?[0-9a-fA-F]{6}',v or '') else default
    custom_bg=clean_hex(custom_bg,'')
    custom_text=clean_hex(custom_text,'')
    if not title and not body: return jsonify(ok=False,message='Write a topic or body first.'),400
    cols=['title','body','color','font_style','shape_style','design_style','background_style','qr_enabled','signature_enabled','decoration','custom_bg','custom_text','text_align','font_scale','border_style','texture_style','updated_at']
    vals=[title,body,color,font_style,shape_style,design_style,background_style,1,signature_enabled,decoration,custom_bg,custom_text,text_align,font_scale,border_style,texture_style,now()]
    if card_id:
        owned=db.execute('SELECT id FROM stuff_cards WHERE id=? AND user_id=?',(card_id,user['id'])).fetchone()
        if not owned: return jsonify(ok=False,message='That card was not found.'),404
        sets=', '.join(f'{c}=?' for c in cols)
        db.execute(f'UPDATE stuff_cards SET {sets} WHERE id=? AND user_id=?',tuple(vals+[card_id,user['id']]))
        saved_id=int(card_id); msg='Color Card updated.'
    else:
        placeholders=','.join('?'*len(vals))
        cur=db.execute(f'INSERT INTO stuff_cards(user_id,{",".join(cols)}) VALUES(?,{placeholders})',tuple([user['id']]+vals))
        saved_id=int(cur.lastrowid); msg='Color Card saved.'
    db.commit()
    download_url=url_for('public.my_stuff_card_download',card_id=saved_id,style=design_style,seed=saved_id,brand=('1' if signature_enabled else '0'))
    return jsonify(ok=True,saved_id=saved_id,message=msg,download_url=download_url)

@bp.post('/my-stuff/color-card/<int:card_id>/delete')
def my_stuff_color_card_delete(card_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); db.execute('DELETE FROM stuff_cards WHERE id=? AND user_id=?',(card_id,user['id'])); db.commit()
    return redirect(url_for('public.my_stuff_color_cards'))

@bp.get('/my-stuff/edits-studio')
def my_stuff_edits_studio():
    # Legacy URL retained so old bookmarks do not break; the old editor is no longer exposed.
    return redirect(url_for('public.my_stuff_color_cards'))

@bp.post('/my-stuff/image')
def my_stuff_image_upload():
    user=_current_user_for_stuff()
    if not user: abort(403)
    f=request.files.get('image'); operation=request.form.get('operation','clean')
    if not f or not f.filename: flash('Choose an image first.','error'); return redirect(url_for('public.my_stuff_edits_studio'))
    if operation not in {'clean','grayscale','web'}: operation='clean'
    new_id=None
    try:
        from PIL import Image, ImageOps
        raw=f.read(); from io import BytesIO
        source=Image.open(BytesIO(raw)); source.verify(); source=Image.open(BytesIO(raw)).convert('RGB'); source=ImageOps.exif_transpose(source)
        if operation=='grayscale': source=ImageOps.grayscale(source).convert('RGB')
        elif operation=='web': source.thumbnail((1600,1600), Image.Resampling.LANCZOS)
        out_name=_safe_stuff_image_name(f.filename); stuff_dir=os.path.join(current_app.config['UPLOAD_FOLDER'],'stuff',str(user['id'])); os.makedirs(stuff_dir,exist_ok=True); out_path=os.path.join(stuff_dir,out_name); source.save(out_path,'JPEG',quality=91,optimize=True)
        logical=os.path.join('stuff',str(user['id']),out_name); db=get_db(); db.execute('INSERT INTO stuff_images(user_id,original_name,filename,operation,created_at) VALUES(?,?,?,?,?)',(user['id'],f.filename,logical,operation,now())); db.commit(); flash('Image processed. Metadata has been removed from the new file.','success')
    except Exception: flash('That image could not be processed. Try a JPG, PNG, WEBP or GIF under 12 MB.','error')
    return redirect(url_for('public.my_stuff_edits_studio', image=int(new_id)) if new_id else url_for('public.my_stuff_edits_studio'))

@bp.get('/my-stuff/image/<int:image_id>')
def my_stuff_image(image_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    row=get_db().execute('SELECT * FROM stuff_images WHERE id=? AND user_id=?',(image_id,user['id'])).fetchone()
    if not row: abort(404)
    path=os.path.join(current_app.config['UPLOAD_FOLDER'],row['filename']); return send_file(path,as_attachment=True,download_name='open-road-'+os.path.basename(path),mimetype='image/jpeg')

@bp.post('/my-stuff/image/<int:image_id>/delete')
def my_stuff_image_delete(image_id):
    user=_current_user_for_stuff()
    if not user: abort(403)
    db=get_db(); row=db.execute('SELECT filename FROM stuff_images WHERE id=? AND user_id=?',(image_id,user['id'])).fetchone(); db.execute('DELETE FROM stuff_images WHERE id=? AND user_id=?',(image_id,user['id'])); db.commit()
    if row:
        try: os.remove(os.path.join(current_app.config['UPLOAD_FOLDER'],row['filename']))
        except OSError: pass
    flash('Image history item deleted.','success'); return redirect(url_for('public.my_stuff_edits_studio'))

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

@bp.get('/sw.js')
def service_worker():
    resp = send_from_directory(current_app.static_folder, 'sw.js', mimetype='application/javascript')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@bp.get('/manifest.json')
def manifest():
    return jsonify(name=current_app.config['BRAND_NAME'],short_name='Open Road',start_url='/',scope='/',display='standalone',theme_color='#12212b',background_color='#fbf6ea',orientation='portrait-primary',categories=['travel','lifestyle','utilities'],icons=[{'src':url_for('static',filename='icon.svg'),'sizes':'any','type':'image/svg+xml','purpose':'any maskable'}])

@bp.get('/offline')
def offline_app():
    return render_template('offline_app.html')

@bp.get('/offline/my-stuff')
def offline_my_stuff():
    return render_template('offline_my_stuff.html')
