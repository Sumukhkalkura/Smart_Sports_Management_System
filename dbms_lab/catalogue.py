"""
Curated SQL catalogue for the DBMS Lab.

kind = "select"   -> executed live through the SELECT-only role (read-only transaction)
kind = "sandbox"  -> fixed write statements run in one transaction that is always ROLLED BACK
kind = "compare"  -> the same SELECT is EXPLAIN ANALYZEd twice: planner free vs. index scans disabled

Every query targets the real schema and returns real rows from the seeded data.
"""
from sports.reports import REPORTS

CATEGORIES = [
    ("A", "Basic SQL"),
    ("B", "Relational operations (joins)"),
    ("C", "Aggregation"),
    ("D", "Advanced queries"),
    ("E", "Design & integrity"),
    ("F", "Transactions & concurrency"),
    ("G", "Performance & query plans"),
    ("H", "Reports"),
]

Q = []


def q(**item):
    item.setdefault("kind", "select")
    item.setdefault("tables", [])
    item.setdefault("joins", "")
    item.setdefault("filters", "")
    item.setdefault("columns", {})
    item.setdefault("tuple", "")
    item.setdefault("notes", "")
    Q.append(item)


# =============================================================== A. BASIC SQL
q(slug="select-all-facilities", category="A", title="SELECT: list every facility",
  concept="Projection (choosing columns) over a single relation",
  objective="Retrieve the attributes of every tuple in the facilities relation.",
  sql="""SELECT facility_id, name, city, phone, address
FROM facilities
ORDER BY facility_id;""",
  tables=["facilities"],
  columns={"facility_id": "primary key (bigint identity)", "name": "facility name",
           "city": "city", "phone": "contact number", "address": "street address"},
  tuple="One tuple = one sports facility (one row of the facilities table).")

q(slug="where-filter", category="A", title="WHERE: active courts cheaper than ₹500/hour",
  concept="Selection (σ): keep only tuples that satisfy a predicate",
  objective="Show which courts a budget-conscious player could book.",
  sql="""SELECT court_id, court_name, hourly_rate
FROM courts
WHERE is_active = TRUE
  AND hourly_rate < 500
ORDER BY hourly_rate, court_name;""",
  tables=["courts"], filters="is_active = TRUE AND hourly_rate < 500",
  columns={"court_id": "PK of the court", "court_name": "name within its facility",
           "hourly_rate": "numeric(8,2) price per hour"},
  tuple="One tuple = one court that satisfies both conditions.")

q(slug="order-limit", category="A", title="ORDER BY + LIMIT: five most expensive courts",
  concept="Sorting and limiting a result set",
  objective="Find the premium courts.",
  sql="""SELECT court_name, hourly_rate
FROM courts
ORDER BY hourly_rate DESC, court_name
LIMIT 5;""",
  tables=["courts"],
  columns={"court_name": "court", "hourly_rate": "price per hour, highest first"},
  tuple="One tuple = one court; only the first 5 after sorting are returned.",
  notes="Without ORDER BY, a relation has no guaranteed order, so LIMIT alone would be arbitrary.")

q(slug="distinct-cities", category="A", title="DISTINCT: cities with a facility",
  concept="Duplicate elimination",
  objective="List each city once, even when it has several facilities.",
  sql="""SELECT DISTINCT city
FROM facilities
ORDER BY city;""",
  tables=["facilities"], columns={"city": "a city name, each appearing once"},
  tuple="One tuple = one distinct city value.",
  notes="Bengaluru has two facilities but appears once. In relational algebra, projection removes "
        "duplicates automatically; in SQL you must ask for it with DISTINCT.")

q(slug="insert-returning", category="A", kind="sandbox", title="INSERT … RETURNING (rolled back)",
  concept="Inserting a tuple; identity columns generate the primary key",
  objective="Insert a new sport and see the generated sport_id.",
  steps=[
      {"sql": "INSERT INTO sports (name) VALUES ('Pickleball') RETURNING sport_id, name;",
       "note": "sport_id was not supplied, so the IDENTITY column generated it."},
      {"sql": "SELECT sport_id, name FROM sports ORDER BY sport_id;",
       "note": "Inside the transaction the new tuple is visible."},
  ],
  verify_sql="SELECT COUNT(*) AS pickleball_rows_after_rollback FROM sports WHERE name = 'Pickleball'",
  tables=["sports"],
  tuple="RETURNING gives back the inserted tuple, including generated values.",
  notes="After ROLLBACK the row is gone, but the identity sequence value is NOT reused: "
        "sequences are non-transactional, which is why IDs can have gaps.")

q(slug="update-returning", category="A", kind="sandbox", title="UPDATE: 10% price rise at one facility (rolled back)",
  concept="Modifying attribute values of selected tuples",
  objective="Increase the hourly rate of every court at facility 1 by 10%.",
  steps=[
      {"sql": "SELECT court_id, court_name, hourly_rate FROM courts WHERE facility_id = 1 ORDER BY court_id;",
       "note": "Before the update."},
      {"sql": """UPDATE courts
SET hourly_rate = ROUND(hourly_rate * 1.10, 2)
WHERE facility_id = 1
RETURNING court_id, court_name, hourly_rate;""",
       "note": "The command tag shows how many tuples were updated."},
  ],
  verify_sql="SELECT court_id, court_name, hourly_rate FROM courts WHERE facility_id = 1 ORDER BY court_id",
  tables=["courts"], filters="facility_id = 1",
  notes="Existing bookings keep their stored total_amount: it is a snapshot of the price at booking time.")

