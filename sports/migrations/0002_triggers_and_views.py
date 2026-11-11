"""
Database-level objects that Django models cannot express directly.

1. Cross-table invariant: a non-cancelled booking may not overlap a maintenance
   window of the same court (and vice-versa). CHECK and EXCLUDE constraints only
   see one table, so this is enforced by two BEFORE triggers. Each trigger first
   locks the parent court row (SELECT ... FOR UPDATE) so that two concurrent
   transactions touching the same court's schedule are serialised and cannot
   both pass the check.

2. Two reporting views used by the reports page and the DBMS Lab.
"""
from django.db import migrations

TRIGGERS_SQL = r"""
CREATE OR REPLACE FUNCTION fn_booking_not_during_maintenance() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status = 'cancelled' THEN
        RETURN NEW;
    END IF;
    -- Serialise schedule changes for this court.
    PERFORM 1 FROM courts WHERE court_id = NEW.court_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM maintenance m
        WHERE m.court_id = NEW.court_id
          AND tstzrange(m.start_time, m.end_time, '[)')
              && tstzrange(NEW.start_time, NEW.end_time, '[)')
    ) THEN
        RAISE EXCEPTION 'Court % is under maintenance during the requested time', NEW.court_id
            USING ERRCODE = 'exclusion_violation',
                  CONSTRAINT = 'bookings_not_during_maintenance';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_bookings_not_during_maintenance
    BEFORE INSERT OR UPDATE OF court_id, start_time, end_time, status ON bookings
    FOR EACH ROW EXECUTE FUNCTION fn_booking_not_during_maintenance();

CREATE OR REPLACE FUNCTION fn_maintenance_not_during_booking() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM courts WHERE court_id = NEW.court_id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM bookings b
        WHERE b.court_id = NEW.court_id
          AND b.status <> 'cancelled'
          AND tstzrange(b.start_time, b.end_time, '[)')
              && tstzrange(NEW.start_time, NEW.end_time, '[)')
    ) THEN
        RAISE EXCEPTION 'Court % has active bookings during this maintenance window', NEW.court_id
            USING ERRCODE = 'exclusion_violation',
                  CONSTRAINT = 'maintenance_not_during_booking';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_maintenance_not_during_booking
    BEFORE INSERT OR UPDATE OF court_id, start_time, end_time ON maintenance
    FOR EACH ROW EXECUTE FUNCTION fn_maintenance_not_during_booking();
"""

DROP_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS trg_maintenance_not_during_booking ON maintenance;
DROP FUNCTION IF EXISTS fn_maintenance_not_during_booking();
DROP TRIGGER IF EXISTS trg_bookings_not_during_maintenance ON bookings;
DROP FUNCTION IF EXISTS fn_booking_not_during_maintenance();
"""

VIEWS_SQL = """
-- One row per booking, de-normalised for reading (the base tables stay normalised).
CREATE VIEW v_booking_details AS
SELECT b.booking_id,
       b.user_id,
       u.name                AS user_name,
       f.facility_id,
       f.name                AS facility_name,
       f.city,
       c.court_id,
       c.court_name,
       s.sport_id,
       s.name                AS sport_name,
       b.start_time,
       b.end_time,
       ROUND(EXTRACT(EPOCH FROM (b.end_time - b.start_time)) / 3600, 2) AS hours,
       b.total_amount,
       b.status              AS booking_status,
       p.payment_method,
       p.payment_status,
       p.amount              AS payment_amount,
       p.paid_at,
       r.rating
FROM bookings b
JOIN users       u ON u.user_id     = b.user_id
JOIN courts      c ON c.court_id    = b.court_id
JOIN facilities  f ON f.facility_id = c.facility_id
JOIN sports      s ON s.sport_id    = c.sport_id
LEFT JOIN payments p ON p.booking_id = b.booking_id
LEFT JOIN reviews  r ON r.booking_id = b.booking_id;

-- Revenue per facility. Revenue = payments actually collected (status 'paid').
-- Refunded money is reported separately and NOT counted as revenue.
CREATE VIEW v_facility_revenue AS
SELECT f.facility_id,
       f.name AS facility_name,
       f.city,
       COUNT(DISTINCT c.court_id)                                                   AS courts,
       COUNT(b.booking_id) FILTER (WHERE b.status <> 'cancelled')                    AS active_bookings,
       COUNT(b.booking_id) FILTER (WHERE b.status = 'cancelled')                     AS cancelled_bookings,
       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'paid'), 0)           AS revenue_collected,
       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'pending'), 0)        AS revenue_pending,
       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'refunded'), 0)       AS amount_refunded,
       ROUND(AVG(r.rating), 2)                                                       AS avg_rating
FROM facilities f
LEFT JOIN courts   c ON c.facility_id = f.facility_id
LEFT JOIN bookings b ON b.court_id    = c.court_id
LEFT JOIN payments p ON p.booking_id  = b.booking_id
LEFT JOIN reviews  r ON r.booking_id  = b.booking_id
GROUP BY f.facility_id, f.name, f.city;
"""

DROP_VIEWS_SQL = """
DROP VIEW IF EXISTS v_facility_revenue;
DROP VIEW IF EXISTS v_booking_details;
"""


class Migration(migrations.Migration):
    dependencies = [("sports", "0001_initial")]

    operations = [
        migrations.RunSQL(TRIGGERS_SQL, DROP_TRIGGERS_SQL),
        migrations.RunSQL(VIEWS_SQL, DROP_VIEWS_SQL),
    ]
