from pathlib import Path
p=Path('/mnt/data/work37')

# 1) DB schema additions
f=p/'app/db.py'; s=f.read_text()
s=s.replace("CREATE TABLE IF NOT EXISTS visits (\n id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_key TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL\n);",
"CREATE TABLE IF NOT EXISTS visits (\n id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_key TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,\n user_id INTEGER, name TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '',\n method TEXT DEFAULT 'GET', referrer TEXT DEFAULT '', user_agent TEXT DEFAULT '', ip_address TEXT DEFAULT '',\n device_model TEXT DEFAULT '', platform TEXT DEFAULT '', browser TEXT DEFAULT ''\n);\nCREATE TABLE IF NOT EXISTS error_logs (\n id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL, status_code INTEGER NOT NULL,\n path TEXT NOT NULL, method TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL,\n traceback TEXT DEFAULT '', user_id INTEGER, visitor_key TEXT DEFAULT '', user_agent TEXT DEFAULT '', ip_address TEXT DEFAULT ''\n);")
# safe upgrades
needle="        upgrades = {\n            'users': {"
insert="        upgrades = {\n            'visits': {\n                'user_id': 'ALTER TABLE visits ADD COLUMN user_id INTEGER',\n                'name': \"ALTER TABLE visits ADD COLUMN name TEXT DEFAULT ''\",\n                'email': \"ALTER TABLE visits ADD COLUMN email TEXT DEFAULT ''\",\n                'phone': \"ALTER TABLE visits ADD COLUMN phone TEXT DEFAULT ''\",\n                'method': \"ALTER TABLE visits ADD COLUMN method TEXT DEFAULT 'GET'\",\n                'referrer': \"ALTER TABLE visits ADD COLUMN referrer TEXT DEFAULT ''\",\n                'user_agent': \"ALTER TABLE visits ADD COLUMN user_agent TEXT DEFAULT ''\",\n                'ip_address': \"ALTER TABLE visits ADD COLUMN ip_address TEXT DEFAULT ''\",\n                'device_model': \"ALTER TABLE visits ADD COLUMN device_model TEXT DEFAULT ''\",\n                'platform': \"ALTER TABLE visits ADD COLUMN platform TEXT DEFAULT ''\",\n                'browser': \"ALTER TABLE visits ADD COLUMN browser TEXT DEFAULT ''\",\n            },\n            'error_logs': {},\n            'users': {"
s=s.replace(needle,insert)
f.write_text(s)