q(slug="delete-safely", category="A", kind="sandbox", title="DELETE: remove 1-star reviews (rolled back)",
  concept="Deleting tuples that satisfy a predicate",
  objective="Delete low-rated reviews and show which tuples were removed.",
  steps=[
      {"sql": "SELECT COUNT(*) AS reviews_before FROM reviews;"},
      {"sql": "DELETE FROM reviews WHERE rating = 1 RETURNING booking_id, rating, comment;"},
      {"sql": "SELECT COUNT(*) AS reviews_after FROM reviews;"},
  ],
  verify_sql="SELECT COUNT(*) AS reviews_after_rollback FROM reviews",
  tables=["reviews"], filters="rating = 1",
  notes="Shown safely: the whole transaction is rolled back, so nothing is deleted from the live database.")

# ====================================================== B. RELATIONAL OPERATIONS
q(slug="inner-join-courts", category="B", title="INNER JOIN: courts with their facility and sport",
  concept="Natural/equi-join along foreign keys",
  objective="Replace the foreign-key numbers in courts with readable facility and sport names.",
  sql="""SELECT f.name AS facility, c.court_name, s.name AS sport, c.hourly_rate, c.is_active
FROM courts c
JOIN facilities f ON f.facility_id = c.facility_id
JOIN sports     s ON s.sport_id    = c.sport_id
ORDER BY f.name, c.court_name;""",
  tables=["courts", "facilities", "sports"],
  joins="courts.facility_id = facilities.facility_id; courts.sport_id = sports.sport_id",
  columns={"facility": "facilities.name", "court_name": "courts.court_name", "sport": "sports.name",
           "hourly_rate": "courts.hourly_rate", "is_active": "courts.is_active"},
  tuple="One tuple = one court combined with the single facility and single sport it references.",
  notes="Because every court has exactly one facility and one sport (NOT NULL FKs), the join returns "
        "exactly one row per court.")

q(slug="left-join-sports", category="B", title="LEFT JOIN: every sport, even without courts",
  concept="Outer join keeps unmatched tuples from the left relation (NULL-padded)",
  objective="Show all sports and their courts, including sports with no court yet.",
  sql="""SELECT s.sport_id, s.name AS sport, c.court_id, c.court_name
FROM sports s
LEFT JOIN courts c ON c.sport_id = s.sport_id
ORDER BY s.name, c.court_name;""",
  tables=["sports", "courts"], joins="courts.sport_id = sports.sport_id (outer)",
  columns={"sport_id": "PK of sport", "sport": "sport name", "court_id": "NULL if the sport has no court",
           "court_name": "NULL if the sport has no court"},
  tuple="One tuple = one (sport, court) pair, or (sport, NULL) when the sport has no court.",
  notes="Volleyball has no courts: an INNER JOIN would drop it; the LEFT JOIN keeps it with NULLs.")

q(slug="multi-join-upcoming", category="B", title="5-table join: upcoming bookings with payment status",
  concept="Multiple joins + outer join to an optional (weak) entity",
  objective="Build a booking timetable a front-desk employee could use.",
  sql="""SELECT b.booking_id, u.name AS customer, f.name AS facility, c.court_name,
       b.start_time, b.end_time, b.status, p.payment_status
FROM bookings b
JOIN users       u ON u.user_id     = b.user_id
JOIN courts      c ON c.court_id    = b.court_id
JOIN facilities  f ON f.facility_id = c.facility_id
LEFT JOIN payments p ON p.booking_id = b.booking_id
WHERE b.start_time > now()
  AND b.status <> 'cancelled'
ORDER BY b.start_time;""",
  tables=["bookings", "users", "courts", "facilities", "payments"],
  joins="bookings→users (user_id), bookings→courts (court_id), courts→facilities (facility_id), "
        "bookings⟕payments (booking_id)",
  filters="start_time in the future and not cancelled",
  columns={"payment_status": "NULL when no payment row exists yet (participation of BOOKING in settled_by is partial)"},
  tuple="One tuple = one upcoming booking with the customer, place and payment state.")

q(slug="join-filter", category="B", title="Join then filter: badminton bookings in Bengaluru",
  concept="Selection applied to attributes coming from different joined relations",
  objective="Find bookings for a given sport in a given city.",
  sql="""SELECT b.booking_id, u.name AS customer, f.name AS facility, c.court_name, b.start_time, b.status
FROM bookings b
JOIN users      u ON u.user_id     = b.user_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN sports     s ON s.sport_id    = c.sport_id
JOIN facilities f ON f.facility_id = c.facility_id
WHERE s.name = 'Badminton'
  AND f.city = 'Bengaluru'
ORDER BY b.start_time DESC;""",
  tables=["bookings", "users", "courts", "sports", "facilities"],
  filters="sports.name = 'Badminton' AND facilities.city = 'Bengaluru'",
  tuple="One tuple = one booking whose court plays badminton and whose facility is in Bengaluru.")

