import os
import json
import sqlite3
import shutil
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify, make_response, send_file
from services import get_all_services, get_service
from bookings import create_booking, get_booking
from database import init_db, db_connection
from collections import defaultdict
from functools import wraps

app = Flask(__name__)

# Initialize database
def init_db():
    """Initialize the database with required tables"""
    db_path = os.path.join(os.path.dirname(__file__), 'cleaning.db')
    
    with sqlite3.connect(db_path) as conn:
        # Create tables if they don't exist
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                base_price REAL NOT NULL,
                image_url TEXT
            );

            CREATE TABLE IF NOT EXISTS service_pricing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER,
                rule_type TEXT NOT NULL,
                label TEXT NOT NULL,
                price REAL NOT NULL,
                min_quantity INTEGER DEFAULT 0,
                max_quantity INTEGER DEFAULT 0,
                FOREIGN KEY (service_id) REFERENCES services (id)
            );

            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER,
                pricing_id INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_email TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                date TEXT NOT NULL,
                bedroom_qty INTEGER DEFAULT 0,
                bath_qty INTEGER DEFAULT 0,
                hours INTEGER DEFAULT 0,
                notes TEXT,
                total_price REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES services (id),
                FOREIGN KEY (pricing_id) REFERENCES service_pricing (id)
            );

            CREATE TABLE IF NOT EXISTS booking_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER,
                pricing_id INTEGER,
                quantity INTEGER DEFAULT 1,
                FOREIGN KEY (booking_id) REFERENCES bookings (id),
                FOREIGN KEY (pricing_id) REFERENCES service_pricing (id)
            );

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_id INTEGER UNIQUE,
                street_address TEXT,
                city TEXT,
                province TEXT,
                region TEXT,
                payment_method TEXT,
                payment_status TEXT DEFAULT 'pending',
                amount REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (booking_id) REFERENCES bookings (id)
            );
        ''')
        conn.commit()

# Initialize database on startup
init_db()

app.secret_key = os.urandom(24)

# Load services and pricing rules from JSON files into the database
def load_services_and_pricing():
    try:
        with open('services.txt') as f:
            services = json.load(f)

        with open('service_pricing.txt') as f:
            pricing_rules = json.load(f)

        with db_connection() as conn:
            # Clear existing services and pricing rules
            conn.execute('DELETE FROM service_pricing')
            conn.execute('DELETE FROM services')
            
            # Insert services from file
            for s in services:
                conn.execute(
                    'INSERT INTO services (id, name, base_price, description) VALUES (?, ?, ?, ?)',
                    (s['id'], s['name'], s['base_price'], s['description'])
                )
            
            # Insert pricing rules from file
            for p in pricing_rules:
                min_q = p.get('min_quantity', 0)
                max_q = p.get('max_quantity', 0)
                conn.execute(
                    '''INSERT INTO service_pricing 
                    (service_id, rule_type, label, price, min_quantity, max_quantity) 
                    VALUES (?, ?, ?, ?, ?, ?)''',
                    (p['service_id'], p['rule_type'], p['label'], p['price'], min_q, max_q)
                )
            conn.commit()
    except Exception as e:
        print(f"Error loading services and pricing: {str(e)}")
        raise

# Load services and pricing on startup
load_services_and_pricing()

# Back up all bookings (with service info and options) into a JSON file
def backup_to_json(filename='backup.json'):
    tables = ['services', 'service_pricing', 'bookings', 'booking_options', 'payments']
    backup_data = {}

    with db_connection() as conn:
        for table in tables:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            # Convert sqlite3.Row objects to dicts
            backup_data[table] = [dict(row) for row in rows]

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2, default=str)  # default=str to handle datetime if any

    return filename

# Calculate total price based on service type and dynamic pricing rules
def calculate_price(service_id, bedroom_qty=1, bath_qty=1, hours=0, pricing_id=None):
    service = get_service(service_id)
    if not service:
        raise ValueError("Invalid service ID")

    total_price = service['base_price']

    for p in service['pricing']:
        rule = p['rule_type']
        if rule == 'per_room':
            if 'Bedroom' in p['label'] and bedroom_qty > 1:
                total_price += p['price'] * (bedroom_qty - 1)
            if 'Bathroom' in p['label'] and bath_qty > 1:
                total_price += p['price'] * (bath_qty - 1)
        elif rule == 'hourly' and hours > 0:
            total_price += p['price'] * hours
        elif rule in ['flat_rate', 'flat_tier'] and pricing_id and p['id'] == pricing_id:
            total_price = p['price']

    return total_price

def get_payment(booking_id):
    with db_connection() as conn:
        cur = conn.execute('SELECT * FROM payments WHERE booking_id = ?', (booking_id,))
        return cur.fetchone()
    
def check_auth(username, password):
    return username == AUTH_USERNAME and password == AUTH_PASSWORD

def authenticate():
    """Sends 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials.', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


#Home page route: display list of services
@app.route('/')
def home():
    services = get_all_services()
    return render_template('index.html', services=services)

@app.route('/services')
def services():
    services = get_all_services()
    return render_template('services.html', services=services)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/payment-options')
def payment_options():
    return render_template('payment_options.html')

@app.route('/returns')
def returns():
    return render_template('returns.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/guarantee')
def guarantee():
    return render_template('guarantee.html')

@app.route('/service/<type>')
def service(type):
    return render_template('service.html', service_type=type)

#Booking route: handle booking form submission and display booking page
@app.route('/book/<int:service_id>', methods=['GET', 'POST'])
def book(service_id):
    service = get_service(service_id)
    if not service:
        return "Service not found", 404

    if request.method == 'POST':
        try:
            bedroom_qty = int(request.form.get('bedroom_qty', 1))
            bath_qty = int(request.form.get('bath_qty', 1))
            hours = int(request.form.get('hours', 0))
            
            # Get pricing_id and ensure it's not None
            pricing_id_str = request.form.get("pricing_id")
            if not pricing_id_str:
                return "Pricing option is required", 400
            pricing_id = int(pricing_id_str)

            total_price = calculate_price(
                service_id,
                bedroom_qty=bedroom_qty,
                bath_qty=bath_qty,
                hours=hours,
                pricing_id=pricing_id
            )

        except ValueError as e:
            return f"Input Error: {str(e)}", 400

        booking_id = create_booking(service_id, pricing_id, {
            'name': request.form['name'],
            'email': request.form['email'],
            'phone': request.form['phone'],
            'date': request.form['date'],
            'bedroom_qty': bedroom_qty,
            'bath_qty': bath_qty,
            'hours': hours,
            'notes': request.form.get('notes', ''),
            'total_price': total_price
        })
        return redirect(url_for('payment', booking_id=booking_id))

    with db_connection() as conn:
        pricing_options = conn.execute(
            'SELECT * FROM service_pricing WHERE service_id = ?',
            (service_id,)
        ).fetchall()
        pricing_options = [dict(row) for row in pricing_options]

    # Ensure there's at least one pricing option
    if not pricing_options:
        # Create a default pricing option if none exists
        with db_connection() as conn:
            cursor = conn.execute('''
                INSERT INTO service_pricing (service_id, rule_type, label, price)
                VALUES (?, 'flat_rate', 'Standard Service', ?)
            ''', (service_id, service['base_price']))
            conn.commit()
            pricing_options = [{'id': cursor.lastrowid, 'rule_type': 'flat_rate', 'label': 'Standard Service', 'price': service['base_price']}]

    hourly_pricing_id = None
    base_pricing_id = pricing_options[0]['id']  # Set default base_pricing_id
    flat_tiers = []
    flat_rate = []
    bedroom_price = None
    bathroom_price = None
    hourly_price = None
    custom_label = None

    for option in pricing_options:
        if option["rule_type"] == "per_room":
            if "Bedroom" in option["label"]:
                bedroom_price = option["price"]
            elif "Bathroom" in option["label"]:
                bathroom_price = option["price"]
        elif option["rule_type"] == "flat_tier":
            flat_tiers.append(option)
        elif option["rule_type"] == "flat_rate":
            flat_rate.append(option)
        elif option["rule_type"] == "hourly":
            hourly_price = option["price"]
            hourly_pricing_id = option["id"]
        elif option["rule_type"] == "custom":
            custom_label = option["label"]

    return render_template(
        "book.html",
        service=service,
        pricing_options=pricing_options,
        bedroom_price=bedroom_price,
        bathroom_price=bathroom_price,
        flat_tiers=flat_tiers,
        flat_rate=flat_rate,
        hourly_price=hourly_price,
        hourly_pricing_id=hourly_pricing_id,
        custom_label=custom_label,
        base_pricing_id=base_pricing_id
    )
    
#Payment route: handle payment and redirect to confirmation
@app.route('/payment/<int:booking_id>', methods=['GET', 'POST'])
def payment(booking_id):
    booking = get_booking(booking_id)
    if not booking:
        return "Booking not found", 404

    with db_connection() as conn:
        payment = conn.execute(
            'SELECT * FROM payments WHERE booking_id = ?', (booking_id,)
        ).fetchone()

    # Phase 2: When user agrees
    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        return redirect(url_for('confirmation', booking_id=booking_id))

    # Phase 1: Initial payment submission
    if request.method == 'POST':
        street_address = request.form.get('street_address', '').strip()
        city = request.form.get('city', '').strip()
        province = request.form.get('province', '').strip()
        region = request.form.get('region', '').strip()
        payment_method = request.form.get('payment_method')

        # Validation
        if not (street_address and city and province and region):
            flash('Please fill in all address fields.', 'error')
            return render_template('payment.html', booking=booking, payment=payment)

        if not payment_method:
            flash('Please select a payment method.', 'error')
            return render_template('payment.html', booking=booking, payment=payment)

        # Store the payment temporarily
        with db_connection() as conn:
            if payment:
                conn.execute('''
                    UPDATE payments
                    SET street_address = ?, city = ?, province = ?, region = ?, payment_method = ?, amount = ?
                    WHERE booking_id = ?
                ''', (street_address, city, province, region, payment_method, booking['total_price'], booking_id))
            else:
                conn.execute('''
                    INSERT INTO payments
                    (booking_id, street_address, city, province, region, payment_method, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (booking_id, street_address, city, province, region, payment_method, booking['total_price']))
            conn.commit()

        # Payment instructions for modal
        amount = booking['total_price']
        if payment_method == 'Cash':
            instruction = f'Please ready your cash (₱{amount}) when the crew arrives.'
        elif payment_method == 'Card':
            instruction = 'Please wait, you will be redirected to our secure card payment gateway.'
        elif payment_method == 'GCASH':
            instruction = f'Please send ₱{amount} to GCASH Number: 09457996892.'
        else:
            instruction = 'Invalid payment method.'

        # Re-render page with modal trigger
        return render_template('payment.html', booking=booking, payment=payment, show_modal=True, instruction=instruction)

    return render_template('payment.html', booking=booking, payment=payment)

