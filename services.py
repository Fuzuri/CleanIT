from database import db_connection

def get_all_services():
    with db_connection() as conn:
        # Fetch all services
        services_cursor = conn.execute('SELECT * FROM services')
        services = [dict(row) for row in services_cursor.fetchall()]

        # Fetch all pricing rules
        pricing_cursor = conn.execute('SELECT * FROM service_pricing')
        pricing = [dict(row) for row in pricing_cursor.fetchall()]

        # Group pricing rules under each service
        service_map = {s['id']: s for s in services}
        for service in service_map.values():
            service['pricing'] = []

        for p in pricing:
            service_map[p['service_id']]['pricing'].append(p)

        return list(service_map.values())

def get_service(service_id):
    with db_connection() as conn:
        # Fetch the main service
        service_cursor = conn.execute('SELECT * FROM services WHERE id = ?', (service_id,))
        service = service_cursor.fetchone()

        if service is None:
            return None

        service_dict = dict(service)

        # Fetch pricing rules for that service
        pricing_cursor = conn.execute('SELECT * FROM service_pricing WHERE service_id = ?', (service_id,))
        pricing = [dict(row) for row in pricing_cursor.fetchall()]

        service_dict['pricing'] = pricing
        return service_dict