q(slug="anti-join-no-bookings", category="B", title="LEFT JOIN … IS NULL: users who never booked",
  concept="Anti-join",
  objective="Find registered customers with no booking history.",
  sql="""SELECT u.user_id, u.name, u.email, u.created_at
FROM users u
LEFT JOIN bookings b ON b.user_id = u.user_id
WHERE u.role = 'customer'
  AND b.booking_id IS NULL
ORDER BY u.user_id;""",
  tables=["users", "bookings"], joins="bookings.user_id = users.user_id (outer)",
  filters="no matching booking (b.booking_id IS NULL)",
  tuple="One tuple = one customer with zero bookings.",
  notes="Participation of USER in 'places' is partial: a user may exist without bookings.")

q(slug="self-join-alternatives", category="B", title="Self-join: alternative courts for the same sport",
  concept="Joining a relation with itself using aliases",
  objective="For each court, list other courts in the same facility for the same sport.",
  sql="""SELECT f.name AS facility, a.court_name AS court, b.court_name AS alternative, s.name AS sport
FROM courts a
JOIN courts b     ON b.facility_id = a.facility_id
                 AND b.sport_id    = a.sport_id
                 AND b.court_id   <> a.court_id
JOIN facilities f ON f.facility_id = a.facility_id
JOIN sports     s ON s.sport_id    = a.sport_id
ORDER BY f.name, a.court_name, b.court_name;""",
  tables=["courts (as a)", "courts (as b)", "facilities", "sports"],
  joins="a.facility_id = b.facility_id AND a.sport_id = b.sport_id AND a.court_id <> b.court_id",
  tuple="One tuple = an ordered pair (court, alternative court) of the same facility and sport.")

# ================================================================ C. AGGREGATION
q(slug="count-by-status", category="C", title="COUNT + GROUP BY: bookings per status",
  concept="Grouping tuples and counting each group",
  objective="See how many bookings are pending, confirmed, completed or cancelled.",
  sql="""SELECT status, COUNT(*) AS bookings
FROM bookings
GROUP BY status
ORDER BY bookings DESC;""",
  tables=["bookings"], columns={"status": "group key", "bookings": "number of tuples in the group"},
  tuple="One tuple = one group (one distinct status value).")

q(slug="sum-avg-min-max", category="C", title="SUM / AVG / MIN / MAX per facility",
  concept="Aggregate functions over groups",
  objective="Summarise the booking value of each facility (cancelled bookings excluded).",
  sql="""SELECT f.name AS facility,
       COUNT(b.booking_id)          AS bookings,
       SUM(b.total_amount)          AS booked_value,
       ROUND(AVG(b.total_amount),2) AS avg_booking,
       MIN(b.total_amount)          AS smallest,
       MAX(b.total_amount)          AS largest
FROM facilities f
JOIN courts   c ON c.facility_id = f.facility_id
JOIN bookings b ON b.court_id    = c.court_id
WHERE b.status <> 'cancelled'
GROUP BY f.facility_id, f.name
ORDER BY booked_value DESC;""",
  tables=["facilities", "courts", "bookings"],
  joins="courts.facility_id = facilities.facility_id; bookings.court_id = courts.court_id",
  filters="WHERE removes cancelled bookings BEFORE grouping",
  tuple="One tuple = one facility with aggregates computed over its non-cancelled bookings.",
  notes="booked_value is the price of bookings, not money received; see the revenue report for collected money.")

q(slug="having-frequent", category="C", title="HAVING: customers with more than 5 active bookings",
  concept="Filtering groups (HAVING) vs. filtering rows (WHERE)",
  objective="Identify frequent players.",
  sql="""SELECT u.user_id, u.name, COUNT(*) AS active_bookings, SUM(b.total_amount) AS total_value
FROM users u
JOIN bookings b ON b.user_id = u.user_id
WHERE b.status <> 'cancelled'
GROUP BY u.user_id, u.name
HAVING COUNT(*) > 5
ORDER BY active_bookings DESC;""",
  tables=["users", "bookings"], filters="WHERE status <> 'cancelled'; HAVING COUNT(*) > 5",
  tuple="One tuple = one customer whose group of bookings has more than 5 members.")

q(slug="avg-rating-facility", category="C", title="AVG rating per facility (with review counts)",
  concept="Aggregation across a chain of joins",
  objective="Rank facilities by customer satisfaction.",
  sql="""SELECT f.name AS facility, COUNT(*) AS reviews, ROUND(AVG(r.rating), 2) AS avg_rating
FROM reviews r
JOIN bookings   b ON b.booking_id  = r.booking_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN facilities f ON f.facility_id = c.facility_id
GROUP BY f.facility_id, f.name
HAVING COUNT(*) >= 2
ORDER BY avg_rating DESC;""",
  tables=["reviews", "bookings", "courts", "facilities"],
  joins="reviews→bookings→courts→facilities",
  tuple="One tuple = one facility with at least two reviews.",
  notes="A review has no facility_id column: the facility is reached through the booking and court "
        "(storing it again would be redundant and could become inconsistent).")

# ============================================================ D. ADVANCED QUERIES
q(slug="scalar-subquery", category="D", title="Subquery: courts priced above the overall average",
  concept="Scalar subquery in WHERE",
  objective="Find courts that cost more than the average court.",
  sql="""SELECT court_name, hourly_rate,
       (SELECT ROUND(AVG(hourly_rate), 2) FROM courts) AS overall_avg
FROM courts
WHERE hourly_rate > (SELECT AVG(hourly_rate) FROM courts)
ORDER BY hourly_rate DESC;""",
  tables=["courts"], tuple="One tuple = one court whose rate exceeds the single average value.")

