import sqlite3
from flask import current_app, g

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT NOT NULL,
 email TEXT UNIQUE NOT NULL, pin_hash TEXT NOT NULL, recovery_question TEXT NOT NULL,
 recovery_answer_hash TEXT NOT NULL, remember_token TEXT, remember_until TEXT,
 deleted_at TEXT, created_at TEXT NOT NULL
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
            },
            'bookings': {
                'payment_method': "ALTER TABLE bookings ADD COLUMN payment_method TEXT DEFAULT ''",
                'payment_reference': "ALTER TABLE bookings ADD COLUMN payment_reference TEXT DEFAULT ''",
                'paid_at': 'ALTER TABLE bookings ADD COLUMN paid_at TEXT',
                'followup_sent': 'ALTER TABLE bookings ADD COLUMN followup_sent INTEGER NOT NULL DEFAULT 0',
            },
            'trips': {'gallery': "ALTER TABLE trips ADD COLUMN gallery TEXT DEFAULT ''"},
        }
        for table, cols in upgrades.items():
            existing = _column_names(db, table)
            for col, sql in cols.items():
                if col not in existing:
                    db.execute(sql)

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