# 2) public request analytics + client hint endpoint
f=p/'app/routes.py'; s=f.read_text()
old="""def log_visit():\n    if request.path.startswith('/static/') or request.path.startswith('/media/') or request.path.startswith('/api/'):\n        return\n    key=request.cookies.get('visitor_key') or secrets.token_urlsafe(16)\n    db=get_db(); db.execute('INSERT INTO visits(visitor_key,path,created_at) VALUES(?,?,?)',(key,request.path,now())); db.commit(); request._visitor_key=key\n"""
new="""def _request_ip():\n    # Keep the first proxy address for admin diagnostics; deployment may sit behind a proxy.\n    forwarded=request.headers.get('X-Forwarded-For','')\n    return (forwarded.split(',')[0].strip() if forwarded else request.remote_addr or '')[:120]\n\ndef _ua_details(ua=''):\n    ua=ua or ''\n    platform='Android' if 'Android' in ua else ('iPhone/iPad' if ('iPhone' in ua or 'iPad' in ua) else ('Windows' if 'Windows' in ua else ('Mac' if 'Macintosh' in ua else ('Linux' if 'Linux' in ua else 'Other'))))\n    browser='Chrome' if 'Chrome/' in ua and 'Edg/' not in ua else ('Edge' if 'Edg/' in ua else ('Safari' if 'Safari/' in ua and 'Chrome/' not in ua else ('Firefox' if 'Firefox/' in ua else 'Other')))\n    model=''\n    m=re.search(r'Android[^;)]*;\\s*(?:[a-z]{2}-[A-Z]{2};\\s*)?(?:wv;\\s*)?([^;\\)]+)',ua)\n    if m: model=m.group(1).strip()\n    if model in {'K','wv','Mobile'}: model=''\n    return model[:120],platform,browser\n\ndef log_visit():\n    if request.path.startswith(('/static/','/media/','/api/','/pulse_receiver','/health')):\n        return\n    key=request.cookies.get('visitor_key') or secrets.token_urlsafe(16)\n    me=None\n    try:\n        uid=session.get('user_id')\n        if uid: me=get_db().execute('SELECT id,name,email,phone FROM users WHERE id=? AND deleted_at IS NULL',(uid,)).fetchone()\n    except Exception:\n        me=None\n    model,platform,browser=_ua_details(request.headers.get('User-Agent',''))\n    db=get_db(); cur=db.execute(\n        'INSERT INTO visits(visitor_key,path,created_at,user_id,name,email,phone,method,referrer,user_agent,ip_address,device_model,platform,browser) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',\n        (key,request.path,now(), me['id'] if me else None, me['name'] if me else '', me['email'] if me else '', me['phone'] if me else '', request.method, request.referrer or '', request.headers.get('User-Agent','')[:600], _request_ip(), model, platform, browser))\n    db.commit(); request._visitor_key=key; request._visit_id=cur.lastrowid\n"""
if old not in s: raise SystemExit('log_visit block not found')
s=s.replace(old,new)
# add telemetry endpoint after pulse receiver
needle="@bp.route('/pulse_receiver',methods=['GET','POST'])\ndef pulse_receiver(): return jsonify(ok=True, received=True)\n"
replacement=needle+"""\n@bp.post('/telemetry')\ndef telemetry():\n    vid=getattr(request,'_visit_id',None)\n    if not vid: return jsonify(ok=True)\n    data=request.get_json(silent=True) or {}\n    model=str(data.get('model','') or '')[:120]\n    platform=str(data.get('platform','') or '')[:120]\n    browser=str(data.get('browser','') or '')[:120]\n    db=get_db(); db.execute('UPDATE visits SET device_model=COALESCE(NULLIF(?,\'\'),device_model), platform=COALESCE(NULLIF(?,\'\'),platform), browser=COALESCE(NULLIF(?,\'\'),browser) WHERE id=?',(model,platform,browser,vid)); db.commit()\n    return jsonify(ok=True)\n"""
s=s.replace(needle,replacement)
f.write_text(s)

# 3) Error handlers
f=p/'app/__init__.py'; s=f.read_text()
s=s.replace('import os, secrets\n','import os, secrets, logging, traceback\n')
old="""    @app.errorhandler(404)\n    def not_found(_): return __import__('flask').render_template('not_found.html'), 404\n    @app.errorhandler(500)\n    def server_error(_): return __import__('flask').render_template('error.html'), 500\n"""
new="""    @app.errorhandler(404)\n    def not_found(err):\n        try:\n            db=get_db(); uid=request.cookies.get('visitor_key','')\n            db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',\n                       (__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),404,request.path,request.method,type(err).__name__,str(err),'',request.args.get('_uid'),uid,request.headers.get('User-Agent','')[:600],request.remote_addr or '')); db.commit()\n        except Exception: app.logger.exception('Could not persist 404 analytics')\n        return __import__('flask').render_template('not_found.html'), 404\n    @app.errorhandler(500)\n    def server_error(err):\n        tb=traceback.format_exc()\n        try:\n            db=get_db(); db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',\n                       (__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),500,request.path,request.method,type(err).__name__,str(err),tb[-12000:],request.cookies.get('_uid'),request.cookies.get('visitor_key',''),request.headers.get('User-Agent','')[:600],request.remote_addr or '')); db.commit()\n        except Exception: app.logger.exception('Could not persist 500 analytics')\n        return __import__('flask').render_template('error.html'), 500\n"""
if old not in s: raise SystemExit('error block not found')
s=s.replace(old,new)
f.write_text(s)