q(slug="correlated-subquery", category="D", title="Correlated subquery: above the average of its own sport",
  concept="A subquery re-evaluated for each outer tuple",
  objective="Find courts that are expensive compared with other courts of the same sport.",
  sql="""SELECT s.name AS sport, c.court_name, c.hourly_rate
FROM courts c
JOIN sports s ON s.sport_id = c.sport_id
WHERE c.hourly_rate > (
        SELECT AVG(c2.hourly_rate)
        FROM courts c2
        WHERE c2.sport_id = c.sport_id   -- correlation with the outer row
      )
ORDER BY s.name, c.hourly_rate DESC;""",
  tables=["courts (outer c)", "courts (inner c2)", "sports"], joins="c2.sport_id = c.sport_id (correlation)",
  tuple="One tuple = a court priced above the average for its sport.")

q(slug="in-subquery", category="D", title="IN subquery: customers who have played tennis",
  concept="Set membership with IN",
  objective="List users with at least one non-cancelled tennis booking.",
  sql="""SELECT user_id, name
FROM users
WHERE user_id IN (
    SELECT b.user_id
    FROM bookings b
    JOIN courts c ON c.court_id = b.court_id
    JOIN sports s ON s.sport_id = c.sport_id
    WHERE s.name = 'Tennis' AND b.status <> 'cancelled'
)
ORDER BY name;""",
  tables=["users", "bookings", "courts", "sports"],
  tuple="One tuple = one user (appearing once even with many tennis bookings).")

q(slug="exists-maintenance", category="D", title="EXISTS: facilities with upcoming maintenance",
  concept="Existential quantification",
  objective="Warn about facilities where some court will be closed for maintenance.",
  sql="""SELECT f.facility_id, f.name, f.city
FROM facilities f
WHERE EXISTS (
    SELECT 1
    FROM courts c
    JOIN maintenance m ON m.court_id = c.court_id
    WHERE c.facility_id = f.facility_id
      AND m.end_time > now()
)
ORDER BY f.name;""",
  tables=["facilities", "courts", "maintenance"], tuple="One tuple = one facility for which the subquery returns ≥ 1 row.")

q(slug="not-exists-unreviewed", category="D", title="NOT EXISTS: completed bookings that were never reviewed",
  concept="Negated existential quantification (anti-join)",
  objective="Find customers to remind about leaving a review.",
  sql="""SELECT b.booking_id, u.name AS customer, b.end_time
FROM bookings b
JOIN users u ON u.user_id = b.user_id
WHERE b.status = 'completed'
  AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.booking_id = b.booking_id)
ORDER BY b.end_time DESC;""",
  tables=["bookings", "users", "reviews"],
  tuple="One tuple = one completed booking with no tuple in reviews.")

q(slug="cte-top-spenders", category="D", title="CTE: top spenders by money actually paid",
  concept="Common Table Expression (WITH) for readable multi-step queries",
  objective="Compute each customer's paid total, then keep customers above the average.",
  sql="""WITH spend AS (
    SELECT b.user_id, SUM(p.amount) AS paid_total, COUNT(*) AS paid_bookings
    FROM bookings b
    JOIN payments p ON p.booking_id = b.booking_id
    WHERE p.payment_status = 'paid'
    GROUP BY b.user_id
)
SELECT u.name, s.paid_total, s.paid_bookings
FROM spend s
JOIN users u ON u.user_id = s.user_id
WHERE s.paid_total > (SELECT AVG(paid_total) FROM spend)
ORDER BY s.paid_total DESC;""",
  tables=["bookings", "payments", "users"],
  tuple="One tuple = one customer whose paid total is above the average customer's.")

q(slug="window-rank", category="D", title="Window function: rank courts by revenue within each facility",
  concept="RANK() OVER (PARTITION BY … ORDER BY …)",
  objective="Find each facility's best-earning court without collapsing rows like GROUP BY would.",
  sql="""WITH court_revenue AS (
    SELECT c.facility_id, c.court_name, COALESCE(SUM(p.amount), 0) AS revenue
    FROM courts c
    LEFT JOIN bookings b ON b.court_id = c.court_id
    LEFT JOIN payments p ON p.booking_id = b.booking_id AND p.payment_status = 'paid'
    GROUP BY c.facility_id, c.court_id, c.court_name
)
SELECT f.name AS facility, cr.court_name, cr.revenue,
       RANK() OVER (PARTITION BY cr.facility_id ORDER BY cr.revenue DESC) AS rank_in_facility,
       ROUND(100.0 * cr.revenue / NULLIF(SUM(cr.revenue) OVER (PARTITION BY cr.facility_id), 0), 1)
           AS pct_of_facility
FROM court_revenue cr
JOIN facilities f ON f.facility_id = cr.facility_id
ORDER BY f.name, rank_in_facility;""",
  tables=["courts", "bookings", "payments", "facilities"],
  tuple="One tuple = one court with its rank and revenue share inside its own facility.")

