from database import db_connection
from datetime import datetime

def create_booking(service_id, pricing_id, customer_info):
    """
    Create a new booking with detailed info and calculated total price.

    Args:
        service_id (int): ID of the selected service
        pricing_id (int): ID of the selected pricing rule
        customer_info (dict): Contains keys:
            - name (str)
            - email (str)
            - phone (str)
            - date (str)
            - address (str)
            - bedroom_qty (int), default 1
            - bath_qty (int), default 1
            - hours (int), default 0
            - notes (str), optional
            - total_price (float)

    Returns:
        int: ID of the newly created booking
    """
    with db_connection() as conn:
        cursor = conn.execute('''
            INSERT INTO bookings
            (service_id, pricing_id, customer_name, customer_email, customer_phone, date, bedroom_qty, bath_qty, hours, notes, total_price, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            service_id,
            pricing_id,
            customer_info['name'],
            customer_info['email'],
            customer_info['phone'],
            customer_info['date'],
            customer_info.get('bedroom_qty', 1),
            customer_info.get('bath_qty', 1),
            customer_info.get('hours', 0),
            customer_info.get('notes', ''),
            customer_info.get('total_price', 0.0),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))

        conn.commit()
        return cursor.lastrowid


def get_booking(booking_id):
    """
    Retrieve a booking by its ID including service name and pricing details.

    Args:
        booking_id (int): The booking ID to retrieve.

    Returns:
        dict or None: Booking details or None if not found.
    """
    with db_connection() as conn:
        booking = conn.execute('''
            SELECT b.*, s.name AS service_name, sp.label AS pricing_label, sp.price AS pricing_price,
                   sp.rule_type, sp.id AS original_pricing_id
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN service_pricing sp ON b.pricing_id = sp.id
            WHERE b.id = ?
        ''', (booking_id,)).fetchone()

        if booking is None:
            return None

        # Convert to dict and handle custom pricing ID
        booking_dict = dict(booking)
        if booking_dict['rule_type'] == 'custom':
            booking_dict['pricing_id'] = f"{booking_dict['original_pricing_id']}_custom"
        
        return booking_dict