#Confirmation page after successful booking
@app.route('/confirmation/<int:booking_id>')
def confirmation(booking_id):
    booking = get_booking(booking_id)
    if not booking:
        return "Booking not found", 404
    payment = get_payment(booking_id)
    return render_template('confirmation.html', booking=booking, payment=payment)


#________________________________________________________________________________________________________________________
#ADMIN PAGE

#ADMIN AUTHENTICATION
AUTH_USERNAME = 'admin'
AUTH_PASSWORD = 'secret'


@app.template_filter('currency')
def currency_format(value):
    """Format a float value as currency without decimal places and with commas."""
    return f"₱{value:,.0f}"


@app.route('/admin/dashboard')
@requires_auth
def admin_dashboard():
    with db_connection() as conn:
        # Total bookings count
        total_bookings = conn.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]

        # Pending bookings count
        pending_bookings = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE payment_status = 'pending'"
        ).fetchone()[0]

        # Total revenue from paid payments
        total_revenue_row = conn.execute(
            "SELECT SUM(amount) FROM payments WHERE payment_status = 'paid'"
        ).fetchone()
        total_revenue = total_revenue_row[0] if total_revenue_row[0] is not None else 0.0

        # Active customers (unique customers with bookings in the last 30 days)
        active_customers = conn.execute('''
            SELECT COUNT(DISTINCT customer_email) 
            FROM bookings 
            WHERE date >= date('now', '-30 days')
        ''').fetchone()[0]

        # Recent bookings (last 5) with customer name, service name, date and payment status
        recent_bookings = conn.execute('''
            SELECT 
                b.id, 
                b.customer_name, 
                b.date, 
                b.total_price,
                s.name as service_name,
                COALESCE(p.payment_status, 'pending') as status
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            LEFT JOIN payments p ON b.id = p.booking_id
            ORDER BY b.created_at DESC
            LIMIT 5
        ''').fetchall()

        # Popular services (services with most bookings in last 30 days)
        popular_services = conn.execute('''
            SELECT 
                s.name,
                COUNT(*) as bookings,
                COUNT(*) * 100.0 / (
                    SELECT COUNT(*) FROM bookings 
                    WHERE date >= date('now', '-30 days')
                ) as percentage
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            WHERE b.date >= date('now', '-30 days')
            GROUP BY s.id, s.name
            ORDER BY bookings DESC
            LIMIT 5
        ''').fetchall()

    recent_backups = get_recent_backups()

    return render_template(
        'admin_dashboard.html',
        total_bookings=total_bookings,
        pending_bookings=pending_bookings,
        total_revenue=total_revenue,
        active_customers=active_customers,
        recent_bookings=recent_bookings,
        popular_services=popular_services,
        recent_backups=recent_backups
    )