q(slug="window-running-total", category="D", title="Window function: running total of collected revenue",
  concept="SUM() OVER (ORDER BY …) cumulative aggregate",
  objective="Show daily collected revenue and the running total.",
  sql="""SELECT paid_at::date AS day,
       SUM(amount) AS collected,
       SUM(SUM(amount)) OVER (ORDER BY paid_at::date) AS running_total
FROM payments
WHERE payment_status = 'paid'
GROUP BY paid_at::date
ORDER BY day;""",
  tables=["payments"], tuple="One tuple = one calendar day with money collected that day and in total so far.")

# ========================================================= E. DESIGN & INTEGRITY
q(slug="pk-inspection", category="E", title="Inspect primary keys (incl. composite and weak-entity keys)",
  concept="Primary keys from the system catalogue",
  objective="Show the PK of every application table, read directly from pg_constraint.",
  sql="""SELECT c.relname AS table_name, k.conname AS constraint_name,
       pg_get_constraintdef(k.oid) AS definition,
       array_length(k.conkey, 1) AS key_columns
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
WHERE k.contype = 'p'
  AND c.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY c.relname;""",
  tables=["pg_constraint", "pg_class"],
  tuple="One tuple = the primary-key constraint of one table.",
  notes="payments and reviews use booking_id (the owner's key) as PK; maintenance has a 2-column composite PK.")

q(slug="fk-inspection", category="E", title="Inspect foreign keys and their ON DELETE rules",
  concept="Referential integrity metadata",
  objective="List every relationship edge with its delete rule and deferrability.",
  sql="""SELECT src.relname AS child_table, pg_get_constraintdef(k.oid) AS definition,
       CASE k.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'c' THEN 'CASCADE'
                          WHEN 'r' THEN 'RESTRICT' WHEN 'n' THEN 'SET NULL' END AS on_delete,
       k.condeferrable AS deferrable, k.condeferred AS initially_deferred
FROM pg_constraint k
JOIN pg_class src ON src.oid = k.conrelid
WHERE k.contype = 'f'
  AND src.relname IN ('courts','bookings','payments','reviews','maintenance')
ORDER BY src.relname, k.conname;""",
  tables=["pg_constraint", "pg_class"],
  tuple="One tuple = one foreign-key constraint.",
  notes="Weak entities (payments, reviews, maintenance) use ON DELETE CASCADE; history-bearing parents "
        "use NO ACTION so the database refuses to delete them. Django creates FKs as DEFERRABLE "
        "INITIALLY DEFERRED: they are checked at COMMIT unless SET CONSTRAINTS ALL IMMEDIATE.")

q(slug="unique-check-inspection", category="E", title="Inspect UNIQUE, CHECK and EXCLUDE constraints",
  concept="Domain and key constraints",
  objective="List the business rules enforced by the database itself.",
  sql="""SELECT c.relname AS table_name, k.conname AS constraint_name,
       CASE k.contype WHEN 'u' THEN 'UNIQUE' WHEN 'c' THEN 'CHECK' WHEN 'x' THEN 'EXCLUDE' END AS type,
       pg_get_constraintdef(k.oid) AS definition
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
WHERE k.contype IN ('u','c','x')
  AND c.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY c.relname, type, k.conname;""",
  tables=["pg_constraint", "pg_class"], tuple="One tuple = one constraint.")

q(slug="invalid-check", category="E", kind="sandbox", title="CHECK constraints reject invalid data",
  concept="Domain integrity enforced by the DBMS",
  objective="Attempt three invalid inserts and read PostgreSQL's errors.",
  steps=[
      {"sql": "INSERT INTO reviews (booking_id, rating, comment, created_at)\n"
              "SELECT MIN(b.booking_id), 7, 'seven stars!', now() FROM bookings b\n"
              "WHERE NOT EXISTS (SELECT 1 FROM reviews r WHERE r.booking_id = b.booking_id);",
       "note": "rating must be 1..5", "expect_error": True},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "VALUES (2, 1, now() + interval '3 days', now() + interval '3 days', 400, 'pending', now());",
       "note": "zero-length booking: end_time = start_time violates bookings_time_order", "expect_error": True},
      {"sql": "UPDATE payments SET amount = -50 WHERE booking_id = (SELECT MIN(booking_id) FROM payments);",
       "note": "negative payment amount", "expect_error": True},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "VALUES (2, 1, now() + interval '30 days', now() + interval '30 days 1 hour', 400, 'reserved', now());",
       "note": "status not in the allowed set", "expect_error": True},
  ],
  tables=["reviews", "bookings", "payments"],
  notes="Each failing statement is wrapped in a SAVEPOINT so the demo can continue; SQLSTATE 23514 = check_violation. "
        "Curiosity: if end_time < start_time, PostgreSQL fails even earlier with SQLSTATE 22000, because building "
        "tstzrange(start, end) for the exclusion constraint's index raises 'range lower bound must be less than "
        "or equal to range upper bound'.")

