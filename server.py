from flask import Flask, request, jsonify, send_from_directory, Response
import sqlite3, os, time, json, hashlib, re, xml.etree.ElementTree as ET

app = Flask(__name__, static_folder='public')
DB = os.path.join(os.path.dirname(__file__), 'db', 'failarchive.db')
ADMIN_TOKEN = 'failarchive-admin-2024'  # Change this in production

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT,
            industry TEXT NOT NULL,
            category TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            story TEXT NOT NULL,
            what_went_wrong TEXT NOT NULL,
            what_learned TEXT NOT NULL,
            recovery TEXT,
            impact_level INTEGER DEFAULT 3,
            author TEXT DEFAULT 'Anonymous',
            upvotes INTEGER DEFAULT 0,
            been_there INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            status TEXT DEFAULT 'approved',
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            author TEXT DEFAULT 'Anonymous',
            experience_years INTEGER,
            upvotes INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES entries(id)
        );

        CREATE TABLE IF NOT EXISTS reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            UNIQUE(type, target_type, target_id, fingerprint)
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(entry_id, session_id)
        );

        CREATE TABLE IF NOT EXISTS newsletter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
        CREATE INDEX IF NOT EXISTS idx_entries_category ON entries(category);
        CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
        CREATE INDEX IF NOT EXISTS idx_entries_upvotes ON entries(upvotes);
        CREATE INDEX IF NOT EXISTS idx_tips_entry ON tips(entry_id);
        CREATE INDEX IF NOT EXISTS idx_newsletter_email ON newsletter(email);
    ''')
    conn.commit()

    # Migrations: add new columns if they don't exist yet
    for col, definition in [
        ('company_stage', 'TEXT'),
        ('time_lost', 'TEXT'),
        ('featured', 'INTEGER DEFAULT 0'),
    ]:
        try:
            conn.execute(f'ALTER TABLE entries ADD COLUMN {col} {definition}')
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

    if conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0:
        seed_data = [
            (
                'We hired too fast and burned through runway',
                'StealthStartup', 'Startup', 'hiring',
                '["scaling", "runway", "team-building"]',
                'In 2022 we raised a $1.2M seed round. Within 3 months we hired 18 people. Engineering, sales, marketing, ops — all at once. We never validated product-market fit first. 8 months later, our runway was at 4 months and we had to let 12 of them go. Some had quit stable jobs to join us.',
                'We confused hiring activity with progress. Every new hire felt like momentum. We hired for our dream state, not our current stage. We also hired generalists when we needed specialists — and then hired specialists when we should have stayed lean.',
                'Hire for your current stage, not your dream stage. Every hire before PMF is a liability you may not be able to afford. Before hiring anyone, ask: does this person directly help us reach PMF faster? If the answer is "eventually" or "when we scale" — wait.',
                'We survived. Cut burn by 70%, refocused on 2 core customers, found PMF 11 months later with 6 people.',
                4, 'Founder, anonymous', int(time.time()) - 86400 * 45,
                'seed', '8 months + $400k burn', 1
            ),
            (
                'We ignored churn for 18 months',
                'B2B SaaS co.', 'SaaS', 'product',
                '["churn", "metrics", "retention"]',
                'Our new user numbers looked great every month. We celebrated every new signup in Slack. Nobody was watching the back door. Customers were quietly leaving after 3-6 months. By the time we finally built a churn dashboard, our NRR was at 72% — we were a leaky bucket.',
                'Vanity metrics felt good. New MRR was visible, churn was invisible because it was slow and buried in spreadsheets. Our investor updates only showed new ARR. Nobody pushed back because the number looked right.',
                'Set up automated churn alerts from day one. NRR (Net Revenue Retention) is the single most important metric for a SaaS. Track it weekly, not quarterly. If NRR is below 100%, you are paying to acquire customers who will leave.',
                'Built a retention team, introduced quarterly business reviews for all customers over $500/mo. NRR recovered to 108% over 14 months.',
                4, 'Head of Growth', int(time.time()) - 86400 * 21,
                'series-a', '18 months of misleading data', 1
            ),
            (
                'We built 6 months of features nobody asked for',
                None, 'Product', 'product',
                '["product-market-fit", "user-research", "roadmap"]',
                'We had a roadmap full of "obvious" ideas. Things we were sure users wanted. We shipped them. Usage was near zero. We kept building. Still zero. After 6 months and ~$200k in engineering cost, we finally did proper user interviews and discovered users wanted something completely different.',
                'We mistook user politeness in demos for validation. "That looks cool!" and "I would use that!" are not purchase intent. We also fell in love with our solution and stopped questioning whether it solved a real problem.',
                'Before building anything, watch 5 real users try to accomplish the goal without your feature. Do mom tests, not demo feedback. One hour of real user observation saves 6 months of building.',
                None, 5, 'CPO', int(time.time()) - 86400 * 12,
                'seed', '6 months + $200k', 0
            ),
            (
                'We let one key engineer become a single point of failure',
                'AgencyFlow', 'Agency', 'operations',
                '["key-person-risk", "documentation", "bus-factor"]',
                'Our lead engineer had been with us 4 years. He knew every system, every quirk, every undocumented decision. No runbooks, no documentation, no knowledge transfer. He left for a FAANG job with 2 weeks notice. We spent the next 3 months firefighting. We lost 2 major clients during that period.',
                'We were too busy building to document. We also ignored subtle signs — he had been interviewing for months and we chose not to notice.',
                'Bus factor of 1 is an existential risk. Every critical system needs at least 2 people who understand it deeply. Force documentation as part of the done criteria. Schedule monthly "teach me your job" sessions between senior engineers.',
                'Hired 2 engineers, spent 4 months on documentation and system rewrites. Now every critical system has a runbook.',
                5, 'CTO', int(time.time()) - 86400 * 6,
                'growth', '3 months firefighting', 0
            ),
            (
                'We raised at too high a valuation and trapped ourselves',
                None, 'Startup', 'finance',
                '["fundraising", "valuation", "down-round"]',
                'We raised our Series A at 40x ARR during the 2021 boom. It felt like validation. 18 months later, ARR had grown 2x but the market had repriced SaaS at 8-12x. We needed more runway but could not raise without a severe down round. We were trapped between running out of money and a down round that would crater morale and cap table.',
                'We optimized for headline valuation instead of terms and dilution. We also spent aggressively assuming the next round would come at a higher valuation. We had no bridge plan.',
                'Raise the amount you need, at a fair valuation, with clean terms. A high valuation is a liability if you cannot grow into it. Always model your next raise assuming flat or down markets. Keep 18+ months of runway at all times.',
                None, 4, 'CEO (anonymous)', int(time.time()) - 86400 * 3,
                'series-a', 'Nearly the company', 0
            ),
        ]
        for s in seed_data:
            conn.execute('''INSERT INTO entries
                (title, company, industry, category, tags, story, what_went_wrong, what_learned,
                 recovery, impact_level, author, created_at, status, company_stage, time_lost, featured)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'approved',?,?,?)''', s)
        conn.commit()
    else:
        # Update existing seed entries with new fields if they are still NULL
        updates = [
            ('seed', '8 months + $400k burn', 1, 'We hired too fast and burned through runway'),
            ('series-a', '18 months of misleading data', 1, 'We ignored churn for 18 months'),
            ('seed', '6 months + $200k', 0, 'We built 6 months of features nobody asked for'),
            ('growth', '3 months firefighting', 0, 'We let one key engineer become a single point of failure'),
            ('series-a', 'Nearly the company', 0, 'We raised at too high a valuation and trapped ourselves'),
        ]
        for company_stage, time_lost, featured, title in updates:
            conn.execute('''UPDATE entries SET
                company_stage = COALESCE(company_stage, ?),
                time_lost = COALESCE(time_lost, ?),
                featured = CASE WHEN featured IS NULL THEN ? ELSE featured END
                WHERE title = ?''',
                (company_stage, time_lost, featured, title))
        conn.commit()

    conn.close()

def get_fingerprint():
    ip = request.remote_addr or '0.0.0.0'
    ua = request.headers.get('User-Agent', '')
    return hashlib.md5(f'{ip}:{ua}'.encode()).hexdigest()[:16]

def row_to_dict(row):
    d = dict(row)
    if 'tags' in d:
        try: d['tags'] = json.loads(d['tags'])
        except: d['tags'] = []
    return d

def require_admin():
    token = request.headers.get('X-Admin-Token') or request.args.get('token')
    return token == ADMIN_TOKEN

def valid_email(email):
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email.strip()))

# ─── ENTRIES ─────────────────────────────────────────────

@app.route('/api/entries', methods=['GET'])
def get_entries():
    category = request.args.get('category')
    tag = request.args.get('tag')
    q = request.args.get('q')
    sort = request.args.get('sort', 'recent')
    impact = request.args.get('impact')
    featured = request.args.get('featured')
    company_stage = request.args.get('company_stage')
    limit = min(int(request.args.get('limit', 20)), 50)
    offset = int(request.args.get('offset', 0))
    status = 'approved'
    if require_admin():
        status = request.args.get('status', 'approved')

    conn = get_db()
    base = '''SELECT e.*,
        (SELECT COUNT(*) FROM tips WHERE entry_id=e.id) as tip_count
        FROM entries e WHERE e.status=?'''
    params = [status]

    if category:
        base += ' AND e.category=?'; params.append(category)
    if impact:
        base += ' AND e.impact_level=?'; params.append(int(impact))
    if tag:
        base += ' AND e.tags LIKE ?'; params.append(f'%"{tag}"%')
    if q:
        base += ' AND (e.title LIKE ? OR e.story LIKE ? OR e.what_learned LIKE ? OR e.tags LIKE ?)'
        params += [f'%{q}%'] * 4
    if featured is not None:
        base += ' AND e.featured=?'; params.append(1 if featured in ('1', 'true') else 0)
    if company_stage:
        base += ' AND e.company_stage=?'; params.append(company_stage)

    order = {'recent': 'e.created_at DESC', 'top': 'e.upvotes DESC',
             'trending': '(e.upvotes + e.been_there) DESC', 'discussed': 'tip_count DESC'}.get(sort, 'e.created_at DESC')
    base += f' ORDER BY {order} LIMIT ? OFFSET ?'
    params += [limit, offset]

    rows = conn.execute(base, params).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route('/api/entries/featured', methods=['GET'])
def get_featured():
    conn = get_db()
    rows = conn.execute('''SELECT e.*,
        (SELECT COUNT(*) FROM tips WHERE entry_id=e.id) as tip_count
        FROM entries e WHERE e.status='approved' AND e.featured=1
        ORDER BY e.created_at DESC LIMIT 3''').fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route('/api/entries/trending', methods=['GET'])
def get_trending():
    week_ago = int(time.time()) - 86400 * 7
    conn = get_db()
    rows = conn.execute('''SELECT e.*,
        (SELECT COUNT(*) FROM tips WHERE entry_id=e.id) as tip_count
        FROM entries e WHERE e.status='approved' AND e.created_at > ?
        ORDER BY (e.upvotes + e.been_there * 2) DESC LIMIT 5''', (week_ago,)).fetchall()
    if len(rows) < 3:
        rows = conn.execute('''SELECT e.*,
            (SELECT COUNT(*) FROM tips WHERE entry_id=e.id) as tip_count
            FROM entries e WHERE e.status='approved'
            ORDER BY (e.upvotes + e.been_there * 2) DESC LIMIT 5''').fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route('/api/entries/random', methods=['GET'])
def get_random():
    conn = get_db()
    row = conn.execute("SELECT * FROM entries WHERE status='approved' ORDER BY RANDOM() LIMIT 1").fetchone()
    conn.close()
    if not row: return jsonify({'error': 'No entries'}), 404
    return jsonify(row_to_dict(row))

@app.route('/api/entries/<int:eid>', methods=['GET'])
def get_entry(eid):
    conn = get_db()
    entry = conn.execute('SELECT * FROM entries WHERE id=?', (eid,)).fetchone()
    if not entry or (entry['status'] != 'approved' and not require_admin()):
        conn.close(); return jsonify({'error': 'Not found'}), 404
    conn.execute('UPDATE entries SET views=views+1 WHERE id=?', (eid,))
    conn.commit()
    tips = conn.execute('SELECT * FROM tips WHERE entry_id=? ORDER BY upvotes DESC, created_at DESC', (eid,)).fetchall()
    related = conn.execute('''SELECT id, title, category, upvotes FROM entries
        WHERE category=? AND id!=? AND status='approved' ORDER BY upvotes DESC LIMIT 4''',
        (entry['category'], eid)).fetchall()
    conn.close()
    return jsonify({'entry': row_to_dict(entry), 'tips': [dict(t) for t in tips], 'related': [dict(r) for r in related]})

@app.route('/api/entries', methods=['POST'])
def create_entry():
    d = request.json or {}
    required = ['title', 'industry', 'category', 'story', 'what_went_wrong', 'what_learned']
    for f in required:
        if not str(d.get(f, '')).strip():
            return jsonify({'error': f'Missing: {f}'}), 400

    tags = d.get('tags', [])
    if isinstance(tags, str):
        tags = [t.strip().lower() for t in tags.split(',') if t.strip()]
    tags = tags[:8]

    valid_stages = {'pre-seed', 'seed', 'series-a', 'growth', 'established', 'enterprise', ''}
    company_stage = d.get('company_stage', '').strip()
    if company_stage not in valid_stages:
        return jsonify({'error': 'Invalid company_stage'}), 400

    conn = get_db()
    cur = conn.execute('''INSERT INTO entries
        (title,company,industry,category,tags,story,what_went_wrong,what_learned,recovery,
         impact_level,author,created_at,status,company_stage,time_lost)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (d['title'].strip()[:200], d.get('company','').strip()[:100] or None,
         d['industry'].strip()[:60], d['category'].strip(),
         json.dumps(tags), d['story'].strip(),
         d['what_went_wrong'].strip(), d['what_learned'].strip(),
         d.get('recovery','').strip() or None,
         max(1,min(5,int(d.get('impact_level',3)))),
         d.get('author','Anonymous').strip()[:80] or 'Anonymous',
         int(time.time()), 'approved',
         company_stage or None,
         d.get('time_lost','').strip()[:200] or None))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return jsonify({'id': new_id}), 201

