import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from services import get_all_services, get_service
from bookings import create_booking, get_booking
from database import init_db, db_connection
from collections import defaultdict
from functools import wraps

app = Flask(__name__)

# Initialize database
init_db()

app.secret_key = os.urandom(24)

# Load services and pricing rules from JSON files into the database (if empty)
def load_services_and_pricing():
    with open('services.txt') as f:
        services = json.load(f)

    with open('service_pricing.txt') as f:
        pricing_rules = json.load(f)

    with db_connection() as conn:
        count = conn.execute('SELECT COUNT(*) FROM services').fetchone()[0]
        if count == 0:
            for s in services:
                conn.execute(
                    'INSERT INTO services (id, name, base_price, description) VALUES (?, ?, ?, ?)',
                    (s['id'], s['name'], s['base_price'], s['description'])
                )
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
            pricing_id_str = request.form.get("pricing_id")
            if pricing_id_str is None or pricing_id_str == '':
                pricing_id = None
            else:
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

    hourly_pricing_id = None
    base_pricing_id = None
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
            hourly_pricing_id = option["id"]  # capture this
            if base_pricing_id is None:
                base_pricing_id = option["id"]
        elif option["rule_type"] == "custom":
            custom_label = option["label"]

        # Set base_pricing_id if not set and current option has an id
        if base_pricing_id is None:
            base_pricing_id = option["id"]

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
            instruction = f'Please send ₱{amount} to GCASH Number: 09XXXXXXXXX.'
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
    """Format a float value as currency with 2 decimal places and commas."""
    return f"₱{value:,.2f}"


@app.route('/admin/dashboard')
@requires_auth
def admin_dashboard():
    with db_connection() as conn:
        # Total bookings count
        total_bookings = conn.execute('SELECT COUNT(*) FROM bookings').fetchone()[0]

        # Total services count
        total_services = conn.execute('SELECT COUNT(*) FROM services').fetchone()[0]

        # Total revenue from paid payments
        total_revenue_row = conn.execute(
            "SELECT SUM(amount) FROM payments WHERE payment_status = 'paid'"
        ).fetchone()
        total_revenue = total_revenue_row[0] if total_revenue_row[0] is not None else 0.0

        # New bookings today
        new_bookings_today = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE DATE(created_at) = DATE('now', 'localtime')"
        ).fetchone()[0]

        # Recent bookings (last 5) with customer name, service name, and date
        recent_bookings = conn.execute('''
            SELECT b.id, b.customer_name, b.date, s.name as service_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            ORDER BY b.created_at DESC
            LIMIT 5
        ''').fetchall()

    return render_template(
        'admin_dashboard.html',
        total_bookings=total_bookings,
        total_services=total_services,
        total_revenue=total_revenue,
        new_bookings_today=new_bookings_today,
        recent_bookings=recent_bookings
    )

@app.route('/admin/bookings')
@requires_auth
def show_bookings():
    with db_connection() as conn:
        # Fetch all bookings with associated service name
        bookings = conn.execute('''
            SELECT b.*, s.name AS service_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
# To run the app, use the command: python app.py