q(slug="invalid-fk", category="E", kind="sandbox", title="Referential integrity: invalid and dangling references",
  concept="Foreign keys prevent orphans",
  objective="Insert a booking for a court that does not exist, and delete a facility that still has courts.",
  steps=[
      {"sql": "SET CONSTRAINTS ALL IMMEDIATE;",
       "note": "Django's FKs are DEFERRABLE INITIALLY DEFERRED; this makes them fire per statement."},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "VALUES (2, 999999, now() + interval '40 days', now() + interval '40 days 1 hour', 400, 'pending', now());",
       "note": "court 999999 does not exist", "expect_error": True},
      {"sql": "DELETE FROM facilities WHERE facility_id = 1;",
       "note": "facility 1 still has courts (ON DELETE NO ACTION)", "expect_error": True},
      {"sql": "DELETE FROM users WHERE user_id = 2;",
       "note": "user 2 has bookings (history must be preserved)", "expect_error": True},
  ],
  tables=["bookings", "facilities", "users"],
  notes="SQLSTATE 23503 = foreign_key_violation.")

q(slug="unique-violations", category="E", kind="sandbox", title="UNIQUE / PRIMARY KEY violations",
  concept="Key constraints, including the 1:1 rule of a weak entity",
  objective="Insert a duplicate email and a second review for an already-reviewed booking.",
  steps=[
      {"sql": "INSERT INTO users (name, email, password_hash, role, created_at, is_active)\n"
              "VALUES ('Copycat', 'aarav.sharma@example.com', 'x', 'customer', now(), true);",
       "note": "email is UNIQUE", "expect_error": True},
      {"sql": "INSERT INTO users (name, email, password_hash, role, created_at, is_active)\n"
              "VALUES ('Shouty', 'AARAV.SHARMA@EXAMPLE.COM', 'x', 'customer', now(), true);",
       "note": "upper-case variant is rejected by the lowercase CHECK", "expect_error": True},
      {"sql": "INSERT INTO reviews (booking_id, rating, comment, created_at)\n"
              "SELECT booking_id, 5, 'second review', now() FROM reviews ORDER BY booking_id LIMIT 1;",
       "note": "reviews.booking_id is the PK, so one review per booking", "expect_error": True},
      {"sql": "INSERT INTO maintenance (court_id, start_time, end_time, reason)\n"
              "SELECT court_id, start_time, start_time + interval '10 minutes', 'duplicate key' FROM maintenance LIMIT 1;",
       "note": "composite PK (court_id, start_time) already exists", "expect_error": True},
  ],
  tables=["users", "reviews", "maintenance"], notes="SQLSTATE 23505 = unique_violation.")

q(slug="exclusion-overlap", category="E", kind="sandbox", title="EXCLUDE constraint + trigger: no double booking",
  concept="Exclusion constraint on (court_id =, tstzrange &&) and a cross-table trigger",
  objective="Try to double-book a court, book during maintenance, and show that a cancelled booking does not block.",
  steps=[
      {"sql": "SELECT booking_id, court_id, start_time, end_time, status FROM bookings\n"
              "WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1;",
       "note": "An existing confirmed booking."},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "SELECT 3, court_id, start_time, end_time, total_amount, 'pending', now() FROM bookings\n"
              "WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1;",
       "note": "Same court, same time → bookings_no_overlap", "expect_error": True},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "SELECT 3, court_id, start_time, end_time, total_amount, 'cancelled', now() FROM bookings\n"
              "WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1\n"
              "RETURNING booking_id, court_id, start_time, status;",
       "note": "Allowed: the constraint has WHERE (status <> 'cancelled')."},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "SELECT 3, court_id, start_time, end_time, 0, 'pending', now() FROM maintenance\n"
              "ORDER BY start_time DESC LIMIT 1;",
       "note": "Overlaps a maintenance window → trigger raises an exclusion_violation", "expect_error": True},
  ],
  tables=["bookings", "maintenance"],
  notes="tstzrange(start,end,'[)') is half-open, so 10:00–11:00 and 11:00–12:00 do NOT overlap. "
        "SQLSTATE 23P01 = exclusion_violation.")

q(slug="cascade-weak-entity", category="E", kind="sandbox", title="ON DELETE CASCADE for weak entities",
  concept="Existence dependency of PAYMENT and REVIEW on BOOKING",
  objective="Delete a booking that has a payment and a review, and watch the weak-entity rows disappear.",
  steps=[
      {"sql": "SELECT r.booking_id, p.payment_status, r.rating FROM reviews r\n"
              "JOIN payments p ON p.booking_id = r.booking_id ORDER BY r.booking_id LIMIT 1;"},
      {"sql": "DELETE FROM bookings WHERE booking_id = (\n"
              "  SELECT r.booking_id FROM reviews r JOIN payments p ON p.booking_id = r.booking_id\n"
              "  ORDER BY r.booking_id LIMIT 1) RETURNING booking_id;"},
      {"sql": "SELECT (SELECT COUNT(*) FROM payments) AS payments_now, (SELECT COUNT(*) FROM reviews) AS reviews_now;",
       "note": "Both counts dropped by one: the dependent rows were cascaded."},
  ],
  verify_sql="SELECT (SELECT COUNT(*) FROM payments) AS payments_after_rollback, "
             "(SELECT COUNT(*) FROM reviews) AS reviews_after_rollback",
  tables=["bookings", "payments", "reviews"],
  notes="In the application bookings are cancelled, not deleted; this demonstrates the FK rule only.")

q(slug="view-definition", category="E", title="SQL views: definition of v_booking_details",
  concept="Views as stored queries (no data duplication)",
  objective="Show the SQL behind the reporting view.",
  sql="""SELECT viewname, pg_get_viewdef(viewname::regclass, true) AS definition
FROM pg_views
WHERE schemaname = 'public'
ORDER BY viewname;""",
  tables=["pg_views"], tuple="One tuple = one view and its stored SELECT.")