# ─── NEWSLETTER ───────────────────────────────────────────

@app.route('/api/newsletter', methods=['POST'])
def newsletter_subscribe():
    d = request.json or {}
    email = d.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    if not valid_email(email):
        return jsonify({'error': 'Invalid email address'}), 400
    conn = get_db()
    try:
        conn.execute('INSERT INTO newsletter (email, created_at) VALUES (?, ?)',
                     (email, int(time.time())))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # already subscribed — silently succeed
    conn.close()
    return jsonify({'ok': True})

# ─── REACTIONS ────────────────────────────────────────────

@app.route('/api/entries/<int:eid>/upvote', methods=['POST'])
def upvote_entry(eid):
    fp = get_fingerprint()
    conn = get_db()
    try:
        conn.execute('INSERT INTO reactions (type,target_type,target_id,fingerprint) VALUES (?,?,?,?)',
                     ('upvote','entry',eid,fp))
        conn.execute('UPDATE entries SET upvotes=upvotes+1 WHERE id=?', (eid,))
        conn.commit()
        count = conn.execute('SELECT upvotes FROM entries WHERE id=?', (eid,)).fetchone()['upvotes']
        conn.close()
        return jsonify({'upvotes': count})
    except sqlite3.IntegrityError:
        conn.execute('DELETE FROM reactions WHERE type=? AND target_type=? AND target_id=? AND fingerprint=?',
                     ('upvote','entry',eid,fp))
        conn.execute('UPDATE entries SET upvotes=MAX(0,upvotes-1) WHERE id=?', (eid,))
        conn.commit()
        count = conn.execute('SELECT upvotes FROM entries WHERE id=?', (eid,)).fetchone()['upvotes']
        conn.close()
        return jsonify({'upvotes': count, 'removed': True})

