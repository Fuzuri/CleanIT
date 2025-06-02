import sqlite3
from contextlib import contextmanager

DATABASE = 'cleaning.db'

def init_db():
    with db_connection() as conn:
        # Create services table
        conn.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            base_price REAL DEFAULT 0
        )''')

        # Create service_pricing table
        conn.execute('''
        CREATE TABLE IF NOT EXISTS service_pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            rule_type TEXT NOT NULL,
            label TEXT NOT NULL,
            price REAL NOT NULL,
            min_quantity INTEGER DEFAULT 0,
            max_quantity INTEGER DEFAULT 0,
            FOREIGN KEY (service_id) REFERENCES services (id)
        )''')

        # Existing bookings table (optional: you can remove pricing_id, bedroom_qty, bath_qty later)
        conn.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            pricing_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            customer_email TEXT NOT NULL,
            customer_phone TEXT NOT NULL,
            date TEXT NOT NULL,
            bedroom_qty INTEGER DEFAULT 1,
            bath_qty INTEGER DEFAULT 1,
            hours INTEGER DEFAULT 0,
            notes TEXT,
            total_price REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (service_id) REFERENCES services (id),
            FOREIGN KEY (pricing_id) REFERENCES service_pricing (id)
        )''')

        # New table to support multiple pricing options per booking
        conn.execute('''
        CREATE TABLE IF NOT EXISTS booking_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            pricing_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (booking_id) REFERENCES bookings (id),
            FOREIGN KEY (pricing_id) REFERENCES service_pricing (id)
        )''')

        #Payment methods table
        conn.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER NOT NULL,
            payment_method TEXT NOT NULL,
            payment_status TEXT NOT NULL DEFAULT 'pending',
            amount REAL NOT NULL,
            street_address TEXT,
            city TEXT,
            province TEXT,
            region TEXT,
            paid_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (booking_id) REFERENCES bookings (id)
        )''')

        
        # Optional: seed basic services if empty
        if not conn.execute('SELECT 1 FROM services LIMIT 1').fetchone():
            sample_services = [
                ('Regular Cleaning', 'General routine cleaning for homes and apartments.', 500),
                ('Deep Cleaning', 'Intensive cleaning including hard-to-reach areas.', 1000),
                ('End of Tenancy Cleaning', 'Thorough cleaning before moving out.', 2000),
                ('Domestic Cleaning', 'Recurring residential cleaning service.', 700),
                ('Disaster Cleaning & Restoration', 'Post-fire, flood, or emergency cleaning.', 3000),
                ('Event Cleaning', 'Pre- and post-event cleanup.', 1500),
                ('Outdoor Cleaning', 'Cleaning of outdoor spaces like patios and driveways.', 1000)
            ]
            conn.executemany('INSERT INTO services (name, description, base_price) VALUES (?, ?, ?)', sample_services)


@contextmanager
def db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    try:
        yield conn
    finally:
        conn.close()
