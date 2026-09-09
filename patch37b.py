from pathlib import Path
p=Path('/mnt/data/work37')
# Base: global client-side error reporting and device hints
f=p/'app/templates/base.html'; s=f.read_text()
s=s.replace("<link rel=\"stylesheet\" href=\"{{ url_for('static',filename='style.css', v='32') }}\">", "<link rel=\"stylesheet\" href=\"{{ url_for('static',filename='style.css', v='37') }}\">")
needle="</script>\n<script>let deferredInstall=null;"
script="""</script>\n<script>\n(function(){\n  const send=(payload)=>{try{navigator.sendBeacon('/client-error',new Blob([JSON.stringify(payload)],{type:'application/json'}));}catch(_){fetch('/client-error',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),keepalive:true}).catch(()=>{});}};\n  window.addEventListener('error',e=>send({kind:'JavaScriptError',message:String(e.message||'Unknown error'),source:String(e.filename||''),line:e.lineno||0,column:e.colno||0,stack:e.error&&e.error.stack||''}));\n  window.addEventListener('unhandledrejection',e=>send({kind:'UnhandledPromise',message:String(e.reason&&e.reason.message||e.reason||'Unhandled rejection'),stack:e.reason&&e.reason.stack||''}));\n  window.addEventListener('DOMContentLoaded',()=>{try{const u=navigator.userAgentData;if(!u)return;u.getHighEntropyValues(['model','platform','platformVersion','fullVersionList']).then(hi=>{const body={model:hi.model||'',platform:hi.platform||'',browser:(hi.fullVersionList||hi.brands||[]).map(x=>x.brand+' '+x.version).join(', ')};fetch('/telemetry',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive:true}).catch(()=>{});}).catch(()=>{});}catch(_) {}});\n})();\n</script>\n<script>let deferredInstall=null;"""
if needle not in s: raise SystemExit('base needle not found')
s=s.replace(needle,script,1)
f.write_text(s)

# Public routes: client error collector and telemetry uses latest visit
f=p/'app/routes.py'; s=f.read_text()
old="""@bp.post('/telemetry')\ndef telemetry():\n    vid=getattr(request,'_visit_id',None)\n    if not vid: return jsonify(ok=True)\n    data=request.get_json(silent=True) or {}\n    model=str(data.get('model','') or '')[:120]\n    platform=str(data.get('platform','') or '')[:120]\n    browser=str(data.get('browser','') or '')[:120]\n    db=get_db(); db.execute('UPDATE visits SET device_model=COALESCE(NULLIF(?,'"'"'"'"'""'"'"'"'),device_model), platform=COALESCE(NULLIF(?,'"'"'"'"'""'"'"'"'),platform), browser=COALESCE(NULLIF(?,'"'"'"'"'""'"'"'"'),browser) WHERE id=?',(model,platform,browser,vid)); db.commit()\n    return jsonify(ok=True)\n"""
# find by slice since quotes make exact annoying
start=s.find("@bp.post('/telemetry')")
end=s.find("\n@bp.get('/health')",0) if False else -1
# use next public decorator after telemetry
if start==-1: raise SystemExit('telemetry not found')
nextpos=s.find("\n@bp.",start+10)
# This should point to next route decorator, likely /health appears later? check and choose first.
new="""@bp.post('/telemetry')\ndef telemetry():\n    key=request.cookies.get('visitor_key')\n    if not key: return jsonify(ok=True)\n    data=request.get_json(silent=True) or {}\n    model=str(data.get('model','') or '')[:120]\n    platform=str(data.get('platform','') or '')[:120]\n    browser=str(data.get('browser','') or '')[:200]\n    db=get_db(); db.execute('UPDATE visits SET device_model=COALESCE(NULLIF(?,\'\'),device_model), platform=COALESCE(NULLIF(?,\'\'),platform), browser=COALESCE(NULLIF(?,\'\'),browser) WHERE id=(SELECT id FROM visits WHERE visitor_key=? ORDER BY id DESC LIMIT 1)',(model,platform,browser,key)); db.commit()\n    return jsonify(ok=True)\n\n@bp.post('/client-error')\ndef client_error():\n    data=request.get_json(silent=True) or {}\n    db=get_db(); key=request.cookies.get('visitor_key','')\n    uid=session.get('user_id')\n    message=str(data.get('message','Client-side error'))[:4000]\n    kind=str(data.get('kind','ClientError'))[:100]\n    extra='source='+str(data.get('source',''))[:300]+' line='+str(data.get('line',''))[:20]+' column='+str(data.get('column',''))[:20]\n    stack=str(data.get('stack',''))[:10000]\n    db.execute('INSERT INTO error_logs(occurred_at,status_code,path,method,error_type,message,traceback,user_id,visitor_key,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(now(),0,request.path,request.method,kind,message,extra+'\\n'+stack,uid,key,request.headers.get('User-Agent','')[:600],_request_ip())); db.commit()\n    return jsonify(ok=True)\n\n"""
s=s[:start]+new+s[nextpos+1:]
f.write_text(s)

# App error handlers: use real session user id
f=p/'app/__init__.py'; s=f.read_text()
s=s.replace("uid=request.cookies.get('_uid')", "uid=__import__('flask').session.get('user_id')")
f.write_text(s)

# Editor: add change handler and remove page-specific duplicate telemetry; tighten scroll
f=p/'app/templates/my_edits_studio.html'; s=f.read_text()
# Insert change handling before paint() end
needle="  document.querySelectorAll('.myed-more').forEach(btn=>{btn.setAttribute('aria-haspopup','true');btn.setAttribute('aria-expanded','false');});\n  function paint(){"
rep="""  document.querySelectorAll('.myed-more').forEach(btn=>{btn.setAttribute('aria-haspopup','true');btn.setAttribute('aria-expanded','false');});\n  document.addEventListener('change',e=>{\n    const input=e.target.closest('.myed-picks input');\n    if(!input)return;\n    const pop=input.closest('.myed-pop');\n    if(pop){const tool=pop.closest('.myed-tool'); if(tool&&openTool===tool){tool.classList.remove('more-open');input.closest('.myed-pop').style.display='none';tool.querySelector('.myed-more')?.setAttribute('aria-expanded','false');openTool=null;setTimeout(()=>input.closest('.myed-pop').style.display='',0);}}\n    paint();\n  });\n  function paint(){"""
if needle not in s: raise SystemExit('editor change insertion point not found')
s=s.replace(needle,rep,1)
# remove old page-specific telemetry block
import re
s=re.sub(r"\n\s*// Capture the device model when the browser exposes it, while keeping the server-side UA as fallback\.\n\s*\(async\(\)=>\{try\{const u=navigator\.userAgentData.*?\}\)\(\)\;", "", s, flags=re.S)
# Ensure final inline CSS overrides parent rigid main and gives true scroll viewport.
if '.myed{min-height:calc(100dvh - 80px);height:100dvh;' not in s:
    s=s.replace('.myed{min-height:calc(100dvh - 80px);overflow-y:auto;overflow-x:hidden;', '.myed{min-height:calc(100dvh - 80px);height:100dvh;box-sizing:border-box;overflow-y:auto;overflow-x:hidden;')
f.write_text(s)

print('patched b')