@app.route('/api/entries/<int:eid>/been-there', methods=['POST'])
def been_there(eid):
    fp = get_fingerprint()
    conn = get_db()
    try:
        conn.execute('INSERT INTO reactions (type,target_type,target_id,fingerprint) VALUES (?,?,?,?)',
                     ('been_there','entry',eid,fp))
        conn.execute('UPDATE entries SET been_there=been_there+1 WHERE id=?', (eid,))
        conn.commit()
        count = conn.execute('SELECT been_there FROM entries WHERE id=?', (eid,)).fetchone()['been_there']
        conn.close()
        return jsonify({'been_there': count})
    except sqlite3.IntegrityError:
        conn.execute('DELETE FROM reactions WHERE type=? AND target_type=? AND target_id=? AND fingerprint=?',
                     ('been_there','entry',eid,fp))
        conn.execute('UPDATE entries SET been_there=MAX(0,been_there-1) WHERE id=?', (eid,))
        conn.commit()
        count = conn.execute('SELECT been_there FROM entries WHERE id=?', (eid,)).fetchone()['been_there']
        conn.close()
        return jsonify({'been_there': count, 'removed': True})

@app.route('/api/tips/<int:tid>/upvote', methods=['POST'])
def upvote_tip(tid):
    fp = get_fingerprint()
    conn = get_db()
    try:
        conn.execute('INSERT INTO reactions (type,target_type,target_id,fingerprint) VALUES (?,?,?,?)',
                     ('upvote','tip',tid,fp))
        conn.execute('UPDATE tips SET upvotes=upvotes+1 WHERE id=?', (tid,))
        conn.commit()
        count = conn.execute('SELECT upvotes FROM tips WHERE id=?', (tid,)).fetchone()['upvotes']
        conn.close()
        return jsonify({'upvotes': count})
    except sqlite3.IntegrityError:
        conn.execute('DELETE FROM reactions WHERE type=? AND target_type=? AND target_id=? AND fingerprint=?',
                     ('upvote','tip',tid,fp))
        conn.execute('UPDATE tips SET upvotes=MAX(0,upvotes-1) WHERE id=?', (tid,))
        conn.commit()
        count = conn.execute('SELECT upvotes FROM tips WHERE id=?', (tid,)).fetchone()['upvotes']
        conn.close()
        return jsonify({'upvotes': count, 'removed': True})