# 4) Admin dashboard query + templates
f=p/'app/admin.py'; s=f.read_text()
old="""    trips=db.execute('SELECT * FROM trips ORDER BY date').fetchall(); destinations=db.execute('SELECT * FROM destinations ORDER BY sort_order,id').fetchall(); posts=db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall(); services=db.execute('SELECT * FROM services ORDER BY sort_order,id').fetchall(); service_requests=db.execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id ORDER BY sr.id DESC LIMIT 12').fetchall()\n    return render_template('admin_dashboard.html',stats=stats,settings=rows,trips=trips,destinations=destinations,posts=posts,services=services,service_requests=service_requests)\n"""
new="""    trips=db.execute('SELECT * FROM trips ORDER BY date').fetchall(); destinations=db.execute('SELECT * FROM destinations ORDER BY sort_order,id').fetchall(); posts=db.execute('SELECT * FROM posts ORDER BY id DESC').fetchall(); services=db.execute('SELECT * FROM services ORDER BY sort_order,id').fetchall(); service_requests=db.execute('SELECT sr.*,s.title FROM service_requests sr JOIN services s ON s.id=sr.service_id ORDER BY sr.id DESC LIMIT 12').fetchall()\n    visits=db.execute('SELECT * FROM visits ORDER BY id DESC LIMIT 35').fetchall()\n    errors=db.execute('SELECT * FROM error_logs ORDER BY id DESC LIMIT 35').fetchall()\n    return render_template('admin_dashboard.html',stats=stats,settings=rows,trips=trips,destinations=destinations,posts=posts,services=services,service_requests=service_requests,visits=visits,errors=errors)\n"""
if old not in s: raise SystemExit('dashboard return block not found')
s=s.replace(old,new)
f.write_text(s)

# inject analytics panels before backup section in admin dashboard
f=p/'app/templates/admin_dashboard.html'; s=f.read_text()
marker='<div class="admin-grid-two"><div class="admin-panel"><div class="panel-head"><div><span class="eyebrow">VISITOR QR</span>'
panel='''<div class="admin-grid-two"><div class="admin-panel"><div class="panel-head"><div><span class="eyebrow">LIVE ACTIVITY</span><h2>Who is visiting</h2></div><span class="micro">Most recent 35</span></div>{% for v in visits %}<div class="admin-row"><div><b>{{ v.name or ('Visitor ' ~ v.visitor_key[:8]) }}</b><span>{{ v.created_at.replace('T',' ')[:19] }} · {{ v.path }}</span><small style="display:block;color:#6d7f76">{{ v.device_model or v.platform or 'Unknown device' }}{% if v.browser %} · {{ v.browser }}{% endif %}{% if v.phone %} · {{ v.phone }}{% endif %}</small></div><div class="row-actions"><span title="Visitor key">{{ v.visitor_key[:6] }}</span></div></div>{% else %}<div class="empty">No visit records yet.</div>{% endfor %}</div><div class="admin-panel"><div class="panel-head"><div><span class="eyebrow">SYSTEM ERRORS</span><h2>Silent failures</h2></div><span class="micro">Latest 35</span></div>{% for e in errors %}<div class="admin-row"><div><b>{{ e.status_code }} · {{ e.error_type }}</b><span>{{ e.occurred_at.replace('T',' ')[:19] }} · {{ e.path }}</span><small style="display:block;color:#6d7f76">{{ e.message[:180] }}</small></div><div class="row-actions"><span>{{ e.method }}</span></div></div>{% else %}<div class="empty">No recorded errors.</div>{% endfor %}</div></div>'''+marker
# only replace first occurrence
s=s.replace(marker,panel,1)
f.write_text(s)

