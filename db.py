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
 id INTEGER PRIMARY KEY AUTOINCREMENT, visitor_key TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, visitor_key_hash TEXT NOT NULL, device_key_hash TEXT NOT NULL,
 phone TEXT DEFAULT '', path TEXT NOT NULL, ip_address TEXT DEFAULT '', user_agent TEXT DEFAULT '',
 latitude REAL, longitude REAL, location_source TEXT DEFAULT '', created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_access_logs_created ON access_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_access_logs_device ON access_logs(device_key_hash);
CREATE INDEX IF NOT EXISTS idx_access_logs_user ON access_logs(user_id);
CREATE TABLE IF NOT EXISTS discovery_cache (
 id INTEGER PRIMARY KEY AUTOINCREMENT, cache_key TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL,
 url TEXT NOT NULL, source TEXT NOT NULL, snippet TEXT DEFAULT '', price REAL, price_text TEXT DEFAULT '',
 fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_discovery_cache_key ON discovery_cache(cache_key, fetched_at);
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, posted_by_user_id INTEGER NOT NULL, title TEXT NOT NULL, company TEXT DEFAULT '',
 country TEXT NOT NULL, location TEXT DEFAULT '', employment_type TEXT DEFAULT 'Full-time', salary TEXT DEFAULT '',
 description TEXT NOT NULL, apply_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'published', created_at TEXT NOT NULL,
 FOREIGN KEY(posted_by_user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
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
 ticket_style TEXT NOT NULL DEFAULT 'tiers',
 visibility TEXT NOT NULL DEFAULT 'public',
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
 admin_message TEXT DEFAULT '',
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
 phone TEXT DEFAULT '',
 email TEXT DEFAULT '',
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
 approval_method TEXT NOT NULL DEFAULT 'manual',
 ticket_status TEXT NOT NULL DEFAULT 'valid',
 design TEXT NOT NULL DEFAULT 'classic',
 checked_in_by TEXT DEFAULT '',
 checked_in_at TEXT,
 approved_at TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(event_id) REFERENCES event_ticket_events(id),
 FOREIGN KEY(attendee_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS payment_intents (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 reference TEXT UNIQUE NOT NULL,
 kind TEXT NOT NULL,
 target_id INTEGER NOT NULL,
 event_id INTEGER,
 phone TEXT NOT NULL,
 amount INTEGER NOT NULL,
 currency TEXT NOT NULL DEFAULT 'KES',
 provider TEXT NOT NULL DEFAULT 'mpesa',
 status TEXT NOT NULL DEFAULT 'created',
 fee_percent REAL NOT NULL DEFAULT 0,
 platform_fee INTEGER NOT NULL DEFAULT 0,
 net_amount INTEGER NOT NULL DEFAULT 0,
 merchant_request_id TEXT DEFAULT '',
 checkout_request_id TEXT DEFAULT '',
 provider_transaction_id TEXT DEFAULT '',
 result_code TEXT DEFAULT '',
 result_desc TEXT DEFAULT '',
 provider_response_json TEXT DEFAULT '',
 metadata_json TEXT DEFAULT '',
 paid_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
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
 signature_enabled INTEGER NOT NULL DEFAULT 0,
 background_style TEXT NOT NULL DEFAULT 'solid',
 custom_bg TEXT DEFAULT '',
 custom_text TEXT DEFAULT '',
 text_align TEXT NOT NULL DEFAULT 'left',
 font_scale INTEGER NOT NULL DEFAULT 100,
 border_style TEXT NOT NULL DEFAULT 'classic',
 texture_style TEXT NOT NULL DEFAULT 'none',
 accent_color TEXT DEFAULT '',
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

CREATE TABLE IF NOT EXISTS billing_profiles (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER NOT NULL,
 billing_id TEXT UNIQUE NOT NULL,
 place_type TEXT NOT NULL DEFAULT 'Apartment',
 place_name TEXT NOT NULL,
 owner_name TEXT DEFAULT '',
 phone TEXT DEFAULT '',
 address TEXT DEFAULT '',
 payment_to TEXT DEFAULT '',
 created_at TEXT NOT NULL,
 FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS billing_customers (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 profile_id INTEGER NOT NULL,
 name TEXT NOT NULL,
 phone TEXT DEFAULT '',
 unit_label TEXT DEFAULT '',
 rent_amount INTEGER NOT NULL DEFAULT 0,
 recurring_items_json TEXT NOT NULL DEFAULT '[]',
 notes TEXT DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(profile_id) REFERENCES billing_profiles(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS billing_invoices (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 profile_id INTEGER NOT NULL,
 customer_id INTEGER NOT NULL,
 invoice_number TEXT UNIQUE NOT NULL,
 issue_date TEXT NOT NULL,
 due_date TEXT DEFAULT '',
 property_name TEXT NOT NULL,
 owner_name TEXT DEFAULT '',
 recipient_name TEXT NOT NULL,
 recipient_unit TEXT DEFAULT '',
 notes TEXT DEFAULT '',
 payment_to TEXT DEFAULT '',
 subtotal INTEGER NOT NULL DEFAULT 0,
 paid_amount INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'unpaid',
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 FOREIGN KEY(profile_id) REFERENCES billing_profiles(id) ON DELETE CASCADE,
 FOREIGN KEY(customer_id) REFERENCES billing_customers(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS billing_invoice_items (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 invoice_id INTEGER NOT NULL,
 label TEXT NOT NULL,
 quantity INTEGER NOT NULL DEFAULT 1,
 amount INTEGER NOT NULL DEFAULT 0,
 FOREIGN KEY(invoice_id) REFERENCES billing_invoices(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS billing_receipts (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 profile_id INTEGER NOT NULL,
 customer_id INTEGER NOT NULL,
 invoice_id INTEGER,
 receipt_number TEXT UNIQUE NOT NULL,
 payment_date TEXT NOT NULL,
 property_name TEXT NOT NULL,
 owner_name TEXT DEFAULT '',
 recipient_name TEXT NOT NULL,
 recipient_unit TEXT DEFAULT '',
 payment_to TEXT DEFAULT '',
 amount_paid INTEGER NOT NULL DEFAULT 0,
 payment_method TEXT NOT NULL DEFAULT 'Cash',
 payment_reference TEXT DEFAULT '',
 note TEXT DEFAULT '',
 created_at TEXT NOT NULL,
 FOREIGN KEY(profile_id) REFERENCES billing_profiles(id) ON DELETE CASCADE,
 FOREIGN KEY(customer_id) REFERENCES billing_customers(id) ON DELETE CASCADE,
 FOREIGN KEY(invoice_id) REFERENCES billing_invoices(id) ON DELETE SET NULL
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
            'event_ticket_events': {
                'ticket_style': "ALTER TABLE event_ticket_events ADD COLUMN ticket_style TEXT NOT NULL DEFAULT 'tiers'",
                'visibility': "ALTER TABLE event_ticket_events ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'",
                'regular_price': 'ALTER TABLE event_ticket_events ADD COLUMN regular_price INTEGER NOT NULL DEFAULT 0',
                'vip_price': 'ALTER TABLE event_ticket_events ADD COLUMN vip_price INTEGER NOT NULL DEFAULT 0',
                'vvip_price': 'ALTER TABLE event_ticket_events ADD COLUMN vvip_price INTEGER NOT NULL DEFAULT 0',
                'scanner_code': 'ALTER TABLE event_ticket_events ADD COLUMN scanner_code TEXT',
            },
            'event_tickets': {
                'attendee_gender': "ALTER TABLE event_tickets ADD COLUMN attendee_gender TEXT NOT NULL DEFAULT ''",
                'attendee_phone': "ALTER TABLE event_tickets ADD COLUMN attendee_phone TEXT DEFAULT ''",
                'attendee_email': "ALTER TABLE event_tickets ADD COLUMN attendee_email TEXT DEFAULT ''",
                'ticket_tier': "ALTER TABLE event_tickets ADD COLUMN ticket_tier TEXT NOT NULL DEFAULT 'regular'",
                'source': "ALTER TABLE event_tickets ADD COLUMN source TEXT NOT NULL DEFAULT 'visitor'",
                'access_token': 'ALTER TABLE event_tickets ADD COLUMN access_token TEXT',
                'approval_method': "ALTER TABLE event_tickets ADD COLUMN approval_method TEXT NOT NULL DEFAULT 'manual'",
                'checked_in_by': "ALTER TABLE event_tickets ADD COLUMN checked_in_by TEXT DEFAULT ''",
            },
            'group_retreats': {
                'admin_message': "ALTER TABLE group_retreats ADD COLUMN admin_message TEXT DEFAULT ''",
            },
            'group_members': {
                'phone': "ALTER TABLE group_members ADD COLUMN phone TEXT DEFAULT ''",
                'email': "ALTER TABLE group_members ADD COLUMN email TEXT DEFAULT ''",
            },
            'billing_profiles': {
                'payment_to': "ALTER TABLE billing_profiles ADD COLUMN payment_to TEXT DEFAULT ''",
            },
            'billing_invoices': {
                'payment_to': "ALTER TABLE billing_invoices ADD COLUMN payment_to TEXT DEFAULT ''",
            },
            'billing_receipts': {
                'payment_to': "ALTER TABLE billing_receipts ADD COLUMN payment_to TEXT DEFAULT ''",
            },
            'stuff_cards': {
                'font_style': "ALTER TABLE stuff_cards ADD COLUMN font_style TEXT NOT NULL DEFAULT 'bold'",
                'shape_style': "ALTER TABLE stuff_cards ADD COLUMN shape_style TEXT NOT NULL DEFAULT 'sticky'",
                'design_style': "ALTER TABLE stuff_cards ADD COLUMN design_style TEXT NOT NULL DEFAULT 'sunny'",
                'qr_enabled': "ALTER TABLE stuff_cards ADD COLUMN qr_enabled INTEGER NOT NULL DEFAULT 1",
                'signature_enabled': "ALTER TABLE stuff_cards ADD COLUMN signature_enabled INTEGER NOT NULL DEFAULT 0",
                'background_style': "ALTER TABLE stuff_cards ADD COLUMN background_style TEXT NOT NULL DEFAULT 'solid'",
                'custom_bg': "ALTER TABLE stuff_cards ADD COLUMN custom_bg TEXT DEFAULT ''",
                'custom_text': "ALTER TABLE stuff_cards ADD COLUMN custom_text TEXT DEFAULT ''",
                'text_align': "ALTER TABLE stuff_cards ADD COLUMN text_align TEXT NOT NULL DEFAULT 'left'",
                'font_scale': "ALTER TABLE stuff_cards ADD COLUMN font_scale INTEGER NOT NULL DEFAULT 100",
                'border_style': "ALTER TABLE stuff_cards ADD COLUMN border_style TEXT NOT NULL DEFAULT 'classic'",
                'texture_style': "ALTER TABLE stuff_cards ADD COLUMN texture_style TEXT NOT NULL DEFAULT 'none'",
                'accent_color': "ALTER TABLE stuff_cards ADD COLUMN accent_color TEXT DEFAULT ''",
                'decoration': "ALTER TABLE stuff_cards ADD COLUMN decoration TEXT NOT NULL DEFAULT 'spark'",
                'format_style': "ALTER TABLE stuff_cards ADD COLUMN format_style TEXT NOT NULL DEFAULT 'square'",
            },
        }
        for table, cols in upgrades.items():
            existing = _column_names(db, table)
            for col, sql in cols.items():
                if col not in existing:
                    db.execute(sql)

        # Access logging was added after the original visitor-only analytics.
        if 'access_logs' not in {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS access_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, visitor_key_hash TEXT NOT NULL, device_key_hash TEXT NOT NULL, phone TEXT DEFAULT '', path TEXT NOT NULL, ip_address TEXT DEFAULT '', user_agent TEXT DEFAULT '', latitude REAL, longitude REAL, location_source TEXT DEFAULT '', created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_access_logs_created ON access_logs(created_at);
            CREATE INDEX IF NOT EXISTS idx_access_logs_device ON access_logs(device_key_hash);
            CREATE INDEX IF NOT EXISTS idx_access_logs_user ON access_logs(user_id);
            """)
        if 'discovery_cache' not in {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS discovery_cache (id INTEGER PRIMARY KEY AUTOINCREMENT, cache_key TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL, snippet TEXT DEFAULT '', price REAL, price_text TEXT DEFAULT '', fetched_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_discovery_cache_key ON discovery_cache(cache_key, fetched_at);
            CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, posted_by_user_id INTEGER NOT NULL, title TEXT NOT NULL, company TEXT DEFAULT '', country TEXT NOT NULL, location TEXT DEFAULT '', employment_type TEXT DEFAULT 'Full-time', salary TEXT DEFAULT '', description TEXT NOT NULL, apply_url TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'published', created_at TEXT NOT NULL, FOREIGN KEY(posted_by_user_id) REFERENCES users(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
            """)

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
        # Event and group retention is manual. The administrator controls archival/removal.

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
            'payment_business_shortcode': '',
            'payment_transaction_type': 'CustomerBuyGoodsOnline',
            'payment_currency': 'KES',
            'ticketing_fee_percent': '5',
            'event_mpesa_listener_token': '',
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


        # Expand the travel wall on existing installations without duplicating seeded places.
        starter_destination_additions = [
            ('mount-elgon','Mount Elgon','Highland landscapes, caves and a cooler western-Kenya change of scene.','Mountain · caves · highlands',9800,'https://commons.wikimedia.org/wiki/Special:FilePath/Mount_Elgon.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Mount_Elgon',11),
            ('kisumu','Kisumu','A Lake Victoria city break for food, sunsets, culture and an easy western-Kenya weekend.','Lake · city · culture',7600,'https://commons.wikimedia.org/wiki/Special:FilePath/Kisumu_Impala_Sanctuary.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Kisumu_Impala_Sanctuary.jpg',12),
            ('lake-victoria','Lake Victoria','Big water, breezes and western-Kenya days built around the lake.','Lake · views · slow days',7900,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Victoria.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lake_Victoria',13),
            ('kakamega-city','Kakamega','A western-Kenya base for forest days, food stops and short nature escapes.','Forest · local life · weekend',6800,'https://commons.wikimedia.org/wiki/Special:FilePath/Kakamega_Forest.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/File:Kakamega_Forest.jpg',14),
            ('kit-mikayi','Kit-Mikayi','A culture-and-scenery stop that pairs naturally with a Kisumu-area route.','Culture · rocks · day trip',6900,'https://commons.wikimedia.org/wiki/Special:FilePath/Kit_Mikayi.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Kit-Mikayi',15),
            ('kericho','Kericho','Green tea country, cooler air and a gentler road-trip mood.','Tea country · highlands · green',7000,'https://commons.wikimedia.org/wiki/Special:FilePath/Kericho.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Kericho',16),
            ('nairobi-national-park','Nairobi National Park','Wildlife close to the city for a half-day or easy group escape.','Wildlife · city · half day',4800,'https://commons.wikimedia.org/wiki/Special:FilePath/Nairobi_National_Park.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Nairobi_National_Park',17),
            ('karura','Karura Forest','A local green reset with trails and shaded space close to Nairobi.','Forest · walks · local',1800,'https://commons.wikimedia.org/wiki/Special:FilePath/Karura_Forest.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Karura_Forest',18),
            ('ngong-hills','Ngong Hills','Open ridgelines and a simple hiking day when you want movement without a full weekend.','Hike · views · day trip',2500,'https://commons.wikimedia.org/wiki/Special:FilePath/Ngong_Hills.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Ngong_Hills',19),
            ('nakuru','Nakuru','A Rift Valley base for lake days, wildlife and nearby nature stops.','Lake · wildlife · Rift Valley',6200,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Nakuru.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lake_Nakuru',20),
            ('lake-baringo','Lake Baringo','Wide-open water, birdlife and a road-trip feel that rewards a slower weekend.','Lake · boats · birds',8200,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Baringo.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lake_Baringo',21),
            ('lake-bogoria','Lake Bogoria','A striking Rift Valley stop for hot-spring country and big landscapes.','Lake · springs · Rift Valley',7600,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Bogoria.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lake_Bogoria',22),
            ('mombasa','Mombasa','A proper coastal city break with old-town wandering, food and sea air.','Coast · culture · city',9200,'https://commons.wikimedia.org/wiki/Special:FilePath/Mombasa_Old_Town.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Mombasa_Old_Town',23),
            ('malindi','Malindi','Warm coast days, marine experiences and an easy base for a small group getaway.','Coast · marine · slow days',9800,'https://commons.wikimedia.org/wiki/Special:FilePath/Malindi_Beach.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Malindi',24),
            ('kilifi','Kilifi','Creek views, open skies and a breezier coastal weekend.','Coast · creek · weekend',9500,'https://commons.wikimedia.org/wiki/Special:FilePath/Kilifi_Creek.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Kilifi',25),
            ('lamu','Lamu','A coastal island escape built around old-town atmosphere, sea time and slower days.','Island · culture · coast',11500,'https://commons.wikimedia.org/wiki/Special:FilePath/Lamu_Old_Town.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lamu_Old_Town',26),
            ('shimba-hills','Shimba Hills','Coastal highlands, forest and wildlife in a day that feels far from the beach strip.','Wildlife · forest · coast',7800,'https://commons.wikimedia.org/wiki/Special:FilePath/Shimba_Hills.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Shimba_Hills',27),
            ('tsavo-west','Tsavo West','A classic safari road with wide landscapes, wildlife and a long-drive feeling.','Safari · wildlife · road',14500,'https://commons.wikimedia.org/wiki/Special:FilePath/Tsavo_West_National_Park.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Tsavo_West_National_Park',28),
            ('meru-national-park','Meru National Park','A northern-eastern safari option with open country and a quieter circuit.','Safari · wildlife · north-east',15000,'https://commons.wikimedia.org/wiki/Special:FilePath/Meru_National_Park.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Meru_National_Park',29),
            ('marsabit','Marsabit','A longer northern road for people who enjoy the feeling of real distance.','North · road trip · wild',18500,'https://commons.wikimedia.org/wiki/Special:FilePath/Marsabit_National_Park.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Marsabit_National_Park',30),
            ('lake-turkana','Lake Turkana','A big northern-Kenya expedition idea for a group that wants something very different.','North · lake · expedition',24000,'https://commons.wikimedia.org/wiki/Special:FilePath/Lake_Turkana.jpg','Wikimedia Commons','https://commons.wikimedia.org/wiki/Category:Lake_Turkana',31),
        ]
        for row in starter_destination_additions:
            if not db.execute('SELECT 1 FROM destinations WHERE slug=?',(row[0],)).fetchone():
                db.execute("INSERT INTO destinations(slug,title,subtitle,vibe,price_from,cover_image,credit,source_url,sort_order,created_at) VALUES(?,?,?,?,?,?,?,?,?,datetime('now'))", row)

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

        if db.execute('SELECT COUNT(*) n FROM posts').fetchone()['n'] == 0:
            db.execute('INSERT INTO posts(title,excerpt,body,image,media_url,category,published,created_at) VALUES(?,?,?,?,?,?,?,datetime(\'now\'))', (
                'The road is calling','Little previews, trip stories and places we keep thinking about.','This space grows after every adventure. Come back for photos, videos, stories and the next places worth leaving home for.','','','The road ahead',1))
        db.commit()
    app.teardown_appcontext(close_db)