# ─── TIPS ─────────────────────────────────────────────────

@app.route('/api/entries/<int:eid>/tips', methods=['POST'])
def add_tip(eid):
    d = request.json or {}
    if not str(d.get('content','')).strip():
        return jsonify({'error': 'Content required'}), 400
    conn = get_db()
    if not conn.execute('SELECT id FROM entries WHERE id=? AND status="approved"', (eid,)).fetchone():
        conn.close(); return jsonify({'error': 'Entry not found'}), 404
    conn.execute('INSERT INTO tips (entry_id,content,author,experience_years,created_at) VALUES (?,?,?,?,?)',
        (eid, d['content'].strip(), d.get('author','Anonymous').strip()[:80] or 'Anonymous',
         d.get('experience_years') or None, int(time.time())))
    conn.commit(); conn.close()
    return jsonify({'ok': True}), 201

# ─── REPORTS ──────────────────────────────────────────────

@app.route('/api/entries/<int:eid>/report', methods=['POST'])
def report_entry(eid):
    d = request.json or {}
    reason = d.get('reason','').strip()
    if not reason: return jsonify({'error': 'Reason required'}), 400
    conn = get_db()
    conn.execute('INSERT INTO reports (entry_id,reason,created_at) VALUES (?,?,?)',
                 (eid, reason[:500], int(time.time())))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