@app.route('/admin/bookings')
@requires_auth
def show_bookings():
    with db_connection() as conn:
        # Fetch all bookings with associated service name and pricing label
        bookings = conn.execute('''
            SELECT b.*, s.name AS service_name, sp.label AS pricing_label, sp.rule_type
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            LEFT JOIN service_pricing sp ON b.pricing_id = sp.id
            ORDER BY b.created_at DESC
        ''').fetchall()

        # Fetch booking options
        options_rows = conn.execute('''
            SELECT bo.booking_id, sp.label, sp.price, bo.quantity
            FROM booking_options bo
            JOIN service_pricing sp ON bo.pricing_id = sp.id
        ''').fetchall()

        # Fetch payments (including payment_method)
        payments = conn.execute('SELECT * FROM payments').fetchall()

    # Map payments by booking ID
    payments_map = {p['booking_id']: p for p in payments}

    # Group options by booking_id
    options_map = {}
    for row in options_rows:
        options_map.setdefault(row['booking_id'], []).append({
            'label': row['label'],
            'price': row['price'],
            'quantity': row['quantity']
        })

    # Construct final booking list
    booking_list = []
    for b in bookings:
        created_at_dt = datetime.strptime(b['created_at'], '%Y-%m-%d %H:%M:%S')
        opts = options_map.get(b['id'], [])

        if b['bedroom_qty'] > 0:
            opts.append({'label': 'Bedrooms', 'price': 0.0, 'quantity': b['bedroom_qty']})
        if b['bath_qty'] > 0:
            opts.append({'label': 'Bathrooms', 'price': 0.0, 'quantity': b['bath_qty']})

        payment = payments_map.get(b['id'])

        booking_list.append({
            **b,
            'options': opts,
            'payment': payment,
            'payment_method': payment['payment_method'] if payment else 'Not provided',
            'created_at_dt': created_at_dt
        })

    return render_template('bookings_list.html', bookings=booking_list)

