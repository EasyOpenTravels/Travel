import sqlite3
from flask import current_app, g

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL,
 email TEXT UNIQUE NOT NULL, pin_hash TEXT NOT NULL, recovery_question TEXT NOT NULL,
 recovery_answer_hash TEXT NOT NULL, remember_token TEXT, remember_until TEXT,
 deleted_at TEXT, simple_id_hash TEXT, is_stuff_guest INTEGER NOT NULL DEFAULT 0, journal_card_uses INTEGER NOT NULL DEFAULT 0, stuff_journal_uses INTEGER NOT NULL DEFAULT 0, stuff_copy_uses INTEGER NOT NULL DEFAULT 0, stuff_edits_uses INTEGER NOT NULL DEFAULT 0, stuff_card_uses INTEGER NOT NULL DEFAULT 0, journal_secret_hash TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trips (
 id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 destination TEXT NOT NULL, description TEXT NOT NULL, date TEXT NOT NULL, price INTEGER NOT NULL,
 capacity INTEGER NOT NULL, pickup TEXT NOT NULL, itinerary TEXT NOT NULL, included TEXT NOT NULL,
 excluded TEXT NOT NULL, cover_image TEXT NOT NULL, gallery TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'published',
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
 name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL, quantity INTEGER NOT NULL DEFAULT 1,
 total INTEGER NOT NULL, ref TEXT UNIQUE NOT NULL, payment_status TEXT NOT NULL DEFAULT 'awaiting_payment',
 payment_method TEXT DEFAULT '', payment_reference TEXT DEFAULT '', paid_at TEXT,
 followup_sent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
 FOREIGN KEY(trip_id) REFERENCES trips(id), FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER NOT NULL, passenger_name TEXT NOT NULL,
 ticket_code TEXT UNIQUE NOT NULL, signature TEXT NOT NULL, seat TEXT, status TEXT NOT NULL DEFAULT 'valid',
 checked_in_at TEXT, created_at TEXT NOT NULL, FOREIGN KEY(booking_id) REFERENCES bookings(id)
);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT NOT NULL, email TEXT NOT NULL,
 phone TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unread', admin_reply TEXT,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, trip_id INTEGER NOT NULL, voter_key TEXT NOT NULL,
 rating INTEGER NOT NULL, choice TEXT NOT NULL, comment TEXT, created_at TEXT NOT NULL,
 UNIQUE(trip_id, voter_key)
);
CREATE TABLE IF NOT EXISTS visits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_key TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,
 user_id INTEGER, name TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '',
 method TEXT DEFAULT 'GET', referrer TEXT DEFAULT '', user_agent TEXT DEFAULT '', ip_address TEXT DEFAULT '',
 device_model TEXT DEFAULT '', platform TEXT DEFAULT '', browser TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS error_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL, status_code INTEGER NOT NULL,
 path TEXT NOT NULL, method TEXT NOT NULL, error_type TEXT NOT NULL, message TEXT NOT NULL,
 traceback TEXT DEFAULT '', user_id INTEGER, visitor_key TEXT DEFAULT '', user_agent TEXT DEFAULT '', ip_address TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS destinations (
 id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL, subtitle TEXT NOT NULL,
 vibe TEXT NOT NULL, price_from INTEGER NOT NULL DEFAULT 0, cover_image TEXT NOT NULL, credit TEXT DEFAULT '',
 source_url TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, excerpt TEXT NOT NULL, body TEXT NOT NULL,
 image TEXT DEFAULT '', media_url TEXT DEFAULT '', category TEXT NOT NULL DEFAULT 'From the road',
 published INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS services (
 id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
 subtitle TEXT NOT NULL, description TEXT NOT NULL, cover_image TEXT DEFAULT '', accent TEXT DEFAULT 'lime',
 ticketing_available INTEGER NOT NULL DEFAULT 0, published INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, service_id INTEGER NOT NULL, user_id INTEGER, name TEXT NOT NULL, email TEXT NOT NULL,
 phone TEXT NOT NULL, event_date TEXT DEFAULT '', guest_count INTEGER NOT NULL DEFAULT 1, ticketing INTEGER NOT NULL DEFAULT 0,
 budget TEXT DEFAULT '', notes TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL,
 FOREIGN KEY(service_id) REFERENCES services(id), FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS event_ticket_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 owner_user_id INTEGER NOT NULL,
 slug TEXT UNIQUE NOT NULL,
 title TEXT NOT NULL,
 description TEXT DEFAULT '',
 event_date TEXT DEFAULT '',
 event_time TEXT DEFAULT '',
 venue TEXT DEFAULT '',
 price INTEGER NOT NULL DEFAULT 0,
 currency TEXT NOT NULL DEFAULT 'KES',
 payment_instructions TEXT DEFAULT '',
 cover_image TEXT DEFAULT '',
 ticket_note TEXT DEFAULT '',
 regular_price INTEGER NOT NULL DEFAULT 0,
 vip_price INTEGER NOT NULL DEFAULT 0,
 vvip_price INTEGER NOT NULL DEFAULT 0,
 scanner_code TEXT UNIQUE NOT NULL,
 scanners_pin_hash TEXT NOT NULL,
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 FOREIGN KEY(owner_user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS event_joint_tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id INTEGER NOT NULL,
 joint_code TEXT UNIQUE NOT NULL,
 signature TEXT NOT NULL,
 tier TEXT NOT NULL,
 ticket_codes TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'valid',
 used_at TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(event_id) REFERENCES event_ticket_events(id)
);
CREATE TABLE IF NOT EXISTS group_retreats (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 group_code TEXT UNIQUE NOT NULL,
 leader_pin_hash TEXT NOT NULL,
 leader_user_id INTEGER,
 leader_name TEXT NOT NULL,
 leader_phone TEXT NOT NULL,
 leader_email TEXT DEFAULT '',
 title TEXT NOT NULL,
 group_type TEXT NOT NULL DEFAULT 'Group',
 destination TEXT NOT NULL,
 activities TEXT NOT NULL,
 preferred_date TEXT DEFAULT '',
 people_count INTEGER NOT NULL,
 suggested_price INTEGER NOT NULL DEFAULT 0,
 agreed_price INTEGER NOT NULL DEFAULT 0,
 notes TEXT DEFAULT '',
 status TEXT NOT NULL DEFAULT 'pending',
 active INTEGER NOT NULL DEFAULT 1,
 approved_at TEXT,
 completed_at TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(leader_user_id) REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS group_members (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 retreat_id INTEGER NOT NULL,
 name TEXT NOT NULL,
 gender TEXT NOT NULL DEFAULT '',
 amount_paid INTEGER NOT NULL DEFAULT 0,
 payment_reference TEXT DEFAULT '',
 payment_status TEXT NOT NULL DEFAULT 'pending',
 pass_type TEXT NOT NULL DEFAULT 'individual',
 pass_code TEXT UNIQUE NOT NULL,
 signature TEXT NOT NULL,
 checked_in_at TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(retreat_id) REFERENCES group_retreats(id)
);
CREATE TABLE IF NOT EXISTS event_tickets (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 event_id INTEGER NOT NULL,
 attendee_user_id INTEGER,
 attendee_name TEXT NOT NULL,
 attendee_gender TEXT NOT NULL DEFAULT '',
 attendee_phone TEXT DEFAULT '',
 attendee_email TEXT DEFAULT '',
 ticket_code TEXT UNIQUE NOT NULL,
 signature TEXT NOT NULL,
 payment_method TEXT NOT NULL DEFAULT 'M-Pesa',
 payment_reference TEXT DEFAULT '',
 amount INTEGER NOT NULL DEFAULT 0,
 ticket_tier TEXT NOT NULL DEFAULT 'regular',
 source TEXT NOT NULL DEFAULT 'visitor',
 access_token TEXT UNIQUE,
 payment_status TEXT NOT NULL DEFAULT 'submitted',
 approval_status TEXT NOT NULL DEFAULT 'pending',
 ticket_status TEXT NOT NULL DEFAULT 'valid',
 design TEXT NOT NULL DEFAULT 'classic',
 checked_in_at TEXT,
 approved_at TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(event_id) REFERENCES event_ticket_events(id),
 FOREIGN KEY(attendee_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS stuff_folders (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 name TEXT NOT NULL,
 color TEXT NOT NULL DEFAULT 'lime',
 created_at TEXT NOT NULL,
 UNIQUE(user_id, name),
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS stuff_cards (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 folder_id INTEGER,
 title TEXT NOT NULL,
 body TEXT NOT NULL DEFAULT '',
 color TEXT NOT NULL DEFAULT 'lime',
 image_filename TEXT DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 font_style TEXT NOT NULL DEFAULT 'bold',
 shape_style TEXT NOT NULL DEFAULT 'sticky',
 design_style TEXT NOT NULL DEFAULT 'sunny',
 qr_enabled INTEGER NOT NULL DEFAULT 1,
 signature_enabled INTEGER NOT NULL DEFAULT 1,
 decoration TEXT NOT NULL DEFAULT 'spark',
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
 FOREIGN KEY(folder_id) REFERENCES stuff_folders(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS saved_copies (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 label TEXT NOT NULL,
 value TEXT NOT NULL,
 note TEXT DEFAULT '',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS stuff_images (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 original_name TEXT NOT NULL,
 filename TEXT NOT NULL,
 operation TEXT NOT NULL DEFAULT 'clean',
 created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS journal_entries (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 title TEXT NOT NULL,
 body TEXT NOT NULL DEFAULT '',
 mood TEXT NOT NULL DEFAULT 'thoughts',
 tags TEXT DEFAULT '',
 cover_color TEXT NOT NULL DEFAULT 'cream',
 segments_json TEXT DEFAULT '',
 favorite INTEGER NOT NULL DEFAULT 0,
 archived INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

'''

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE_PATH'], timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
        g.db.execute('PRAGMA journal_mode=WAL')
        g.db.execute('PRAGMA busy_timeout=30000')
    return g.db

def close_db(_=None):
    db = g.pop('db', None)
    if db:
        db.close()

def _column_names(db, table):
    return {r['name'] for r in db.execute(f'PRAGMA table_info({table})').fetchall()}

def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        # Safe upgrades from the earlier build.
        upgrades = {
            'visits': {
                'user_id': 'ALTER TABLE visits ADD COLUMN user_id INTEGER',
                'name': "ALTER TABLE visits ADD COLUMN name TEXT DEFAULT ''",
                'email': "ALTER TABLE visits ADD COLUMN email TEXT DEFAULT ''",
                'phone': "ALTER TABLE visits ADD COLUMN phone TEXT DEFAULT ''",
                'method': "ALTER TABLE visits ADD COLUMN method TEXT DEFAULT 'GET'",
                'referrer': "ALTER TABLE visits ADD COLUMN referrer TEXT DEFAULT ''",
                'user_agent': "ALTER TABLE visits ADD COLUMN user_agent TEXT DEFAULT ''",
                'ip_address': "ALTER TABLE visits ADD COLUMN ip_address TEXT DEFAULT ''",
                'device_model': "ALTER TABLE visits ADD COLUMN device_model TEXT DEFAULT ''",
                'platform': "ALTER TABLE visits ADD COLUMN platform TEXT DEFAULT ''",
                'browser': "ALTER TABLE visits ADD COLUMN browser TEXT DEFAULT ''",
            },
            'error_logs': {},
            'users': {
                'remember_token': 'ALTER TABLE users ADD COLUMN remember_token TEXT',
                'remember_until': 'ALTER TABLE users ADD COLUMN remember_until TEXT',
                'deleted_at': 'ALTER TABLE users ADD COLUMN deleted_at TEXT',
                'stuff_id_hash': 'ALTER TABLE users ADD COLUMN stuff_id_hash TEXT',
                'simple_id_hash': 'ALTER TABLE users ADD COLUMN simple_id_hash TEXT',
                'is_stuff_guest': 'ALTER TABLE users ADD COLUMN is_stuff_guest INTEGER NOT NULL DEFAULT 0',
                'journal_card_uses': 'ALTER TABLE users ADD COLUMN journal_card_uses INTEGER NOT NULL DEFAULT 0',
                'stuff_journal_uses': 'ALTER TABLE users ADD COLUMN stuff_journal_uses INTEGER NOT NULL DEFAULT 0',
                'stuff_copy_uses': 'ALTER TABLE users ADD COLUMN stuff_copy_uses INTEGER NOT NULL DEFAULT 0',
                'stuff_edits_uses': 'ALTER TABLE users ADD COLUMN stuff_edits_uses INTEGER NOT NULL DEFAULT 0',
                'stuff_card_uses': 'ALTER TABLE users ADD COLUMN stuff_card_uses INTEGER NOT NULL DEFAULT 0',
                'journal_secret_hash': 'ALTER TABLE users ADD COLUMN journal_secret_hash TEXT',
            },
            'bookings': {
                'payment_method': "ALTER TABLE bookings ADD COLUMN payment_method TEXT DEFAULT ''",
                'payment_reference': "ALTER TABLE bookings ADD COLUMN payment_reference TEXT DEFAULT ''",
                'paid_at': 'ALTER TABLE bookings ADD COLUMN paid_at TEXT',
                'followup_sent': 'ALTER TABLE bookings ADD COLUMN followup_sent INTEGER NOT NULL DEFAULT 0',
            },
            'trips': {'gallery': "ALTER TABLE trips ADD COLUMN gallery TEXT DEFAULT ''"},
            'stuff_cards': {
                'font_style': "ALTER TABLE stuff_cards ADD COLUMN font_style TEXT NOT NULL DEFAULT 'bold'",
                'shape_style': "ALTER TABLE stuff_cards ADD COLUMN shape_style TEXT NOT NULL DEFAULT 'sticky'",
                'design_style': "ALTER TABLE stuff_cards ADD COLUMN design_style TEXT NOT NULL DEFAULT 'sunny'",
                'qr_enabled': "ALTER TABLE stuff_cards ADD COLUMN qr_enabled INTEGER NOT NULL DEFAULT 1",
                'signature_enabled': "ALTER TABLE stuff_cards ADD COLUMN signature_enabled INTEGER NOT NULL DEFAULT 1",
                'decoration': "ALTER TABLE stuff_cards ADD COLUMN decoration TEXT NOT NULL DEFAULT 'spark'",
                'background_style': "ALTER TABLE stuff_cards ADD COLUMN background_style TEXT NOT NULL DEFAULT 'solid'",
            },
            'event_ticket_events': {
                'regular_price': 'ALTER TABLE event_ticket_events ADD COLUMN regular_price INTEGER NOT NULL DEFAULT 0',
                'vip_price': 'ALTER TABLE event_ticket_events ADD COLUMN vip_price INTEGER NOT NULL DEFAULT 0',
                'vvip_price': 'ALTER TABLE event_ticket_events ADD COLUMN vvip_price INTEGER NOT NULL DEFAULT 0',
                'scanner_code': 'ALTER TABLE event_ticket_events ADD COLUMN scanner_code TEXT',
            },
            'event_tickets': {
                'attendee_gender': "ALTER TABLE event_tickets ADD COLUMN attendee_gender TEXT NOT NULL DEFAULT ''",
                'ticket_tier': "ALTER TABLE event_tickets ADD COLUMN ticket_tier TEXT NOT NULL DEFAULT 'regular'",
                'source': "ALTER TABLE event_tickets ADD COLUMN source TEXT NOT NULL DEFAULT 'visitor'",
                'access_token': 'ALTER TABLE event_tickets ADD COLUMN access_token TEXT',
            },
        }
        for table, cols in upgrades.items():
            existing = _column_names(db, table)
            for col, sql in cols.items():
                if col not in existing:
                    db.execute(sql)

        if 'segments_json' not in _column_names(db, 'journal_entries'):
            db.execute("ALTER TABLE journal_entries ADD COLUMN segments_json TEXT DEFAULT ''")

        import secrets
        # Backfill scanner/access identifiers on databases created by earlier builds.
        if 'scanner_code' in _column_names(db, 'event_ticket_events'):
            rows = db.execute("SELECT id FROM event_ticket_events WHERE scanner_code IS NULL OR scanner_code=''").fetchall()
            for r in rows:
                db.execute('UPDATE event_ticket_events SET scanner_code=? WHERE id=?', ('SCN-' + secrets.token_hex(4).upper(), r['id']))
        if 'access_token' in _column_names(db, 'event_tickets'):
            rows = db.execute("SELECT id FROM event_tickets WHERE access_token IS NULL OR access_token=''").fetchall()
            for r in rows:
                db.execute('UPDATE event_tickets SET access_token=? WHERE id=?', (secrets.token_urlsafe(24), r['id']))

        # Remove completed event/group records after a 30-day grace period.
        try:
            old_events = db.execute("SELECT id FROM event_ticket_events WHERE active=1 AND event_date!='' AND event_date < date('now','-30 day')").fetchall()
            for r in old_events:
                db.execute('DELETE FROM event_joint_tickets WHERE event_id=?',(r['id'],))
                db.execute('DELETE FROM event_tickets WHERE event_id=?',(r['id'],))
                db.execute('DELETE FROM event_ticket_events WHERE id=?',(r['id'],))
            old_groups = db.execute("SELECT id FROM group_retreats WHERE active=1 AND preferred_date!='' AND preferred_date < date('now','-30 day')").fetchall()
            for r in old_groups:
                db.execute('DELETE FROM group_members WHERE retreat_id=?',(r['id'],))
                db.execute('DELETE FROM group_retreats WHERE id=?',(r['id'],))
            db.commit()
        except Exception:
            pass

        defaults = {
            'promo_counter': '3401',
            'promo_growth_daily': '17',
            'site_tagline': 'Find a place worth leaving the house for.',
            'payment_paybill': '',
            'payment_till': '',
            'payment_name': 'Open Road Adventures',
            'contact_phone': '',
            'contact_email': '',
            'ticket_secret': None,
        }
        for key, value in defaults.items():
            exists = db.execute('SELECT 1 FROM settings WHERE key=?', (key,)).fetchone()
            if not exists:
                value = value if value is not None else __import__('secrets').token_urlsafe(48)
                db.execute('INSERT INTO settings(key,value) VALUES(?,?)', (key, value))

        # Rich starter content: public inspiration and trip options. Admin can edit/remove any of it.
        if db.execute('SELECT COUNT(*) n FROM destinations').fetchone()['n'] == 0:
            destinations = [
                ('diani-beach','Diani Beach','White sand. Warm water. A very good reason to disappear for a weekend.','Beach · boat · slow mornings',8500,'https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Diani_Beach,_Kenya.jpg',1),
                ('hells-gate',"Hell's Gate",'Cycle under giant cliffs, then leave with a story your group will keep retelling.','Cycle · hike · cliffs',4200,'https://commons.wikimedia.org/wiki/Special:FilePath/Kenya,_Hell%27s_Gate_(45282893295).jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Kenya,_Hell%27s_Gate_(45282893295).jpg',2),
                ('mount-longonot','Mount Longonot','A proper hike, a crater view and bragging rights afterwards.','Hike · crater · challenge',3800,'https://commons.wikimedia.org/wiki/Special:FilePath/Mount_Longonot_in_Kenya.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Mount_Longonot_in_Kenya.jpg',3),
                ('lake-naivasha','Lake Naivasha','Boat rides, open skies and the kind of afternoon that fixes a whole week.','Boat · lake · chill',3600,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Naivasha.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Lake_Naivasha.jpg',4),
                ('nanyuki','Nanyuki + Mt Kenya','Cooler air, big mountain views and a road trip worth waking up early for.','Road trip · mountain · photos',6500,'https://commons.wikimedia.org/wiki/Special:FilePath/View_of_Mt._Kenya_from_Nanyuki_Municipality.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:View_of_Mt._Kenya_from_Nanyuki_Municipality.jpg',5),
                ('watamu','Watamu','Turquoise water, reef life and coastal energy without the city rush.','Beach · reef · coast',9500,'https://commons.wikimedia.org/wiki/Special:FilePath/Watamu_beach.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Watamu_beach.jpg',6),
                ('amboseli','Amboseli','Elephants, huge skies and Mount Kilimanjaro doing the heavy lifting for the photos.','Safari · views · wildlife',14500,'https://commons.wikimedia.org/wiki/Special:FilePath/Amboseli_National_Park,_Kenya.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Amboseli_National_Park,_Kenya.jpg',7),
                ('masai-mara','Maasai Mara','Golden grasslands, wildlife and a road trip people remember for years.','Safari · wildlife · sunrise',19500,'https://commons.wikimedia.org/wiki/Special:FilePath/Maasai_Mara_National_Reserve.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Maasai_Mara_National_Reserve.jpg',8),
                ('samburu','Samburu','A wilder road, dramatic landscapes and a very different side of Kenya.','Safari · culture · wild',17500,'https://commons.wikimedia.org/wiki/Special:FilePath/Samburu_National_Reserve.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Samburu_National_Reserve.jpg',9),
                ('kakamega','Kakamega Forest','Green everywhere, fresh air and a forest weekend that feels far away.','Forest · waterfalls · nature',7200,'https://commons.wikimedia.org/wiki/Special:FilePath/Kakamega_Forest.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Kakamega_Forest.jpg',10),
            ]
            for row in destinations:
                db.execute('INSERT INTO destinations(slug,title,subtitle,vibe,price_from,cover_image,credit,source_url,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,datetime(\'now\'))', row)

        if db.execute('SELECT COUNT(*) n FROM trips').fetchone()['n'] == 0:
            trips = [
                ('ngare-ndare-escape','Ngare Ndare Escape','Ngare Ndare','Blue pools, canopy walks and a proper green reset. One of those days where everyone gets off the bus smiling.','2026-09-19',3500,40,'CBD · Westlands','05:30 — Meet\n06:00 — Leave Nairobi\n09:30 — Forest arrival\n10:00 — Canopy walk\n13:00 — Lunch\n15:00 — Blue pools & free time\n18:00 — Head back','Transport · entry · guided experience','Personal shopping · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Ngare_Ndare_Forest.jpg','published'),
                ('hells-gate-day-out',"Hell's Gate Day Out", "Hell's Gate",'A playful Rift Valley day: cycles, cliffs, lunch and sunset air.','2026-09-26',4200,40,'CBD · Westlands','06:00 — Departure\n08:30 — Breakfast stop\n10:00 — Cycling\n13:00 — Lunch\n15:00 — Gorge area & photos\n17:00 — Return','Transport · entry · bike package','Personal snacks · optional activities','https://commons.wikimedia.org/wiki/Special:FilePath/Kenya,_Hell%27s_Gate_(45282893295).jpg','published'),
                ('longonot-naivasha','Longonot + Naivasha','Longonot · Naivasha','Morning hike, boat ride later. Two completely different moods in one day.','2026-10-03',4800,38,'CBD · Westlands','05:30 — Departure\n08:00 — Hike begins\n12:30 — Lunch\n14:00 — Naivasha boat ride\n16:00 — Chill by the lake\n18:00 — Return','Transport · park entry · boat ride','Personal gear · breakfast','https://commons.wikimedia.org/wiki/Special:FilePath/Mount_Longonot_in_Kenya.jpg','published'),
                ('nanyuki-weekender','Nanyuki Weekend','Nanyuki · Mt Kenya','Cool weather, mountain views, good food and a slow weekend up north.','2026-10-10',6500,32,'CBD · Westlands','Day 1 — Road trip & town\nDay 1 — Check-in & dinner\nDay 2 — Mountain-view morning\nDay 2 — Farm / nature stop\nDay 2 — Back to Nairobi','Transport · stay · selected experiences','Drinks · personal shopping','https://commons.wikimedia.org/wiki/Special:FilePath/View_of_Mt._Kenya_from_Nanyuki_Municipality.jpg','published'),
                ('diani-sun-run','Diani Sun Run','Diani Beach','Three days of sand, ocean, boat time and absolutely no unnecessary urgency.','2026-10-23',12500,34,'CBD · JKIA pickup options','Friday — Travel & check-in\nSaturday — Beach + boat\nSaturday night — Coastal evening\nSunday — Free morning\nSunday — Return','Transport · accommodation · selected activities','Personal shopping · optional upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','published'),
                ('watamu-blue-weekend','Watamu Blue Weekend','Watamu','A coastal weekend for people who need a reset more than another plan.','2026-11-06',13500,34,'CBD · JKIA pickup options','Friday — Travel & check-in\nSaturday — Coast day\nSaturday — Boat / reef experience\nSunday — Beach morning\nSunday — Return','Transport · accommodation · selected activities','Personal shopping · optional upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Watamu_beach.jpg','published'),
                ('amboseli-skyline','Amboseli Skyline','Amboseli','Safari roads, elephants and one of Kenya’s most ridiculous views.','2026-11-20',16500,32,'CBD','Friday — Travel\nSaturday — Safari day\nSaturday — Sunset photos\nSunday — Morning game drive\nSunday — Return','Transport · stay · park entry · selected game drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Amboseli_National_Park,_Kenya.jpg','published'),
                ('mara-first-light','Mara First Light','Maasai Mara','Sunrise game drives, wide-open country and a weekend that feels like a movie.','2026-12-04',22000,30,'CBD','Friday — Travel\nSaturday — Full safari day\nSunday — Sunrise drive\nSunday — Return','Transport · stay · park entry · selected game drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Maasai_Mara_National_Reserve.jpg','published'),
            ]
            for slug,title,dest,desc,dt,price,cap,pickup,itinerary,inc,exc,img,status in trips:
                db.execute('INSERT INTO trips(slug,title,destination,description,date,price,capacity,pickup,itinerary,included,excluded,cover_image,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime(\'now\'))',(slug,title,dest,desc,dt,price,cap,pickup,itinerary,inc,exc,img,status))

        # Expand the public trip catalogue on existing databases too.
        # These are intentionally varied by destination, duration, price and pace so search results
        # are useful instead of sparse. Existing admin-created trips are never removed or overwritten.
        expanded_trips = [
            ('nairobi-city-break','Nairobi City Break','Nairobi','A city day built around food, culture, shopping and easy group movement.','2026-09-12',1800,40,'CBD · Westlands','09:00 — Meet in CBD\n10:00 — City experience\n13:00 — Lunch\n15:00 — Market / gallery stop\n17:00 — Finish','Transport between planned stops · selected entry','Personal shopping · meals unless stated','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_city_view.jpg','published'),
            ('nairobi-national-park-run','Nairobi National Park Run','Nairobi National Park · Nairobi','An easy Nairobi escape: wildlife, fresh air and back before the city feels too far away.','2026-09-13',2600,40,'CBD · Westlands','06:00 — Meet\n06:30 — Park departure\n07:00 — Game drive\n11:30 — Brunch stop\n14:00 — Return','Transport · park entry · guided drive','Personal meals · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_National_Park.jpg','published'),
            ('karura-green-morning','Karura Green Morning','Karura Forest · Nairobi','A lighter local adventure for people who want nature without leaving Nairobi.','2026-09-14',1500,35,'CBD · Westlands','07:30 — Meet\n08:00 — Forest arrival\n08:30 — Walk / waterfalls\n12:00 — Picnic time\n14:00 — Return','Transport · entry · guided route','Personal food · optional activities','https://commons.wikimedia.org/wiki/Special:FilePath/Karura_Forest.jpg','published'),
            ('ngong-hills-half-day','Ngong Hills Half Day','Ngong Hills','Fresh air, views and a proper walk without committing your whole weekend.','2026-09-15',1700,35,'CBD · Westlands','07:00 — Meet\n08:00 — Trail start\n11:30 — Summit break\n13:00 — Lunch\n15:00 — Nairobi return','Transport · trail coordination','Lunch · personal gear','https://commons.wikimedia.org/wiki/Special:FilePath/Ngong_Hills.jpg','published'),
            ('limuru-tea-country','Limuru Tea Country','Limuru','Cool-weather roads, green tea country and a slower day outside Nairobi.','2026-09-16',2200,35,'CBD · Westlands','08:00 — Meet\n09:00 — Leave Nairobi\n10:30 — Tea-country stop\n13:00 — Lunch\n15:00 — Scenic return','Transport · selected experience','Personal purchases · meals unless stated','https://commons.wikimedia.org/wiki/Special:FilePath/Limuru_tea_plantation.jpg','published'),
            ('thika-fourteen-falls','Thika + Fourteen Falls','Thika','A budget-friendly day for waterfalls, photos, fresh air and a little chaos with friends.','2026-09-17',2400,40,'CBD · Thika Road','08:00 — Meet\n09:00 — Thika stop\n10:30 — Fourteen Falls\n13:00 — Picnic / lunch\n16:00 — Return','Transport · entry · guided timing','Personal food · activities not listed','https://commons.wikimedia.org/wiki/Special:FilePath/Fourteen_Falls.jpg','published'),
            ('nairobits-mombasa-road','Nairobi to Mombasa Weekend','Mombasa','A proper coast run with city energy, beach time and a flexible weekend pace.','2026-09-25',7800,36,'CBD · JKIA options','Friday — Travel\nSaturday — Old Town / Fort area\nSaturday — Beach time\nSunday — Free morning\nSunday — Return','Transport · accommodation · selected activities','Personal shopping · upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Fort_Jesus_Mombasa.jpg','published'),
            ('mombasa-old-town','Mombasa Old Town Explorer','Mombasa Old Town','History, coastal food and wandering lanes for a compact city break.','2026-09-27',3900,35,'CBD · JKIA pickup options','06:00 — Travel / meetup\n10:00 — Old Town walk\n13:00 — Lunch\n15:00 — Fort area\n17:00 — Finish','Transport support · guided walking experience','Personal food · entry not listed','https://commons.wikimedia.org/wiki/Special:FilePath/Mombasa_Old_Town.jpg','published'),
            ('kilifi-weekend','Kilifi Weekend','Kilifi','A breezier coast weekend for a group that wants beach time without a packed schedule.','2026-10-02',9800,34,'CBD · JKIA pickup options','Friday — Travel & check-in\nSaturday — Beach / creek time\nSaturday — Sunset\nSunday — Slow morning\nSunday — Return','Transport · stay · selected activities','Personal shopping · upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Kilifi_Creek.jpg','published'),
            ('malindi-weekender','Malindi Weekender','Malindi','Coast, seafood, warm water and a weekend built around being outside.','2026-10-09',10500,34,'CBD · JKIA pickup options','Friday — Travel\nSaturday — Coast day\nSunday — Old town / beach\nSunday — Return','Transport · accommodation · selected activities','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Malindi_Beach.jpg','published'),
            ('shimba-hills-safari','Shimba Hills Safari','Shimba Hills','Forest, wildlife and coastal highlands in one memorable day.','2026-10-11',6200,32,'Mombasa · Diani pickup options','06:00 — Pickup\n08:00 — Game drive\n12:30 — Lunch\n14:00 — Viewpoint / forest stop\n17:00 — Return','Transport · park entry · game drive','Personal meals · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Shimba_Hills.jpg','published'),
            ('tsavo-west-run','Tsavo West Run','Tsavo West','Red-earth safari roads, viewpoints and wildlife for the serious weekend crew.','2026-10-16',11800,30,'Nairobi · Mombasa options','Friday — Travel\nSaturday — Safari day\nSaturday — Sunset\nSunday — Morning drive\nSunday — Return','Transport · stay · park entry · selected drives','Personal expenses · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Tsavo_West_National_Park.jpg','published'),
            ('tsavo-east-escape','Tsavo East Escape','Tsavo East','Big landscapes and a classic safari road trip at a lower price point than a luxury run.','2026-10-23',10500,30,'Nairobi · Mombasa options','Friday — Travel\nSaturday — Full-day game drive\nSunday — Morning drive\nSunday — Return','Transport · stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Tsavo_East_National_Park.jpg','published'),
            ('sgr-coast-hop','SGR Coast Hop','Mombasa','A cost-conscious coast plan for people who want the railway journey to be part of the adventure.','2026-10-30',7200,40,'Nairobi Terminus · Mombasa','Friday — SGR travel\nSaturday — Beach / Old Town\nSunday — Free morning\nSunday — SGR return','Planned SGR segment · stay · selected activities','Meals · personal shopping','https://commons.wikimedia.org/wiki/Special:FilePath/Mombasa_beach.jpg','published'),
            ('naivasha-budget-day','Naivasha Budget Day','Naivasha','One of the easiest group escapes: lake air, a boat option and a comfortable return time.','2026-09-20',3000,42,'CBD · Westlands','07:00 — Meet\n08:00 — Leave Nairobi\n10:00 — Lake area\n12:00 — Lunch\n14:00 — Boat option\n17:00 — Return','Transport · selected lake experience','Meals · optional activities','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Naivasha.jpg','published'),
            ('naivasha-hells-gate','Naivasha + Hell\'s Gate','Naivasha · Hell\'s Gate','Two favourites in one affordable day for groups that want movement, scenery and a little adventure.','2026-10-04',4600,40,'CBD · Westlands','06:00 — Leave Nairobi\n08:30 — Cycling / park\n12:30 — Lunch\n14:00 — Lake stop\n17:00 — Return','Transport · entry · bike package','Meals · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Kenya,_Hell%27s_Gate_(45282893295).jpg','published'),
            ('sagana-adventure-day','Sagana Adventure Day','Sagana','Rafting-town energy, river scenery and an active day for the friends who refuse to sit still.','2026-09-21',5200,32,'CBD · Thika Road','06:00 — Meet\n08:30 — Arrive\n09:30 — Activity block\n13:00 — Lunch\n15:00 — Free / second activity\n18:00 — Return','Transport · selected activity package','Personal meals · optional upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Sagana_River.jpg','published'),
            ('kiambu-countryside','Kiambu Countryside Day','Kiambu','Green countryside, food stops and easy photo opportunities close to Nairobi.','2026-09-22',2100,36,'CBD · Westlands','08:00 — Meet\n09:00 — Countryside drive\n11:00 — Farm / experience\n13:00 — Lunch\n15:30 — Return','Transport · selected entry','Meals · personal purchases','https://commons.wikimedia.org/wiki/Special:FilePath/Kiambu,_Kenya.jpg','published'),
            ('muranga-waterfalls','Murang\'a Waterfalls Run','Murang\'a','A greener Central Kenya day with waterfalls, food and a road-trip feel.','2026-09-23',3300,38,'CBD · Thika Road','06:30 — Meet\n08:30 — Scenic drive\n10:30 — Waterfall walk\n13:00 — Lunch\n15:30 — Return','Transport · guide · selected entry','Personal food · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Chinga_Dam,_Murang%27a.jpg','published'),
            ('aberdare-forest-day','Aberdare Forest Day','Aberdare','Cool highlands, forest roads and a full-day reset far from the city noise.','2026-10-17',6800,30,'CBD · Westlands','05:30 — Meet\n06:00 — Depart\n10:00 — Forest experience\n13:00 — Lunch\n16:00 — Scenic stop\n19:00 — Return','Transport · selected entry · guided timing','Meals · personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Aberdare_Ranges.jpg','published'),
            ('lake-elementaita','Lake Elementaita Escape','Lake Elementaita','A calm lake day with birdlife, views and less pressure than the bigger weekend routes.','2026-09-28',3400,40,'CBD · Westlands','06:30 — Meet\n08:30 — Lake arrival\n10:00 — Viewpoint / walk\n13:00 — Lunch\n15:00 — Scenic loop\n18:00 — Return','Transport · selected entry','Meals · personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Elementaita.jpg','published'),
            ('sotik-green-highlands','Sotik Green Highlands','Sotik · Kericho','Tea-country scenery and cool air for groups that want something different from the usual safari run.','2026-11-13',8200,32,'CBD','Friday — Travel\nSaturday — Tea-country route\nSunday — Scenic morning\nSunday — Return','Transport · accommodation · selected experiences','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Kericho_tea.jpg','published'),
            ('kericho-tea-weekend','Kericho Tea Weekend','Kericho','A cooler highland weekend through tea country, viewpoints and quiet roads.','2026-12-11',8900,32,'CBD','Friday — Travel\nSaturday — Tea estate experience\nSunday — Town / viewpoint\nSunday — Return','Transport · stay · selected experience','Personal purchases · meals unless stated','https://commons.wikimedia.org/wiki/Special:FilePath/Kericho.jpg','published'),
            ('kisumu-lakefront','Kisumu Lakefront','Kisumu','Lake Victoria, city food and a relaxed western Kenya weekend.','2026-11-06',7600,34,'CBD','Friday — Travel & check-in\nSaturday — Lakefront / city\nSunday — Nature stop\nSunday — Return','Transport · stay · selected activities','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Kisumu_Impala_Sanctuary.jpg','published'),
            ('kakamega-forest-weekend','Kakamega Forest Weekend','Kakamega','A full forest weekend with walks, waterfalls and a slower pace.','2026-10-31',7800,32,'CBD','Friday — Travel\nSaturday — Forest walk\nSaturday — Waterfall stop\nSunday — Easy morning\nSunday — Return','Transport · stay · selected entry','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Kakamega_Forest.jpg','published'),
            ('kit-mikayi-day','Kit-Mikayi Day','Kisumu County','A culture-and-scenery day with time to explore and photograph one of western Kenya\'s better-known sites.','2026-11-07',5200,35,'Kisumu · Nairobi connections','07:00 — Depart\n09:00 — Site arrival\n11:00 — Explore\n13:00 — Lunch\n15:00 — Return','Transport · entry · guide','Meals · personal purchases','https://commons.wikimedia.org/wiki/Special:FilePath/Kit_Mikayi.jpg','published'),
            ('nanyuki-budget-run','Nanyuki Budget Run','Nanyuki','A more affordable Nanyuki day for mountain views, food and a little town wandering.','2026-09-29',4300,40,'CBD · Westlands','05:30 — Meet\n06:00 — Leave Nairobi\n10:00 — Nanyuki\n12:00 — Lunch\n14:00 — Scenic / farm stop\n18:00 — Return','Transport · selected experience','Meals · personal shopping','https://commons.wikimedia.org/wiki/Special:FilePath/View_of_Mt._Kenya_from_Nanyuki_Municipality.jpg','published'),
            ('nanyuki-luxury-weekend','Nanyuki Luxe Weekend','Nanyuki · Mt Kenya','A higher-end mountain weekend with better accommodation and a slower itinerary.','2026-11-27',14500,24,'CBD · Westlands','Friday — Travel & premium stay\nSaturday — Mountain-view experience\nSaturday evening — Dinner\nSunday — Farm / nature stop\nSunday — Return','Transport · premium accommodation · selected experiences','Personal shopping · optional upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Mt_Kenya_from_Nanyuki.jpg','published'),
            ('samburu-road-weekend','Samburu Road Weekend','Samburu','A longer northern road with dramatic landscapes, wildlife and a proper sense of distance.','2026-11-13',18500,28,'CBD','Friday — Travel\nSaturday — Full safari day\nSunday — Morning drive\nSunday — Return','Transport · stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Samburu_National_Reserve.jpg','published'),
            ('samburu-comfort-safari','Samburu Comfort Safari','Samburu','A more comfortable version of the northern circuit with fewer compromises on stay and pace.','2026-12-18',24500,20,'CBD · Westlands','Friday — Travel\nSaturday — Safari\nSaturday evening — Lodge dinner\nSunday — Sunrise drive\nSunday — Return','Transport · upgraded stay · park entry · selected drives','Personal expenses · premium extras','https://commons.wikimedia.org/wiki/Special:FilePath/Samburu_National_Reserve.jpg','published'),
            ('laikipia-wild','Laikipia Wild Weekend','Laikipia','Open country, wildlife and a quieter road-trip feeling outside the busiest circuits.','2026-12-04',19800,26,'CBD','Friday — Travel\nSaturday — Conservancy experience\nSunday — Morning drive\nSunday — Return','Transport · stay · selected wildlife experience','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Laikipia.jpg','published'),
            ('masai-mara-budget','Maasai Mara Budget Safari','Maasai Mara','A lower-priced Mara plan built around the core safari experience rather than luxury extras.','2026-09-25',14500,30,'CBD','Friday — Travel\nSaturday — Game drive\nSunday — Game drive\nSunday — Return','Transport · budget stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Maasai_Mara_National_Reserve.jpg','published'),
            ('mara-comfort','Mara Comfort Safari','Maasai Mara','A more comfortable Mara option with upgraded rooms and a little more breathing room.','2026-10-16',22000,24,'CBD','Friday — Travel\nSaturday — Full safari day\nSunday — Sunrise drive\nSunday — Return','Transport · upgraded stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Maasai_Mara_National_Reserve.jpg','published'),
            ('mara-premium','Mara Premium Escape','Maasai Mara','A premium weekend for a smaller group that wants comfort, scenery and long safari days.','2026-11-06',32000,16,'CBD · Westlands','Friday — Premium travel\nSaturday — Full safari day\nSunday — Sunrise drive\nSunday — Return','Transport · premium stay · park entry · selected drives','Personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Maasai_Mara_National_Reserve.jpg','published'),
            ('amboseli-budget','Amboseli Budget Escape','Amboseli','The essential Amboseli experience at a friendlier price, with the mountain doing the rest.','2026-10-09',12000,32,'CBD','Friday — Travel\nSaturday — Safari day\nSunday — Morning drive\nSunday — Return','Transport · stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Amboseli_National_Park,_Kenya.jpg','published'),
            ('amboseli-comfort','Amboseli Comfort Safari','Amboseli','A polished Amboseli weekend with comfortable rooms, game drives and easy pacing.','2026-12-04',20500,24,'CBD','Friday — Travel\nSaturday — Safari\nSunday — Sunrise / mountain views\nSunday — Return','Transport · upgraded stay · park entry · selected drives','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Amboseli_National_Park,_Kenya.jpg','published'),
            ('chale-island-splash','Chale Island Splash','South Coast','A premium coastal escape for a small group that wants the sea and the best part of doing less.','2026-12-18',28500,20,'Nairobi · Diani pickup options','Friday — Travel\nSaturday — Island / beach time\nSunday — Slow morning\nSunday — Return','Transport · accommodation · selected island experience','Personal extras · upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Chale_Island.jpg','published'),
            ('diani-budget','Diani Budget Weekend','Diani Beach','A coast trip stripped to the good bits: travel, beach time, one experience and room to breathe.','2026-10-16',9200,38,'CBD · JKIA options','Friday — Travel\nSaturday — Beach + activity\nSunday — Free morning\nSunday — Return','Transport · stay · selected activity','Personal shopping · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','published'),
            ('diani-comfort','Diani Comfort Weekend','Diani Beach','A comfortable coast weekend with better stay options and enough downtime.','2026-11-13',15500,28,'CBD · JKIA options','Friday — Travel & check-in\nSaturday — Beach + boat\nSunday — Leisure morning\nSunday — Return','Transport · upgraded stay · selected activities','Personal shopping · upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','published'),
            ('watamu-budget','Watamu Budget Weekend','Watamu','A value coast weekend for swimmers, beach lovers and people who want the sea without the premium price.','2026-10-23',9500,38,'CBD · JKIA options','Friday — Travel\nSaturday — Beach / creek\nSunday — Free morning\nSunday — Return','Transport · stay · selected activities','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Watamu_beach.jpg','published'),
            ('watamu-comfort','Watamu Comfort Weekend','Watamu','A more polished Watamu stay with boat time and plenty of unplanned beach hours.','2026-12-04',17500,26,'CBD · JKIA options','Friday — Travel\nSaturday — Reef / boat\nSunday — Beach morning\nSunday — Return','Transport · upgraded stay · selected activities','Personal shopping · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Watamu_beach.jpg','published'),
            ('mount-longonot-budget','Mount Longonot Budget Hike','Mount Longonot','A straightforward hiking day for groups that want the challenge without the luxury extras.','2026-09-19',2400,40,'CBD · Westlands','05:30 — Meet\n07:30 — Trail start\n12:30 — Summit / descent\n14:00 — Lunch\n18:00 — Return','Transport · park entry · hike coordination','Lunch · personal gear','https://commons.wikimedia.org/wiki/Special:FilePath/Mount_Longonot_in_Kenya.jpg','published'),
            ('mount-longonot-combo','Longonot + Lake Combo','Mount Longonot · Naivasha','Hike first, then slow down beside the lake. A good value full day.','2026-10-10',5000,36,'CBD · Westlands','05:30 — Depart\n08:00 — Hike\n13:00 — Lunch\n14:30 — Lake stop\n18:00 — Return','Transport · park entry · selected lake activity','Meals · personal gear','https://commons.wikimedia.org/wiki/Special:FilePath/Mount_Longonot_in_Kenya.jpg','published'),
            ('ngare-ndare-premium','Ngare Ndare Premium Day','Ngare Ndare','A smaller-group version with extra comfort around transport, timing and the forest experience.','2026-10-24',6200,20,'CBD · Westlands','05:00 — Meet\n06:00 — Premium departure\n09:30 — Forest\n10:00 — Canopy experience\n13:00 — Lunch\n16:30 — Return','Transport · entry · guided experience · lunch','Personal shopping · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Ngare_Ndare_Forest.jpg','published'),
            ('naivasha-luxury-day','Naivasha Luxe Day','Naivasha','A calmer, premium lake day with better dining and private-feel group logistics.','2026-11-21',8500,20,'CBD · Westlands','07:00 — Private-feel departure\n09:30 — Lake experience\n12:30 — Lunch\n14:30 — Boat / nature stop\n17:00 — Return','Transport · selected premium experiences','Personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Naivasha.jpg','published'),
            ('nairobi-food-and-art','Nairobi Food + Art Day','Nairobi','For a group that wants an experience rather than a long drive: food, art and city energy.','2026-10-03',3200,32,'CBD · Westlands','10:00 — Meet\n11:00 — Gallery / studio\n13:00 — Lunch\n15:00 — Market / art stop\n18:00 — Finish','Transport between planned stops · selected entry','Food · personal shopping','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_city_view.jpg','published'),
            ('nairobi-premium-experience','Nairobi Premium Experience','Nairobi','A smaller-group city day with curated stops, comfortable transport and plenty of time for photos.','2026-11-28',7800,16,'CBD · Westlands','10:00 — Meet\n11:00 — Curated city route\n13:00 — Premium lunch\n15:00 — Experience stop\n18:00 — Finish','Private-feel transport · selected premium experiences','Personal shopping · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_city_view.jpg','published'),
            ('nairobi-night-out','Nairobi Night Out','Nairobi','An evening plan for friends who want food, city lights and a simple way to coordinate the night.','2026-10-31',3500,30,'Westlands · Kilimani','17:00 — Meet\n18:00 — Dinner\n20:00 — Experience stop\n22:30 — Finish','Planned transport between stops','Food · drinks · personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_night.jpg','published'),
            ('nakuru-city-lake','Nakuru + Lake Day','Nakuru · Lake Nakuru','A Central Rift day blending town food, lake scenery and a short nature escape.','2026-10-24',4600,38,'CBD · Westlands','06:00 — Meet\n08:30 — Nakuru\n10:00 — Nature stop\n13:00 — Lunch\n15:00 — Scenic route\n18:30 — Return','Transport · selected entry','Meals · personal shopping','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Nakuru.jpg','published'),
            ('lake-nakuru-safari','Lake Nakuru Safari','Lake Nakuru','A focused safari day for a group that wants wildlife without the longer northern circuits.','2026-11-14',7600,32,'CBD','05:00 — Depart\n08:30 — Park arrival\n09:00 — Game drive\n13:00 — Lunch\n15:30 — Final drive\n19:00 — Return','Transport · park entry · selected game drive','Meals · personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Nakuru.jpg','published'),
            ('ol-pejeta-budget','Ol Pejeta Budget Safari','Ol Pejeta','A practical northern safari choice with wildlife, conservation and a full weekend road feeling.','2026-11-20',13800,30,'CBD','Friday — Travel\nSaturday — Conservancy day\nSunday — Morning experience\nSunday — Return','Transport · stay · selected entry and experiences','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Ol_Pejeta.jpg','published'),
            ('ol-pejeta-comfort','Ol Pejeta Comfort Safari','Ol Pejeta','A more comfortable conservancy weekend for smaller groups and a calmer pace.','2026-12-12',22800,22,'CBD · Westlands','Friday — Travel\nSaturday — Full conservancy day\nSunday — Morning experience\nSunday — Return','Transport · upgraded stay · selected experiences','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Ol_Pejeta.jpg','published'),
            ('lake-baringo-weekend','Lake Baringo Weekend','Lake Baringo','A more adventurous Rift Valley weekend of boats, birds and wide open water.','2026-12-04',9800,30,'CBD','Friday — Travel\nSaturday — Lake / boat experience\nSunday — Nature morning\nSunday — Return','Transport · accommodation · selected boat experience','Personal expenses','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Baringo.jpg','published'),
            ('lake-bogoria-day','Lake Bogoria Day','Lake Bogoria','A striking Rift Valley day for hot springs, lake views and a long scenic road.','2026-10-17',5800,36,'CBD','05:00 — Depart\n09:00 — Lake arrival\n10:00 — Explore\n13:00 — Lunch\n15:00 — Return route\n20:00 — Nairobi','Transport · selected entry','Meals · optional extras','https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Bogoria.jpg','published'),
            ('hells-gate-premium','Hell\'s Gate Private-Feel Day','Hell\'s Gate','A smaller group, smoother transport and more time for the parts everyone actually came for.','2026-11-07',7600,18,'CBD · Westlands','06:00 — Depart\n08:30 — Breakfast stop\n10:00 — Cycling / gorge\n13:00 — Lunch\n15:00 — Scenic stop\n18:00 — Return','Transport · entry · bike package · lunch','Personal extras','https://commons.wikimedia.org/wiki/Special:FilePath/Kenya,_Hell%27s_Gate_(45282893295).jpg','published'),
            ('coast-three-night','Kenya Coast Three-Night','Diani · Mombasa · Watamu options','A longer coastal route for people who want more than one beach and less rushing between them.','2027-01-08',18900,28,'CBD · JKIA options','Day 1 — Travel & check-in\nDay 2 — Beach / sea\nDay 3 — Coastal town / activity\nDay 4 — Return','Transport · accommodation · selected activities','Personal shopping · upgrades','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','published'),
        ]
        for row in expanded_trips:
            slug=row[0]
            if not db.execute('SELECT 1 FROM trips WHERE slug=?',(slug,)).fetchone():
                db.execute('INSERT INTO trips(slug,title,destination,description,date,price,capacity,pickup,itinerary,included,excluded,cover_image,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime(\'now\'))',row)

        if db.execute('SELECT COUNT(*) n FROM services').fetchone()['n'] == 0:
            services = [
                ('birthdays','Celebrations','Birthday adventures','A day out, a private plan or a surprise worth remembering.','Tell us the mood and the guest count. We can help shape the plan, logistics and optional ticketing.','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','orange',1,1,1),
                ('weddings','Celebrations','Weddings & receptions','From guest flow to digital invitations and QR entry, keep the important day beautiful and organised.','We can support the event flow or simply provide the ticketing layer.','https://commons.wikimedia.org/wiki/Special:FilePath/Diani_Beach,_Kenya.jpg','pink',1,1,2),
                ('graduations','Events','Graduations & campus','Big finish. Easy guest handling. A clean way to manage who comes in.','Perfect for graduation parties, campus dinners, class events and after-parties.','https://commons.wikimedia.org/wiki/Special:FilePath/University_of_Nairobi.jpg','blue',1,1,3),
                ('private-parties','Events','Private parties','Birthdays, reunions, house events, dinners and the plans nobody wants to coordinate in a group chat.','Bring the idea. We help make the practical bits simple.','https://commons.wikimedia.org/wiki/Special:FilePath/Kenya,_Hell%27s_Gate_(45282893295).jpg','lime',1,1,4),
                ('retreats','Groups','Retreats & team days','Schools, teams, clubs and organisations can hand us the planning brief.','We can help with location ideas, transport, schedules, attendee handling and tickets.','https://commons.wikimedia.org/wiki/Special:FilePath/Kakamega_Forest.jpg','aqua',1,1,5),
                ('event-ticketing','Ticketing','Ticketing for your own event','Already organised? Keep your event. Let us handle the digital passes and QR entry.','Branded tickets, attendee records and one-time scan validation.','https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_city_view.jpg','teal',1,1,6),
                ('corporate-days','Groups','Corporate & organisation days','Team days, launches, socials and staff experiences that need someone to own the details.','Useful when you want one place to coordinate the practical flow.','https://commons.wikimedia.org/wiki/Special:FilePath/Amboseli_National_Park,_Kenya.jpg','yellow',1,1,7),
                ('just-an-idea','Open brief','Got an idea?','Not sure what category it belongs in? Start anyway.','Tell us what you want to happen and we will help find the shape of it.','https://commons.wikimedia.org/wiki/Special:FilePath/Ngare_Ndare_Forest.jpg','white',1,1,8),
            ]
            for slug,category,title,subtitle,description,img,accent,ticketing,published,order in services:
                db.execute("INSERT INTO services(slug,category,title,subtitle,description,cover_image,accent,ticketing_available,published,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'))", (slug,category,title,subtitle,description,img,accent,ticketing,published,order))

        # Expanded Kenya destination + recurring trip catalogue. Existing records are never removed.
        # Each destination gets a pair of public price points so search results feel like a real catalogue,
        # not a handful of sparse examples. Repeated trips are renewed after expiry.
        expanded_places = [
            ('aberdare','Aberdare National Park','Moorlands, waterfalls, forests and cool mountain air.','Wildlife · forest · highlands',7500,'Aberdare_National_Park.jpg'),
            ('amboseli','Amboseli National Park','Elephants, open plains and huge Kilimanjaro views.','Safari · elephants · views',14500,'Amboseli_National_Park,_Kenya.jpg'),
            ('arusha-border','Loitoktok & Amboseli borderlands','A southern road with Maasai country, farms and mountain views.','Culture · views · road',6800,'Amboseli_National_Park,_Kenya.jpg'),
            ('bomas-of-kenya','Bomas of Kenya','A lively Nairobi culture stop with performances and traditions.','Culture · city · family',2800,'Nairobi_city_view.jpg'),
            ('bondo','Bondo & Lake Victoria','A quieter western lakeshore route with sunsets and village landscapes.','Lake · culture · sunset',6200,'Lake_Victoria_Kenya.jpg'),
            ('bungoma','Bungoma & Mt Elgon foothills','Western Kenya road scenery, markets and mountain country.','Culture · highlands · road',6200,'Mount_Elgon_National_Park.jpg'),
            ('chaka-ranch','Chaka Ranch','A family-friendly highland escape near Nyeri.','Family · outdoors · highlands',5800,'Aberdare_National_Park.jpg'),
            ('chogoria','Chogoria','The eastern gateway to dramatic Mt Kenya scenery and forest.','Mountain · forest · road',7200,'Mount_Kenya_National_Park.jpg'),
            ('chyulu-hills','Chyulu Hills National Park','Rolling volcanic hills between Amboseli and Tsavo landscapes.','Hiking · wilderness · views',9800,'Chyulu_Hills_National_Park.jpg'),
            ('city-of-kisumu','Kisumu City','Lake Victoria sunsets, city energy and easy western escapes.','Lake · city · sunset',5200,'Kisumu_city.jpg'),
            ('diani','Diani Beach','White sand, warm water and easy coastal weekends.','Beach · boat · coast',8500,'Diani_Beach,_Kenya.jpg'),
            ('elgeyo-marakwet','Elgeyo-Marakwet escarpment','Huge Rift views, hills and road-trip scenery.','Escarpment · hiking · views',7200,'Mount_Longonot_in_Kenya.jpg'),
            ('embu','Embu & waterfalls','Tea country, farms, falls and the eastern Mt Kenya foothills.','Highlands · waterfalls · food',5600,'Mount_Kenya_National_Park.jpg'),
            ('fort-jesus','Fort Jesus & Old Mombasa','History, Swahili streets and the Indian Ocean.','Culture · history · coast',4200,'Mombasa_Old_Town.jpg'),
            ('funzi','Funzi Island','Mangroves, tidal waterways and a slower south-coast day.','Island · boat · mangrove',9800,'Diani_Beach,_Kenya.jpg'),
            ('giraffe-centre','Giraffe Centre','An easy Nairobi wildlife and conservation outing.','Wildlife · Nairobi · family',2200,'Nairobi_city_view.jpg'),
            ('homa-bay','Homa Bay & Lake Victoria','Lakeshore scenery, islands and western Kenya culture.','Lake · culture · road',6500,'Lake_Victoria_Kenya.jpg'),
            ('isiolo','Isiolo & gateway north','A practical starting point for northern Kenya adventures.','Road · gateway · culture',6500,'Samburu_National_Reserve.jpg'),
            ('kajiado','Kajiado & Maasai country','Short southern drives, open country and cultural experiences.','Culture · short trip · views',5200,'Amboseli_National_Park,_Kenya.jpg'),
            ('kakamega','Kakamega Forest National Reserve','Tropical forest, birds, trails and waterfalls.','Forest · birding · hiking',7200,'Kakamega_Forest.jpg'),
            ('kapsabet','Kapsabet & tea country','Green tea landscapes and a western highland road.','Tea · highlands · road',5600,'Kakamega_Forest.jpg'),
            ('karura','Karura Forest','A city escape with trails, caves, falls and green canopy.','Forest · Nairobi · walking',2200,'Karura_Forest.jpg'),
            ('kericho','Kericho Tea Country','Rolling tea estates and cool western highlands.','Tea · highlands · photos',5200,'Kericho_tea.jpg'),
            ('kiambu','Kiambu coffee & farm country','A close-to-Nairobi farm, coffee and countryside escape.','Coffee · farms · day trip',3600,'Kiambu.jpg'),
            ('kilifi','Kilifi','Creeks, beaches and relaxed coastal weekends.','Beach · creek · coast',8200,'Kilifi.jpg'),
            ('kilaguni-tsavo','Kilaguni & Tsavo West','Lava landscapes, springs and wildlife in Tsavo West.','Safari · lava · wildlife',14800,'Tsavo_West_National_Park.jpg'),
            ('kisii','Kisii & highlands','Green hills, markets and a western road escape.','Highlands · culture · road',5600,'Kisii.jpg'),
            ('kisite','Kisite-Mpunguti Marine Park','Coral reefs, dolphins and Wasini Island waters.','Marine · boat · island',11800,'Kisite-Mpunguti_Marine_Park.jpg'),
            ('kitale','Kitale & Saiwa Swamp','Western highland nature with forest and rare antelope country.','Forest · wildlife · highlands',6800,'Saiwa_Swamp_National_Park.jpg'),
            ('lamu','Lamu Old Town','Swahili history, dhow rides and island evenings.','Island · culture · coast',12800,'Lamu_Old_Town.jpg'),
            ('lake-baringo','Lake Baringo','Birds, boats and wide-open Rift Valley water.','Lake · boat · birding',9800,'Lake_Baringo.jpg'),
            ('lake-bogoria','Lake Bogoria','Hot springs, escarpments and striking lake landscapes.','Lake · hot springs · views',5800,'Lake_Bogoria.jpg'),
            ('lake-elementaita','Lake Elementaita','Flamingos, birds and a compact Rift Valley escape.','Lake · birding · Rift',5200,'Lake_Elementaita.jpg'),
            ('lake-nakuru','Lake Nakuru National Park','Rhino country, lakeshore scenery and a manageable safari day.','Safari · rhino · lake',7600,'Lake_Nakuru.jpg'),
            ('lake-turkana','Lake Turkana','The Jade Sea, desert landscapes and a true northern adventure.','Desert · lake · expedition',24000,'Lake_Turkana.jpg'),
            ('loita','Loita Hills','Forest, hills and a wilder southern cultural route.','Hiking · culture · forest',11500,'Maasai_Mara_National_Reserve.jpg'),
            ('madiwa','Mfangano Island','Rock art, lake views and island life on Lake Victoria.','Island · culture · lake',9800,'Lake_Victoria_Kenya.jpg'),
            ('maasai-mara','Maasai Mara National Reserve','Classic safari country with big skies and wildlife.','Safari · wildlife · sunrise',19500,'Maasai_Mara_National_Reserve.jpg'),
            ('malindi','Malindi','Marine life, old Swahili history and beautiful beaches.','Beach · marine · history',8800,'Malindi.jpg'),
            ('marsabit','Marsabit National Park','A remote northern forest around a highland crater lake.','Safari · north · forest',22000,'Marsabit_National_Park.jpg'),
            ('meru','Meru National Park','River country, wildlife and a less-crowded safari feel.','Safari · rivers · wild',16200,'Meru_National_Park.jpg'),
            ('mombasa','Mombasa','Old Town, ocean air, food and coastal energy.','Coast · culture · food',6500,'Mombasa_Old_Town.jpg'),
            ('mount-elgon','Mount Elgon National Park','Forest, caves, hiking and wild western mountain country.','Mountain · caves · forest',9800,'Mount_Elgon_National_Park.jpg'),
            ('mount-kenya','Mount Kenya National Park','High-altitude scenery, forests and mountain trails.','Mountain · hiking · views',12500,'Mount_Kenya_National_Park.jpg'),
            ('mount-longonot','Mount Longonot','A crater hike and one of Kenya’s easiest big mountain days.','Hike · crater · challenge',3800,'Mount_Longonot_in_Kenya.jpg'),
            ('mwea','Mwea National Reserve','Wetlands, birds and an underrated central Kenya safari.','Wetland · birding · safari',8200,'Mwea_National_Reserve.jpg'),
            ('mombasa-old-town','Mombasa Old Town','Swahili lanes, Fort Jesus and historic coastal life.','History · culture · coast',4200,'Mombasa_Old_Town.jpg'),
            ('nakuru','Nakuru City','Rift Valley city life with easy access to the lake and parks.','City · lake · Rift',4600,'Lake_Nakuru.jpg'),
            ('nairobi-national-park','Nairobi National Park','Wildlife with the city skyline close behind.','Safari · Nairobi · wildlife',6200,'Nairobi_National_Park.jpg'),
            ('nairobi','Nairobi','Food, art, wildlife, shopping and city experiences.','City · food · art',3200,'Nairobi_city_view.jpg'),
            ('nanyuki','Nanyuki & Mt Kenya','Cooler air, mountain views and northern road-trip energy.','Mountain · road · photos',6500,'View_of_Mt._Kenya_from_Nanyuki_Municipality.jpg'),
            ('narok','Narok','A practical southern gateway to the Mara with town and countryside options.','Gateway · culture · road',5200,'Maasai_Mara_National_Reserve.jpg'),
            ('ndere','Ndere Island National Park','Island serenity on Lake Victoria with birds and views.','Island · lake · birding',9400,'Ndere_Island_National_Park.jpg'),
            ('ngare-ndare','Ngare Ndare Forest','Blue pools, canopy walks and cool forest air.','Forest · canopy · adventure',6200,'Ngare_Ndare_Forest.jpg'),
            ('ngong-hills','Ngong Hills','A near-Nairobi hiking favourite with broad views.','Hiking · views · day trip',3200,'Ngong_Hills.jpg'),
            ('ol-pejeta','Ol Pejeta Conservancy','Wildlife, conservation and a comfortable Laikipia weekend.','Safari · conservation · wildlife',13800,'Ol_Pejeta.jpg'),
            ('pate','Pate Island','Quiet island life, history and coastal culture north of Lamu.','Island · culture · coast',13500,'Lamu_Old_Town.jpg'),
            ('rusinga','Rusinga Island','Lake Victoria island scenery, culture and slow days.','Island · lake · culture',9800,'Lake_Victoria_Kenya.jpg'),
            ('ruma','Ruma National Park','Open valley scenery and rare roan antelope country.','Safari · valley · wildlife',10500,'Ruma_National_Park.jpg'),
            ('sagana','Sagana','River activities, rafting and a classic central Kenya day out.','River · adventure · day trip',4200,'Sagana.jpg'),
            ('samburu','Samburu National Reserve','Northern wildlife, dramatic landscapes and wide-open skies.','Safari · culture · wild',17500,'Samburu_National_Reserve.jpg'),
            ('sibiloi','Sibiloi National Park','Fossils, desert landscapes and the shores of Lake Turkana.','Fossils · desert · lake',23000,'Sibiloi_National_Park.jpg'),
            ('shimba-hills','Shimba Hills National Reserve','Green coastal hills and rare sable antelope country.','Hills · wildlife · coast',9200,'Shimba_Hills_National_Reserve.jpg'),
            ('siaya','Siaya & western Kenya','Green hills, culture and easy road-trip scenery.','Culture · highlands · road',5200,'Kisumu_city.jpg'),
            ('sotik','Sotik & Kericho','Tea country, farms and a cool southern-western road.','Tea · farms · road',5600,'Kericho_tea.jpg'),
            ('taita-hills','Taita Hills','Mountain scenery between Nairobi and the coast with safari options.','Hills · safari · road',12800,'Tsavo_West_National_Park.jpg'),
            ('takawiri','Takawiri Island','A Lake Victoria island escape with beach-like shores.','Island · lake · chill',10800,'Lake_Victoria_Kenya.jpg'),
            ('tsavo-east','Tsavo East National Park','Red earth, elephants and enormous open country.','Safari · elephants · wilderness',15200,'Tsavo_East_National_Park.jpg'),
            ('tsavo-west','Tsavo West National Park','Lava, springs, rhino country and dramatic sunsets.','Safari · lava · wildlife',14800,'Tsavo_West_National_Park.jpg'),
            ('turkana-central-island','Central Island National Park','Volcanic islands on Lake Turkana for true expedition days.','Island · volcano · lake',28000,'Central_Island_National_Park.jpg'),
            ('watamu','Watamu','Turquoise water, reef life and a calmer coast.','Beach · reef · coast',9500,'Watamu_beach.jpg'),
            ('west-kilimanjaro-view','Amboseli sunset country','Southern Kenya landscapes facing Kilimanjaro.','Views · safari · sunset',12000,'Amboseli_National_Park,_Kenya.jpg'),
            ('nyeri','Nyeri & Aberdare foothills','Tea, farms, waterfalls and Aberdare country.','Highlands · waterfalls · farms',5600,'Aberdare_National_Park.jpg'),
            ('muranga','Murang’a countryside','Tea, coffee, waterfalls and green central Kenya.','Coffee · waterfalls · farms',4200,'Murang_a.jpg'),
        ]
        img_base='https://commons.wikimedia.org/wiki/Special:FilePath/'
        fallback_imgs=[img_base+'Nairobi_city_view.jpg',img_base+'Diani_Beach,_Kenya.jpg',img_base+'Lake_Nakuru.jpg',img_base+'Kakamega_Forest.jpg']
        for slug,title,subtitle,vibe,price,imgfile in expanded_places:
            img=img_base+imgfile
            cur=db.execute('SELECT id FROM destinations WHERE slug=?',(slug,)).fetchone()
            if not cur:
                db.execute('INSERT INTO destinations(slug,title,subtitle,vibe,price_from,cover_image,credit,source_url,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,datetime(\'now\'))',
                           (slug,title,subtitle,vibe,price,img,'Wikimedia Commons','https://commons.wikimedia.org/',100+len(slug)))

            # Two practical price tiers per place. Use place-specific image first and common fallbacks second.
            for tier, mult, label in [('easy',1.0,'Easy'),('premium',1.8,'Premium')]:
                tslug=f'{slug}-{tier}'
                if db.execute('SELECT 1 FROM trips WHERE slug=?',(tslug,)).fetchone():
                    continue
                trip_title=f'{title} {label} Escape'
                trip_price=int(price*mult)
                desc=f'{subtitle} A bookable Open Road option with a clear plan, transport and room to enjoy the place.'
                itinerary='05:30 — Meet & depart\n09:00 — Arrival / first experience\n13:00 — Lunch / free time\n15:30 — Final stop\n18:30 — Return'
                included='Planned transport · selected entry / experience'
                excluded='Personal shopping · optional extras'
                imgs='|'.join([img]+fallback_imgs)
                db.execute('INSERT INTO trips(slug,title,destination,description,date,price,capacity,pickup,itinerary,included,excluded,cover_image,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime(\'now\'))',
                           (tslug,trip_title,title,desc,'2026-10-01' if tier=='easy' else '2026-11-15',trip_price,35,'CBD · Westlands',itinerary,included,excluded,imgs,'published'))

        # Existing and newly seeded trips are recurring departures. Expired unbooked departures roll forward a year.
        from datetime import date as _date
        def _renew_year(d):
            y,m,day=map(int,(d or '').split('-')); target_y=y+1
            if m==2 and day==29:
                day=28
            return f'{target_y:04d}-{m:02d}-{day:02d}'
        for tr in db.execute("SELECT id,date,status FROM trips WHERE date < date('now')").fetchall():
            active_booking=db.execute("SELECT 1 FROM bookings WHERE trip_id=? AND payment_status NOT IN ('cancelled') LIMIT 1",(tr['id'],)).fetchone()
            if not active_booking:
                new_date=tr['date']
                while new_date < __import__('datetime').date.today().isoformat():
                    new_date=_renew_year(new_date)
                db.execute("UPDATE trips SET date=?,status='published' WHERE id=?",(new_date,tr['id']))

        # Give every trip at least three rotating image candidates where possible.
        for tr in db.execute("SELECT id,destination,cover_image FROM trips").fetchall():
            cur=(tr['cover_image'] or '').split('|')
            cur=[x for x in cur if x]
            if len(cur)<3:
                extra=[]
                for x in fallback_imgs:
                    if x not in cur: extra.append(x)
                    if len(cur)+len(extra)>=3: break
                val='|'.join(cur+extra)
                if val!=tr['cover_image']:
                    db.execute('UPDATE trips SET cover_image=? WHERE id=?',(val,tr['id']))

        if db.execute('SELECT COUNT(*) n FROM posts').fetchone()['n'] == 0:
            db.execute('INSERT INTO posts(title,excerpt,body,image,media_url,category,published,created_at) VALUES(?,?,?,?,?,?,?,datetime(\'now\'))', (
                'The road is calling','Little previews, trip stories and places we keep thinking about.','This space grows after every adventure. Come back for photos, videos, stories and the next places worth leaving home for.','','','The road ahead',1))
        db.commit()
    app.teardown_appcontext(close_db)