# ─── STATS & DISCOVERY ────────────────────────────────────

@app.route('/api/stats', methods=['GET'])
def stats():
    conn = get_db()
    entries = conn.execute("SELECT COUNT(*) FROM entries WHERE status='approved'").fetchone()[0]
    tips = conn.execute('SELECT COUNT(*) FROM tips').fetchone()[0]
    total_upvotes = conn.execute("SELECT SUM(upvotes) FROM entries WHERE status='approved'").fetchone()[0] or 0
    total_been_there = conn.execute("SELECT SUM(been_there) FROM entries WHERE status='approved'").fetchone()[0] or 0
    cats = conn.execute("""SELECT category, COUNT(*) as cnt FROM entries
        WHERE status='approved' GROUP BY category ORDER BY cnt DESC""").fetchall()
    tags_raw = conn.execute("SELECT tags FROM entries WHERE status='approved' AND tags!='[]'").fetchall()
    tag_counts = {}
    for row in tags_raw:
        try:
            for t in json.loads(row[0]):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        except: pass
    top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:20]
    conn.close()
    return jsonify({
        'entries': entries, 'tips': tips,
        'total_upvotes': total_upvotes, 'total_been_there': total_been_there,
        'categories': [dict(r) for r in cats],
        'top_tags': [{'tag': t, 'count': c} for t, c in top_tags]
    })

# ─── RSS FEED ─────────────────────────────────────────────