@app.route('/admin/booking/<int:booking_id>', methods=['GET'])
@requires_auth
def get_booking_details(booking_id):
    with db_connection() as conn:
        # Fetch booking with all related information
        booking = conn.execute('''
            SELECT 
                b.*,
                s.name as service_name,
                p.street_address,
                p.city,
                p.province,
                p.region,
                p.payment_method,
                p.payment_status,
                p.amount
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            LEFT JOIN payments p ON b.id = p.booking_id
            WHERE b.id = ?
        ''', (booking_id,)).fetchone()
        
        if not booking:
            return {'error': 'Booking not found'}, 404

        # Fetch booking options
        options = conn.execute('''
            SELECT sp.label, sp.price, bo.quantity
            FROM booking_options bo
            JOIN service_pricing sp ON bo.pricing_id = sp.id
            WHERE bo.booking_id = ?
        ''', (booking_id,)).fetchall()

    return {
        'booking': dict(booking),
        'options': [dict(opt) for opt in options]
    }

@app.route('/admin/booking/<int:booking_id>', methods=['PUT'])
@requires_auth
def update_booking(booking_id):
    data = request.get_json()
    
    with db_connection() as conn:
        # Update booking details
        conn.execute('''
            UPDATE bookings 
            SET 
                customer_name = ?,
                customer_email = ?,
                customer_phone = ?,
                date = ?,
                notes = ?
            WHERE id = ?
        ''', (
            data['customer_name'],
            data['customer_email'],
            data['customer_phone'],
            data['date'],
            data.get('notes', ''),
            booking_id
        ))

        # Update payment if it exists
        if 'payment' in data:
            conn.execute('''
                UPDATE payments
                SET 
                    street_address = ?,
                    city = ?,
                    province = ?,
                    region = ?,
                    payment_method = ?,
                    payment_status = ?
                WHERE booking_id = ?
            ''', (
                data['payment']['street_address'],
                data['payment']['city'],
                data['payment']['province'],
                data['payment']['region'],
                data['payment']['payment_method'],
                data['payment']['payment_status'],
                booking_id
            ))

        conn.commit()

    return {'message': 'Booking updated successfully'}

@app.route('/admin/booking/<int:booking_id>', methods=['DELETE'])
@requires_auth
def delete_booking(booking_id):
    with db_connection() as conn:
        # Delete related records first
        conn.execute('DELETE FROM payments WHERE booking_id = ?', (booking_id,))
        conn.execute('DELETE FROM booking_options WHERE booking_id = ?', (booking_id,))
        # Delete the booking
        conn.execute('DELETE FROM bookings WHERE id = ?', (booking_id,))
        conn.commit()

    return {'message': 'Booking deleted successfully'}