# ==================================================== F. TRANSACTIONS & CONCURRENCY
q(slug="atomic-booking", category="F", kind="sandbox", title="Atomic booking: BEGIN … ROLLBACK",
  concept="Atomicity: all statements of a transaction succeed or none persist",
  objective="Reproduce the application's booking+payment transaction, fail half-way and roll back.",
  steps=[
      {"sql": "SELECT court_id, court_name, hourly_rate FROM courts WHERE court_id = 1 FOR UPDATE;",
       "note": "Step 1 – lock the court row so concurrent bookings for this court wait."},
      {"sql": "INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)\n"
              "VALUES (2, 1, date_trunc('day', now()) + interval '60 days 7 hours',\n"
              "        date_trunc('day', now()) + interval '60 days 9 hours', 2 * 400.00, 'pending', now())\n"
              "RETURNING booking_id, status, total_amount;",
       "note": "Step 2 – insert the booking (price = 2 h × rate)."},
      {"sql": "INSERT INTO payments (booking_id, amount, payment_method, payment_status, paid_at)\n"
              "SELECT MAX(booking_id), 800.00, 'upi', 'paid', now() FROM bookings\n"
              "RETURNING booking_id, payment_status;",
       "note": "Step 3 – record the payment."},
      {"sql": "UPDATE bookings SET status = 'confirmed' WHERE booking_id = (SELECT MAX(booking_id) FROM bookings)\n"
              "RETURNING booking_id, status;",
       "note": "Step 4 – confirm the booking."},
      {"sql": "INSERT INTO payments (booking_id, amount, payment_method, payment_status)\n"
              "SELECT MAX(booking_id), 800.00, 'upi', 'pending' FROM bookings;",
       "note": "Step 5 – a faulty second payment row violates the PK → the transaction must be rolled back.",
       "expect_error": True},
  ],
  verify_sql="SELECT COUNT(*) AS bookings_on_that_day_after_rollback FROM bookings "
             "WHERE court_id = 1 AND start_time = date_trunc('day', now()) + interval '60 days 7 hours'",
  tables=["courts", "bookings", "payments"],
  notes="After ROLLBACK the verification query (run in a new transaction) finds 0 rows: neither the booking "
        "nor the payment persisted. The app does the same with transaction.atomic().")

q(slug="isolation-level", category="F", title="Transaction settings of the lab connection",
  concept="Isolation level, read-only transactions, statement timeout",
  objective="Show the safety settings under which every lab query runs.",
  sql="""SELECT current_user                              AS role,
       current_setting('transaction_isolation')  AS isolation_level,
       current_setting('transaction_read_only')  AS read_only,
       current_setting('statement_timeout')      AS statement_timeout,
       pg_backend_pid()                          AS server_process_id;""",
  tables=[],
  tuple="One tuple describing the current transaction.",
  notes="PostgreSQL's default isolation is READ COMMITTED: each statement sees data committed before it began. "
        "Double booking is prevented not by isolation but by the row lock on the court (FOR UPDATE) plus "
        "the EXCLUDE constraint, which is checked atomically even between concurrent transactions.")

q(slug="savepoints", category="F", kind="sandbox", title="SAVEPOINT and ROLLBACK TO SAVEPOINT",
  concept="Partial rollback inside a transaction",
  objective="Keep the first insert while undoing a failed second one.",
  steps=[
      {"sql": "INSERT INTO sports (name) VALUES ('Archery') RETURNING sport_id, name;"},
      {"sql": "SAVEPOINT before_duplicate;"},
      {"sql": "INSERT INTO sports (name) VALUES ('archery');",
       "note": "Duplicate (case-insensitive unique index on lower(name))", "expect_error": True},
      {"sql": "ROLLBACK TO SAVEPOINT before_duplicate;"},
      {"sql": "SELECT sport_id, name FROM sports WHERE lower(name) = 'archery';",
       "note": "'Archery' survived the partial rollback."},
  ],
  verify_sql="SELECT COUNT(*) AS archery_after_full_rollback FROM sports WHERE lower(name) = 'archery'",
  tables=["sports"])

q(slug="locks-view", category="F", title="Locks currently held (pg_locks)",
  concept="Lock manager inspection",
  objective="See the locks taken by the lab's own read-only transaction.",
  sql="""SELECT l.locktype, l.relation::regclass AS relation, l.mode, l.granted
FROM pg_locks l
WHERE l.pid = pg_backend_pid()
ORDER BY relation NULLS FIRST;""",
  tables=["pg_locks"],
  tuple="One tuple = one lock held by this session.",
  notes="A plain SELECT takes only AccessShareLock, which conflicts with nothing but DDL. A booking takes a "
        "RowExclusiveLock on bookings and a row lock on the court.")

# =================================================== G. PERFORMANCE & QUERY PLANS
q(slug="index-inspection", category="G", title="Indexes with size and usage counters",
  concept="Index catalogue and statistics",
  objective="List every index, its definition, size and how often the planner has used it.",
  sql="""SELECT s.relname AS table_name, s.indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       s.idx_scan AS times_used,
       pg_get_indexdef(s.indexrelid) AS definition
FROM pg_stat_user_indexes s
WHERE s.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY s.relname, s.indexrelname;""",
  tables=["pg_stat_user_indexes"],
  tuple="One tuple = one index.",
  notes="Every PK and UNIQUE constraint is backed by a B-tree index; each EXCLUDE constraint by a GiST index.")

