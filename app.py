import os,re,csv,io,sqlite3,threading,time
from datetime import datetime
from urllib.parse import urlparse
import requests
from flask import Flask,request,jsonify,render_template,send_file
BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,'indexer.db'); MAX=500
app=Flask(__name__); s=requests.Session(); s.headers['User-Agent']='URLIndexer/1.0'
def conn():
 c=sqlite3.connect(DB,timeout=30); c.row_factory=sqlite3.Row; return c
def init():
 c=conn(); c.execute('CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,created_at TEXT,total INTEGER,status TEXT)'); c.execute('CREATE TABLE IF NOT EXISTS urls(id INTEGER PRIMARY KEY,job_id INTEGER,url TEXT,status TEXT,http_status INTEGER,final_url TEXT,canonical TEXT,robots TEXT,noindex TEXT,message TEXT,updated_at TEXT)'); c.commit(); c.close()
def urls(raw):
 out=[]; seen=set()
 for x in raw.splitlines():
  x=x.strip().strip('"\'');
  if not x: continue
  if not re.match(r'^https?://',x,re.I): x='https://'+x
  try:
   p=urlparse(x)
   if p.scheme not in ('http','https') or not p.netloc: continue
   k=x.lower()
   if k not in seen: seen.add(k); out.append(x)
  except: pass
 return out[:MAX]
def meta(h,n):
 m=re.search(r'<meta[^>]+name=["\']'+re.escape(n)+r'["\'][^>]+content=["\']([^"\']*)',h,re.I); return m.group(1) if m else ''
def canonical(h):
 m=re.search(r'<link[^>]+rel=["\'][^"\']*canonical[^"\']*["\'][^>]+href=["\']([^"\']+)',h,re.I) or re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'][^"\']*canonical',h,re.I); return m.group(1) if m else ''
def check(i,u):
 c=conn(); now=datetime.utcnow().isoformat(timespec='seconds')+'Z'
 try:
  r=s.get(u,timeout=20,allow_redirects=True); h=r.text[:300000] if 'text' in r.headers.get('content-type','') else ''; rob=meta(h,'robots') or r.headers.get('X-Robots-Tag',''); ni='noindex' if re.search(r'\bnoindex\b',rob,re.I) else ''; st='Checked' if r.ok else 'HTTP Error'; msg='Reachable' if r.ok else f'HTTP {r.status_code}'
  c.execute('UPDATE urls SET status=?,http_status=?,final_url=?,canonical=?,robots=?,noindex=?,message=?,updated_at=? WHERE id=?',(st,r.status_code,r.url,canonical(h),rob,ni,msg,now,i))
 except Exception as e: c.execute('UPDATE urls SET status="Failed",message=?,updated_at=? WHERE id=?',(str(e)[:500],now,i))
 c.commit(); c.close()
def worker(j):
 c=conn(); rows=c.execute('SELECT id,url FROM urls WHERE job_id=? ORDER BY id',(j,)).fetchall(); c.close()
 for r in rows: check(r['id'],r['url']); time.sleep(1.2)
 c=conn(); c.execute('UPDATE jobs SET status="Completed" WHERE id=?',(j,)); c.commit(); c.close()
@app.route('/')
def home(): return render_template('index.html')
@app.post('/api/jobs')
def create():
 d=request.get_json(silent=True) or {}; u=urls(d.get('urls',''))
 if not u:return jsonify(error='No valid URLs found.'),400
 c=conn(); q=c.execute('INSERT INTO jobs(created_at,total,status) VALUES(?,?,?)',(datetime.utcnow().isoformat(timespec='seconds')+'Z',len(u),'Processing')); j=q.lastrowid; c.executemany('INSERT INTO urls(job_id,url,status) VALUES(?,?,?)',[(j,x,'Pending') for x in u]); c.commit(); c.close(); threading.Thread(target=worker,args=(j,),daemon=True).start(); return jsonify(job_id=j,total=len(u))
@app.get('/api/jobs/<int:j>')
def status(j):
 c=conn(); job=c.execute('SELECT * FROM jobs WHERE id=?',(j,)).fetchone(); rows=c.execute('SELECT * FROM urls WHERE job_id=? ORDER BY id',(j,)).fetchall(); c.close()
 if not job:return jsonify(error='Not found'),404
 counts={}
 for r in rows:counts[r['status']]=counts.get(r['status'],0)+1
 done=sum(v for k,v in counts.items() if k!='Pending'); return jsonify(job=dict(job),counts=counts,done=done,rows=[dict(r) for r in rows])
@app.get('/api/jobs/<int:j>/csv')
def export(j):
 c=conn(); rows=c.execute('SELECT url,status,http_status,final_url,canonical,robots,noindex,message,updated_at FROM urls WHERE job_id=?',(j,)).fetchall(); c.close(); out=io.StringIO(); w=csv.writer(out); w.writerow(['URL','Status','HTTP Status','Final URL','Canonical','Robots','Noindex','Message','Updated']); [w.writerow(list(r)) for r in rows]; b=io.BytesIO(out.getvalue().encode('utf-8-sig')); b.seek(0); return send_file(b,mimetype='text/csv',as_attachment=True,download_name=f'url-indexer-{j}.csv')
init()
if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