@app.route('/admin/update_payment_status', methods=['POST'])
@requires_auth
def update_payment_status():
    booking_id = request.form['update_id']
    new_status = request.form.get(f'payment_status_{booking_id}')

    with db_connection() as conn:
        conn.execute(
            'UPDATE payments SET payment_status = ? WHERE booking_id = ?',
            (new_status, booking_id)
        )
        conn.commit()

    return redirect(url_for('show_bookings'))

#Admin backup route
@app.route('/admin/backup_bookings')
@requires_auth
def backup_bookings():
    filename = backup_to_json()
    return f"Bookings backed up to {filename}"

@app.route('/admin/services/add', methods=['POST'])
@requires_auth
def add_service():
    try:
        name = request.form.get('name')
        description = request.form.get('description')
        price = float(request.form.get('price'))
        image_url = request.form.get('image_url')

        with db_connection() as conn:
            conn.execute('''
                INSERT INTO services (name, description, base_price, image_url)
                VALUES (?, ?, ?, ?)
            ''', (name, description, price, image_url))
            
        return jsonify({'message': 'Service added successfully'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def backup_database():
    """Create a backup of the SQLite database"""
    try:
        # Get the paths
        db_path = os.path.join(os.path.dirname(__file__), 'cleaning.db')
        backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
        
        # Initialize database if it doesn't exist
        if not os.path.exists(db_path):
            init_db()
            load_services_and_pricing()
        
        # Create backups directory if it doesn't exist
        if not os.path.exists(backup_dir):
            try:
                os.makedirs(backup_dir)
            except Exception as e:
                raise Exception(f"Failed to create backup directory: {str(e)}")
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = os.path.join(backup_dir, f'database_backup_{timestamp}.db')
        
        # Create backup using SQLite's backup API for atomic backup
        with sqlite3.connect(db_path) as source:
            with sqlite3.connect(backup_path) as target:
                source.backup(target)
        
        return backup_path
    except Exception as e:
        raise Exception(f"Backup failed: {str(e)}")

@app.route('/admin/backup-database', methods=['POST'])
@requires_auth
def handle_backup_database():
    try:
        backup_path = backup_database()
        return jsonify({
            'message': 'Database backup created successfully',
            'backup_path': backup_path
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_recent_backups():
    """Get list of recent database backups"""
    backup_dir = os.path.join(os.path.dirname(__file__), 'backups')
    if not os.path.exists(backup_dir):
        return []
        
    backups = []
    for file in os.listdir(backup_dir):
        if file.startswith('database_backup_') and file.endswith('.db'):
            try:
                path = os.path.join(backup_dir, file)
                # Extract timestamp from filename (remove 'database_backup_' prefix and '.db' suffix)
                timestamp_str = file[16:-3]  # Changed from 15 to 16 to match the correct prefix length
                timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')
                size = os.path.getsize(path) / (1024 * 1024)  # Convert to MB
                backups.append({
                    'filename': file,
                    'timestamp': timestamp,
                    'size': round(size, 2)
                })
            except (ValueError, OSError) as e:
                print(f"Error processing backup file {file}: {str(e)}")
                continue
    
    # Sort by timestamp, most recent first
    backups.sort(key=lambda x: x['timestamp'], reverse=True)
    return backups[:5]  # Return only the 5 most recent backups

@app.route('/admin/bookings/bulk-update', methods=['POST'])
@requires_auth
def bulk_update_bookings():
    try:
        data = request.get_json()
        booking_ids = data.get('booking_ids', [])
        action = data.get('action')

        if not booking_ids or not action:
            return jsonify({'error': 'Missing booking IDs or action'}), 400

        with db_connection() as conn:
            if action == 'mark_paid':
                conn.executemany(
                    'UPDATE payments SET payment_status = ? WHERE booking_id = ?',
                    [('paid', id) for id in booking_ids]
                )
            elif action == 'cancel':
                conn.executemany(
                    'UPDATE payments SET payment_status = ? WHERE booking_id = ?',
                    [('cancelled', id) for id in booking_ids]
                )
            elif action == 'delete':
                # Delete related records first
                conn.executemany('DELETE FROM payments WHERE booking_id = ?',
                               [(id,) for id in booking_ids])
                conn.executemany('DELETE FROM booking_options WHERE booking_id = ?',
                               [(id,) for id in booking_ids])
                conn.executemany('DELETE FROM bookings WHERE id = ?',
                               [(id,) for id in booking_ids])
            
            conn.commit()

        return jsonify({'message': f'Successfully {action}ed selected bookings'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
# To run the app, use the command: python app.py