# 5) Robust more-button JS and fixed popovers; make page scrollable
f=p/'app/templates/my_edits_studio.html'; s=f.read_text()
# remove inline handlers on more buttons
s=s.replace('onclick="toggleEdPop(this);return false"','')
# Replace existing toggle listener block with delegated pointerdown + positioning helpers
start=s.find("  window.toggleEdPop=btn=>{")
end=s.find("  function paint(){", start)
if start==-1 or end==-1: raise SystemExit('toggle block boundaries not found')
robust="""  let openTool=null;\n  const positionPop=tool=>{\n    const btn=tool.querySelector('.myed-more'), pop=tool.querySelector('.myed-pop'); if(!btn||!pop)return;\n    pop.style.position='fixed';\n    pop.style.left='0px'; pop.style.right='auto'; pop.style.top='0px';\n    const r=btn.getBoundingClientRect(); const pw=Math.min(Math.max(tool.getBoundingClientRect().width-14,240),360);\n    pop.style.width=pw+'px';\n    const below=window.innerHeight-r.bottom-10; const ph=Math.min(pop.scrollHeight||190, Math.max(160, below));\n    const top=below>=150 ? r.bottom+5 : Math.max(8,r.top-Math.min(260,pop.scrollHeight||190)-5);\n    const left=Math.min(Math.max(8,r.left),window.innerWidth-pw-8);\n    pop.style.left=left+'px'; pop.style.top=top+'px';\n  };\n  window.toggleEdPop=btn=>{\n    const tool=btn?.closest('.myed-tool'); if(!tool)return;\n    if(openTool&&openTool!==tool){openTool.classList.remove('more-open');openTool.querySelector('.myed-more')?.setAttribute('aria-expanded','false');}\n    const open=!tool.classList.contains('more-open');\n    tool.classList.toggle('more-open',open); btn.setAttribute('aria-expanded',String(open)); openTool=open?tool:null;\n    if(open){positionPop(tool); setTimeout(()=>positionPop(tool),0);}\n  };\n  document.addEventListener('pointerdown',e=>{\n    const more=e.target.closest('.myed-more');\n    if(more){e.preventDefault();e.stopPropagation();window.toggleEdPop(more);return;}\n    const label=e.target.closest('.myed-pop label');\n    if(label){const input=label.querySelector('input');if(input){e.preventDefault();input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}));}return;}\n    if(openTool&&!e.target.closest('.myed-tool.more-open')){openTool.classList.remove('more-open');openTool.querySelector('.myed-more')?.setAttribute('aria-expanded','false');openTool=null;}\n  },true);\n  window.addEventListener('scroll',()=>openTool&&positionPop(openTool),true);\n  window.addEventListener('resize',()=>openTool&&positionPop(openTool));\n  document.querySelectorAll('.myed-more').forEach(btn=>{btn.setAttribute('aria-haspopup','true');btn.setAttribute('aria-expanded','false');});\n"""
s=s[:start]+robust+s[end:]
# Remove old document click block and input listener block to avoid double handling
old_start=s.find("  document.addEventListener('click',e=>{")
old_end=s.find("  paint();", old_start)
if old_start!=-1 and old_end!=-1:
    s=s[:old_start]+s[old_end:]
# ensure scroll css override in inline style
s=s.replace('.myed{min-height:calc(100dvh - 80px);', '.myed{min-height:calc(100dvh - 80px);overflow-y:auto;overflow-x:hidden;')
# Since fixed popovers are moved visually but remain DOM, CSS class needs display
s=s.replace('.myed-tool.more-open .myed-pop{display:block}', '.myed-tool.more-open .myed-pop{display:block;position:fixed;z-index:2147483647;pointer-events:auto}')
f.write_text(s)

# 6) Add client-hints telemetry script before endscript, just before paint call
f=p/'app/templates/my_edits_studio.html'; s=f.read_text()
needle="  paint();\n})();"
tele="""  paint();\n  // Capture the device model when the browser exposes it, while keeping the server-side UA as fallback.\n  (async()=>{try{const u=navigator.userAgentData;if(!u)return;const hi=await u.getHighEntropyValues(['model','platform','platformVersion','fullVersionList']);await fetch('/telemetry',{method:'POST',headers:{'Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:JSON.stringify({model:hi.model||'',platform:hi.platform||'',browser:(hi.brands||[]).map(x=>x.brand+' '+x.version).join(', ')})});}catch(_){}})();\n})();"""
if needle in s: s=s.replace(needle,tele,1)
f.write_text(s)

print('patched')