q(slug="explain-user-history", category="G", title="EXPLAIN ANALYZE: a user's booking history",
  concept="Reading a query plan",
  objective="See how PostgreSQL finds one user's ten most recent bookings.",
  sql="""EXPLAIN (ANALYZE, BUFFERS)
SELECT booking_id, start_time, status, total_amount
FROM bookings
WHERE user_id = 2
ORDER BY start_time DESC
LIMIT 10;""",
  tables=["bookings"],
  notes="With only ~90 seeded bookings the planner picks a Seq Scan + Sort: the table is a couple of pages, "
        "so an index would only add work. After `python manage.py seed_data --reset --bulk 20000` the plan "
        "changes to an index scan that returns rows already ordered (no Sort node). Which index it picks is a "
        "cost decision: it may use bookings_user_start_idx (user_id = 2, ordered by start_time), or walk "
        "bookings_start_idx backwards and filter on user_id — with LIMIT 10 and a user owning ~8% of the rows, "
        "the 10 matches are found after reading ~100 index entries, which the planner estimates as cheaper.")

q(slug="explain-availability", category="G", title="EXPLAIN: availability check using the GiST index",
  concept="Range overlap (&&) served by the exclusion constraint's GiST index",
  objective="Plan for 'is court 1 busy between these times?' — the same predicate the app uses.",
  sql="""EXPLAIN (ANALYZE, BUFFERS)
SELECT booking_id, start_time, end_time
FROM bookings
WHERE court_id = 1
  AND status <> 'cancelled'
  AND tstzrange(start_time, end_time, '[)') && tstzrange(now(), now() + interval '7 days', '[)');""",
  tables=["bookings"],
  notes="The range predicate and WHERE status <> 'cancelled' match the definition of the partial GiST index "
        "behind bookings_no_overlap. On a large table (seed with --bulk) PostgreSQL combines a Bitmap Index Scan "
        "on that GiST index with one on bookings(court_id) using a BitmapAnd, then visits only matching pages.")

q(slug="compare-index-vs-seq", category="G", kind="compare", title="Compare: planner's choice vs. index scans disabled",
  concept="Indexes do not automatically make every query faster",
  objective="Run the same query twice and compare PostgreSQL's real measured timings.",
  sql="""SELECT booking_id, start_time, status
FROM bookings
WHERE user_id = 2
ORDER BY start_time DESC
LIMIT 10""",
  tables=["bookings"],
  notes="The second run sets enable_indexscan / enable_bitmapscan / enable_indexonlyscan = off for that "
        "transaction only, forcing a sequential scan. Timings are measured by EXPLAIN ANALYZE and vary run to "
        "run (caching, machine load). On tiny tables the difference is negligible or reversed.")

q(slug="table-stats", category="G", title="Sequential vs index scans per table (statistics collector)",
  concept="Planner statistics and access-path counters",
  objective="Show how each table has been accessed since statistics were reset.",
  sql="""SELECT relname AS table_name, n_live_tup AS live_rows, seq_scan, idx_scan,
       last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY relname;""",
  tables=["pg_stat_user_tables"], tuple="One tuple = access statistics of one table.")

# ===================================================================== H. REPORTS
_REPORT_EXPLAIN = {
    "facility_revenue": ("Revenue by facility (view v_facility_revenue)",
                         "One tuple = one facility. revenue_collected counts only payments with status 'paid'; "
                         "refunds are shown separately and excluded from revenue."),
    "sport_popularity": ("Sport popularity", "One tuple = one sport (LEFT JOIN keeps sports with no bookings)."),
    "court_utilization": ("Court utilisation, last 30 days",
                          "One tuple = one court; utilisation = hours booked / (30 days × 17 bookable hours)."),
    "ratings": ("Average rating per court", "One tuple = one court that has at least one review."),
    "upcoming_maintenance": ("Maintenance schedule", "One tuple = one future or ongoing maintenance window."),
    "monthly_revenue": ("Collected revenue per month", "One tuple = one calendar month."),
}
for key, (title, tuple_text) in _REPORT_EXPLAIN.items():
    q(slug=f"report-{key.replace('_', '-')}", category="H", title=title, concept="Reporting query",
      objective=REPORTS[key]["title"], sql=REPORTS[key]["sql"] + ";", tuple=tuple_text,
      notes="Same SQL as the admin Reports page (defined once in sports/reports.py).")

q(slug="report-user-history", category="H", title="Booking history of one user",
  concept="Reporting from a view",
  objective="Full history for customer user_id = 2, via v_booking_details.",
  sql="""SELECT booking_id, facility_name, court_name, sport_name, start_time, hours,
       total_amount, booking_status, payment_status, rating
FROM v_booking_details
WHERE user_id = 2
ORDER BY start_time DESC;""",
  tables=["v_booking_details"],
  tuple="One tuple = one booking of user 2 with all related information.")

BY_SLUG = {item["slug"]: item for item in Q}


def grouped():
    return [(code, name, [i for i in Q if i["category"] == code]) for code, name in CATEGORIES]
