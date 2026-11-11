"""
Reporting queries written as explicit SQL (shared by the Reports page and the DBMS Lab).

Revenue definitions used everywhere in the project:
  * booked value      = SUM(bookings.total_amount) of non-cancelled bookings
  * revenue collected = SUM(payments.amount) WHERE payment_status = 'paid'
  * pending           = SUM(payments.amount) WHERE payment_status = 'pending' (cash due at venue)
  * refunded          = SUM(payments.amount) WHERE payment_status = 'refunded' (NOT revenue)
"""
from django.db import connection

REPORTS = {
    "facility_revenue": {
        "title": "Revenue by facility",
        "sql": """SELECT facility_name, city, courts, active_bookings, cancelled_bookings,
       revenue_collected, revenue_pending, amount_refunded, avg_rating
FROM v_facility_revenue
ORDER BY revenue_collected DESC""",
    },
    "sport_popularity": {
        "title": "Sport popularity and revenue",
        "sql": """SELECT s.name AS sport,
       COUNT(b.booking_id) FILTER (WHERE b.status <> 'cancelled') AS bookings,
       COALESCE(SUM(EXTRACT(EPOCH FROM b.end_time - b.start_time) / 3600)
                FILTER (WHERE b.status <> 'cancelled'), 0)::numeric(10,1) AS hours_booked,
       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'paid'), 0) AS revenue_collected
FROM sports s
LEFT JOIN courts   c ON c.sport_id   = s.sport_id
LEFT JOIN bookings b ON b.court_id   = c.court_id
LEFT JOIN payments p ON p.booking_id = b.booking_id
GROUP BY s.sport_id, s.name
ORDER BY bookings DESC, sport""",
    },
    "court_utilization": {
        "title": "Court utilisation (last 30 days, 17 bookable hours per day)",
        "sql": """SELECT f.name AS facility, c.court_name, c.is_active,
       COALESCE(SUM(EXTRACT(EPOCH FROM b.end_time - b.start_time) / 3600), 0)::numeric(10,1) AS hours_booked,
       ROUND(100 * COALESCE(SUM(EXTRACT(EPOCH FROM b.end_time - b.start_time) / 3600), 0) / (30 * 17), 1)
           AS utilisation_pct
FROM courts c
JOIN facilities f ON f.facility_id = c.facility_id
LEFT JOIN bookings b
       ON b.court_id = c.court_id
      AND b.status IN ('confirmed', 'completed')
      AND b.start_time >= now() - interval '30 days'
      AND b.start_time <  now()
GROUP BY f.name, c.court_id, c.court_name, c.is_active
ORDER BY utilisation_pct DESC, facility, c.court_name""",
    },
    "ratings": {
        "title": "Average rating per court",
        "sql": """SELECT f.name AS facility, c.court_name, COUNT(r.booking_id) AS reviews,
       ROUND(AVG(r.rating), 2) AS avg_rating, MIN(r.rating) AS worst, MAX(r.rating) AS best
FROM reviews r
JOIN bookings   b ON b.booking_id  = r.booking_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN facilities f ON f.facility_id = c.facility_id
GROUP BY f.name, c.court_id, c.court_name
ORDER BY avg_rating DESC, reviews DESC""",
    },
    "upcoming_maintenance": {
        "title": "Upcoming maintenance",
        "sql": """SELECT f.name AS facility, c.court_name, m.start_time, m.end_time, m.reason
FROM maintenance m
JOIN courts     c ON c.court_id    = m.court_id
JOIN facilities f ON f.facility_id = c.facility_id
WHERE m.end_time > now()
ORDER BY m.start_time""",
    },
    "monthly_revenue": {
        "title": "Collected revenue per month",
        "sql": """SELECT to_char(date_trunc('month', p.paid_at), 'YYYY-MM') AS month,
       COUNT(*) AS payments, SUM(p.amount) AS revenue_collected
FROM payments p
WHERE p.payment_status = 'paid'
GROUP BY date_trunc('month', p.paid_at)
ORDER BY month""",
    },
}


def run_report(key):
    report = REPORTS[key]
    with connection.cursor() as cur:
        cur.execute(report["sql"])
        columns = [c.name for c in cur.description]
        rows = cur.fetchall()
    return {"key": key, "title": report["title"], "sql": report["sql"], "columns": columns, "rows": rows}


def dashboard_stats():
    with connection.cursor() as cur:
        cur.execute("""
            SELECT (SELECT COUNT(*) FROM facilities),
                   (SELECT COUNT(*) FROM courts WHERE is_active),
                   (SELECT COUNT(*) FROM bookings WHERE status <> 'cancelled' AND start_time > now()),
                   (SELECT COALESCE(SUM(amount), 0) FROM payments WHERE payment_status = 'paid'),
                   (SELECT COUNT(*) FROM users WHERE role = 'customer'),
                   (SELECT ROUND(AVG(rating), 2) FROM reviews)
        """)
        row = cur.fetchone()
    keys = ["facilities", "active_courts", "upcoming_bookings", "revenue", "customers", "avg_rating"]
    return dict(zip(keys, row))