@app.route('/rss.xml')
def rss_feed():
    conn = get_db()
    entries = conn.execute("""SELECT * FROM entries WHERE status='approved'
        ORDER BY created_at DESC LIMIT 20""").fetchall()
    conn.close()

    rss = ET.Element('rss', version='2.0')
    channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = 'FailArchive — Real Failures, Real Lessons'
    ET.SubElement(channel, 'link').text = 'http://localhost:5000'
    ET.SubElement(channel, 'description').text = 'Honest failure stories from founders, managers, and builders.'

    for e in entries:
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = e['title']
        ET.SubElement(item, 'link').text = f'http://localhost:5000/entry.html?id={e["id"]}'
        ET.SubElement(item, 'description').text = e['what_learned']
        ET.SubElement(item, 'pubDate').text = time.strftime('%a, %d %b %Y %H:%M:%S +0000', time.gmtime(e['created_at']))
        ET.SubElement(item, 'guid').text = str(e['id'])

    xml_str = '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(rss, encoding='unicode')
    return Response(xml_str, mimetype='application/rss+xml')

# ─── ADMIN ────────────────────────────────────────────────

@app.route('/api/admin/entries', methods=['GET'])
def admin_entries():
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    status = request.args.get('status', 'approved')
    rows = conn.execute('SELECT * FROM entries WHERE status=? ORDER BY created_at DESC', (status,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route('/api/admin/entries/<int:eid>/status', methods=['POST'])
def admin_set_status(eid):
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    new_status = (request.json or {}).get('status')
    if new_status not in ('approved', 'pending', 'rejected'):
        return jsonify({'error': 'Invalid status'}), 400
    conn = get_db()
    conn.execute('UPDATE entries SET status=? WHERE id=?', (new_status, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/entries/<int:eid>/feature', methods=['POST'])
def admin_feature_entry(eid):
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    row = conn.execute('SELECT featured FROM entries WHERE id=?', (eid,)).fetchone()
    if not row:
        conn.close(); return jsonify({'error': 'Entry not found'}), 404
    new_val = 0 if row['featured'] else 1
    conn.execute('UPDATE entries SET featured=? WHERE id=?', (new_val, eid))
    conn.commit(); conn.close()
    return jsonify({'ok': True, 'featured': bool(new_val)})

@app.route('/api/admin/entries/<int:eid>', methods=['DELETE'])
def admin_delete_entry(eid):
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    conn.execute('DELETE FROM entries WHERE id=?', (eid,))
    conn.execute('DELETE FROM tips WHERE entry_id=?', (eid,))
    conn.commit(); conn.close()
    return jsonify({'ok': True})

@app.route('/api/admin/reports', methods=['GET'])
def admin_reports():
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    rows = conn.execute('''SELECT r.*, e.title as entry_title FROM reports r
        LEFT JOIN entries e ON r.entry_id=e.id ORDER BY r.created_at DESC''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    if not require_admin(): return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    d = {
        'total_entries': conn.execute('SELECT COUNT(*) FROM entries').fetchone()[0],
        'approved': conn.execute("SELECT COUNT(*) FROM entries WHERE status='approved'").fetchone()[0],
        'pending': conn.execute("SELECT COUNT(*) FROM entries WHERE status='pending'").fetchone()[0],
        'rejected': conn.execute("SELECT COUNT(*) FROM entries WHERE status='rejected'").fetchone()[0],
        'total_tips': conn.execute('SELECT COUNT(*) FROM tips').fetchone()[0],
        'total_reports': conn.execute('SELECT COUNT(*) FROM reports').fetchone()[0],
        'total_views': conn.execute('SELECT SUM(views) FROM entries').fetchone()[0] or 0,
        'newsletter_subscribers': conn.execute('SELECT COUNT(*) FROM newsletter').fetchone()[0],
        'top_entries': [dict(r) for r in conn.execute(
            'SELECT id,title,upvotes,views,been_there FROM entries ORDER BY views DESC LIMIT 5').fetchall()],
    }
    conn.close()
    return jsonify(d)

# ─── STATIC ───────────────────────────────────────────────

@app.route('/')
def index(): return send_from_directory('public', 'index.html')

@app.route('/<path:path>')
def static_files(path): return send_from_directory('public', path)

if __name__ == '__main__':
    init_db()
    print('\n  FailArchive running at http://localhost:5000')
    print('  Admin panel: http://localhost:5000/admin.html')
    print(f'  Admin token: {ADMIN_TOKEN}\n')
    app.run(debug=True, port=5000)
