# SQL query catalogue

Generated from `dbms_lab/catalogue.py` by `python manage.py export_sql_catalogue`. Every query can be run live at `/dbms-lab/queries/<slug>/`.

* **select** – runs live as the SELECT-only role in a READ ONLY transaction
* **sandbox** – fixed write statements executed in one transaction that is always rolled back
* **compare** – the same query EXPLAIN ANALYZEd with and without index scans

## A. Basic SQL

### SELECT: list every facility

`select-all-facilities` · *select* · **Concept:** Projection (choosing columns) over a single relation

**Objective:** Retrieve the attributes of every tuple in the facilities relation.

**Tables:** facilities  
**One result tuple:** One tuple = one sports facility (one row of the facilities table).

- `facility_id` — primary key (bigint identity)
- `name` — facility name
- `city` — city
- `phone` — contact number
- `address` — street address

```sql
SELECT facility_id, name, city, phone, address
FROM facilities
ORDER BY facility_id;
```

### WHERE: active courts cheaper than ₹500/hour

`where-filter` · *select* · **Concept:** Selection (σ): keep only tuples that satisfy a predicate

**Objective:** Show which courts a budget-conscious player could book.

**Tables:** courts  
**Filters:** `is_active = TRUE AND hourly_rate < 500`  
**One result tuple:** One tuple = one court that satisfies both conditions.

- `court_id` — PK of the court
- `court_name` — name within its facility
- `hourly_rate` — numeric(8,2) price per hour

```sql
SELECT court_id, court_name, hourly_rate
FROM courts
WHERE is_active = TRUE
  AND hourly_rate < 500
ORDER BY hourly_rate, court_name;
```

### ORDER BY + LIMIT: five most expensive courts

`order-limit` · *select* · **Concept:** Sorting and limiting a result set

**Objective:** Find the premium courts.

**Tables:** courts  
**One result tuple:** One tuple = one court; only the first 5 after sorting are returned.

- `court_name` — court
- `hourly_rate` — price per hour, highest first

```sql
SELECT court_name, hourly_rate
FROM courts
ORDER BY hourly_rate DESC, court_name
LIMIT 5;
```

> Without ORDER BY, a relation has no guaranteed order, so LIMIT alone would be arbitrary.

### DISTINCT: cities with a facility

`distinct-cities` · *select* · **Concept:** Duplicate elimination

**Objective:** List each city once, even when it has several facilities.

**Tables:** facilities  
**One result tuple:** One tuple = one distinct city value.

- `city` — a city name, each appearing once

```sql
SELECT DISTINCT city
FROM facilities
ORDER BY city;
```

> Bengaluru has two facilities but appears once. In relational algebra, projection removes duplicates automatically; in SQL you must ask for it with DISTINCT.

### INSERT … RETURNING (rolled back)

`insert-returning` · *sandbox* · **Concept:** Inserting a tuple; identity columns generate the primary key

**Objective:** Insert a new sport and see the generated sport_id.

**Tables:** sports  
**One result tuple:** RETURNING gives back the inserted tuple, including generated values.

```sql
BEGIN;
INSERT INTO sports (name) VALUES ('Pickleball') RETURNING sport_id, name;   -- sport_id was not supplied, so the IDENTITY column generated it.
SELECT sport_id, name FROM sports ORDER BY sport_id;   -- Inside the transaction the new tuple is visible.
ROLLBACK;
```

Verification after rollback:
```sql
SELECT COUNT(*) AS pickleball_rows_after_rollback FROM sports WHERE name = 'Pickleball'
```

> After ROLLBACK the row is gone, but the identity sequence value is NOT reused: sequences are non-transactional, which is why IDs can have gaps.

### UPDATE: 10% price rise at one facility (rolled back)

`update-returning` · *sandbox* · **Concept:** Modifying attribute values of selected tuples

**Objective:** Increase the hourly rate of every court at facility 1 by 10%.

**Tables:** courts  
**Filters:** `facility_id = 1`  

```sql
BEGIN;
SELECT court_id, court_name, hourly_rate FROM courts WHERE facility_id = 1 ORDER BY court_id;   -- Before the update.
UPDATE courts
SET hourly_rate = ROUND(hourly_rate * 1.10, 2)
WHERE facility_id = 1
RETURNING court_id, court_name, hourly_rate;   -- The command tag shows how many tuples were updated.
ROLLBACK;
```

Verification after rollback:
```sql
SELECT court_id, court_name, hourly_rate FROM courts WHERE facility_id = 1 ORDER BY court_id
```

> Existing bookings keep their stored total_amount: it is a snapshot of the price at booking time.

### DELETE: remove 1-star reviews (rolled back)

`delete-safely` · *sandbox* · **Concept:** Deleting tuples that satisfy a predicate

**Objective:** Delete low-rated reviews and show which tuples were removed.

**Tables:** reviews  
**Filters:** `rating = 1`  

```sql
BEGIN;
SELECT COUNT(*) AS reviews_before FROM reviews;
DELETE FROM reviews WHERE rating = 1 RETURNING booking_id, rating, comment;
SELECT COUNT(*) AS reviews_after FROM reviews;
ROLLBACK;
```

Verification after rollback:
```sql
SELECT COUNT(*) AS reviews_after_rollback FROM reviews
```

> Shown safely: the whole transaction is rolled back, so nothing is deleted from the live database.

## B. Relational operations (joins)

### INNER JOIN: courts with their facility and sport

`inner-join-courts` · *select* · **Concept:** Natural/equi-join along foreign keys

**Objective:** Replace the foreign-key numbers in courts with readable facility and sport names.

**Tables:** courts, facilities, sports  
**Joins:** `courts.facility_id = facilities.facility_id; courts.sport_id = sports.sport_id`  
**One result tuple:** One tuple = one court combined with the single facility and single sport it references.

- `facility` — facilities.name
- `court_name` — courts.court_name
- `sport` — sports.name
- `hourly_rate` — courts.hourly_rate
- `is_active` — courts.is_active

```sql
SELECT f.name AS facility, c.court_name, s.name AS sport, c.hourly_rate, c.is_active
FROM courts c
JOIN facilities f ON f.facility_id = c.facility_id
JOIN sports     s ON s.sport_id    = c.sport_id
ORDER BY f.name, c.court_name;
```

> Because every court has exactly one facility and one sport (NOT NULL FKs), the join returns exactly one row per court.

### LEFT JOIN: every sport, even without courts

`left-join-sports` · *select* · **Concept:** Outer join keeps unmatched tuples from the left relation (NULL-padded)

**Objective:** Show all sports and their courts, including sports with no court yet.

**Tables:** sports, courts  
**Joins:** `courts.sport_id = sports.sport_id (outer)`  
**One result tuple:** One tuple = one (sport, court) pair, or (sport, NULL) when the sport has no court.

- `sport_id` — PK of sport
- `sport` — sport name
- `court_id` — NULL if the sport has no court
- `court_name` — NULL if the sport has no court

```sql
SELECT s.sport_id, s.name AS sport, c.court_id, c.court_name
FROM sports s
LEFT JOIN courts c ON c.sport_id = s.sport_id
ORDER BY s.name, c.court_name;
```

> Volleyball has no courts: an INNER JOIN would drop it; the LEFT JOIN keeps it with NULLs.

### 5-table join: upcoming bookings with payment status

`multi-join-upcoming` · *select* · **Concept:** Multiple joins + outer join to an optional (weak) entity

**Objective:** Build a booking timetable a front-desk employee could use.

**Tables:** bookings, users, courts, facilities, payments  
**Joins:** `bookings→users (user_id), bookings→courts (court_id), courts→facilities (facility_id), bookings⟕payments (booking_id)`  
**Filters:** `start_time in the future and not cancelled`  
**One result tuple:** One tuple = one upcoming booking with the customer, place and payment state.

- `payment_status` — NULL when no payment row exists yet (participation of BOOKING in settled_by is partial)

```sql
SELECT b.booking_id, u.name AS customer, f.name AS facility, c.court_name,
       b.start_time, b.end_time, b.status, p.payment_status
FROM bookings b
JOIN users       u ON u.user_id     = b.user_id
JOIN courts      c ON c.court_id    = b.court_id
JOIN facilities  f ON f.facility_id = c.facility_id
LEFT JOIN payments p ON p.booking_id = b.booking_id
WHERE b.start_time > now()
  AND b.status <> 'cancelled'
ORDER BY b.start_time;
```

### Join then filter: badminton bookings in Bengaluru

`join-filter` · *select* · **Concept:** Selection applied to attributes coming from different joined relations

**Objective:** Find bookings for a given sport in a given city.

**Tables:** bookings, users, courts, sports, facilities  
**Filters:** `sports.name = 'Badminton' AND facilities.city = 'Bengaluru'`  
**One result tuple:** One tuple = one booking whose court plays badminton and whose facility is in Bengaluru.

```sql
SELECT b.booking_id, u.name AS customer, f.name AS facility, c.court_name, b.start_time, b.status
FROM bookings b
JOIN users      u ON u.user_id     = b.user_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN sports     s ON s.sport_id    = c.sport_id
JOIN facilities f ON f.facility_id = c.facility_id
WHERE s.name = 'Badminton'
  AND f.city = 'Bengaluru'
ORDER BY b.start_time DESC;
```

### LEFT JOIN … IS NULL: users who never booked

`anti-join-no-bookings` · *select* · **Concept:** Anti-join

**Objective:** Find registered customers with no booking history.

**Tables:** users, bookings  
**Joins:** `bookings.user_id = users.user_id (outer)`  
**Filters:** `no matching booking (b.booking_id IS NULL)`  
**One result tuple:** One tuple = one customer with zero bookings.

```sql
SELECT u.user_id, u.name, u.email, u.created_at
FROM users u
LEFT JOIN bookings b ON b.user_id = u.user_id
WHERE u.role = 'customer'
  AND b.booking_id IS NULL
ORDER BY u.user_id;
```

> Participation of USER in 'places' is partial: a user may exist without bookings.

### Self-join: alternative courts for the same sport

`self-join-alternatives` · *select* · **Concept:** Joining a relation with itself using aliases

**Objective:** For each court, list other courts in the same facility for the same sport.

**Tables:** courts (as a), courts (as b), facilities, sports  
**Joins:** `a.facility_id = b.facility_id AND a.sport_id = b.sport_id AND a.court_id <> b.court_id`  
**One result tuple:** One tuple = an ordered pair (court, alternative court) of the same facility and sport.

```sql
SELECT f.name AS facility, a.court_name AS court, b.court_name AS alternative, s.name AS sport
FROM courts a
JOIN courts b     ON b.facility_id = a.facility_id
                 AND b.sport_id    = a.sport_id
                 AND b.court_id   <> a.court_id
JOIN facilities f ON f.facility_id = a.facility_id
JOIN sports     s ON s.sport_id    = a.sport_id
ORDER BY f.name, a.court_name, b.court_name;
```

## C. Aggregation

### COUNT + GROUP BY: bookings per status

`count-by-status` · *select* · **Concept:** Grouping tuples and counting each group

**Objective:** See how many bookings are pending, confirmed, completed or cancelled.

**Tables:** bookings  
**One result tuple:** One tuple = one group (one distinct status value).

- `status` — group key
- `bookings` — number of tuples in the group

```sql
SELECT status, COUNT(*) AS bookings
FROM bookings
GROUP BY status
ORDER BY bookings DESC;
```

### SUM / AVG / MIN / MAX per facility

`sum-avg-min-max` · *select* · **Concept:** Aggregate functions over groups

**Objective:** Summarise the booking value of each facility (cancelled bookings excluded).

**Tables:** facilities, courts, bookings  
**Joins:** `courts.facility_id = facilities.facility_id; bookings.court_id = courts.court_id`  
**Filters:** `WHERE removes cancelled bookings BEFORE grouping`  
**One result tuple:** One tuple = one facility with aggregates computed over its non-cancelled bookings.

```sql
SELECT f.name AS facility,
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
ORDER BY booked_value DESC;
```

> booked_value is the price of bookings, not money received; see the revenue report for collected money.

### HAVING: customers with more than 5 active bookings

`having-frequent` · *select* · **Concept:** Filtering groups (HAVING) vs. filtering rows (WHERE)

**Objective:** Identify frequent players.

**Tables:** users, bookings  
**Filters:** `WHERE status <> 'cancelled'; HAVING COUNT(*) > 5`  
**One result tuple:** One tuple = one customer whose group of bookings has more than 5 members.

```sql
SELECT u.user_id, u.name, COUNT(*) AS active_bookings, SUM(b.total_amount) AS total_value
FROM users u
JOIN bookings b ON b.user_id = u.user_id
WHERE b.status <> 'cancelled'
GROUP BY u.user_id, u.name
HAVING COUNT(*) > 5
ORDER BY active_bookings DESC;
```

### AVG rating per facility (with review counts)

`avg-rating-facility` · *select* · **Concept:** Aggregation across a chain of joins

**Objective:** Rank facilities by customer satisfaction.

**Tables:** reviews, bookings, courts, facilities  
**Joins:** `reviews→bookings→courts→facilities`  
**One result tuple:** One tuple = one facility with at least two reviews.

```sql
SELECT f.name AS facility, COUNT(*) AS reviews, ROUND(AVG(r.rating), 2) AS avg_rating
FROM reviews r
JOIN bookings   b ON b.booking_id  = r.booking_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN facilities f ON f.facility_id = c.facility_id
GROUP BY f.facility_id, f.name
HAVING COUNT(*) >= 2
ORDER BY avg_rating DESC;
```

> A review has no facility_id column: the facility is reached through the booking and court (storing it again would be redundant and could become inconsistent).

## D. Advanced queries

### Subquery: courts priced above the overall average

`scalar-subquery` · *select* · **Concept:** Scalar subquery in WHERE

**Objective:** Find courts that cost more than the average court.

**Tables:** courts  
**One result tuple:** One tuple = one court whose rate exceeds the single average value.

```sql
SELECT court_name, hourly_rate,
       (SELECT ROUND(AVG(hourly_rate), 2) FROM courts) AS overall_avg
FROM courts
WHERE hourly_rate > (SELECT AVG(hourly_rate) FROM courts)
ORDER BY hourly_rate DESC;
```

### Correlated subquery: above the average of its own sport

`correlated-subquery` · *select* · **Concept:** A subquery re-evaluated for each outer tuple

**Objective:** Find courts that are expensive compared with other courts of the same sport.

**Tables:** courts (outer c), courts (inner c2), sports  
**Joins:** `c2.sport_id = c.sport_id (correlation)`  
**One result tuple:** One tuple = a court priced above the average for its sport.

```sql
SELECT s.name AS sport, c.court_name, c.hourly_rate
FROM courts c
JOIN sports s ON s.sport_id = c.sport_id
WHERE c.hourly_rate > (
        SELECT AVG(c2.hourly_rate)
        FROM courts c2
        WHERE c2.sport_id = c.sport_id   -- correlation with the outer row
      )
ORDER BY s.name, c.hourly_rate DESC;
```

### IN subquery: customers who have played tennis

`in-subquery` · *select* · **Concept:** Set membership with IN

**Objective:** List users with at least one non-cancelled tennis booking.

**Tables:** users, bookings, courts, sports  
**One result tuple:** One tuple = one user (appearing once even with many tennis bookings).

```sql
SELECT user_id, name
FROM users
WHERE user_id IN (
    SELECT b.user_id
    FROM bookings b
    JOIN courts c ON c.court_id = b.court_id
    JOIN sports s ON s.sport_id = c.sport_id
    WHERE s.name = 'Tennis' AND b.status <> 'cancelled'
)
ORDER BY name;
```

### EXISTS: facilities with upcoming maintenance

`exists-maintenance` · *select* · **Concept:** Existential quantification

**Objective:** Warn about facilities where some court will be closed for maintenance.

**Tables:** facilities, courts, maintenance  
**One result tuple:** One tuple = one facility for which the subquery returns ≥ 1 row.

```sql
SELECT f.facility_id, f.name, f.city
FROM facilities f
WHERE EXISTS (
    SELECT 1
    FROM courts c
    JOIN maintenance m ON m.court_id = c.court_id
    WHERE c.facility_id = f.facility_id
      AND m.end_time > now()
)
ORDER BY f.name;
```

### NOT EXISTS: completed bookings that were never reviewed

`not-exists-unreviewed` · *select* · **Concept:** Negated existential quantification (anti-join)

**Objective:** Find customers to remind about leaving a review.

**Tables:** bookings, users, reviews  
**One result tuple:** One tuple = one completed booking with no tuple in reviews.

```sql
SELECT b.booking_id, u.name AS customer, b.end_time
FROM bookings b
JOIN users u ON u.user_id = b.user_id
WHERE b.status = 'completed'
  AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.booking_id = b.booking_id)
ORDER BY b.end_time DESC;
```

### CTE: top spenders by money actually paid

`cte-top-spenders` · *select* · **Concept:** Common Table Expression (WITH) for readable multi-step queries

**Objective:** Compute each customer's paid total, then keep customers above the average.

**Tables:** bookings, payments, users  
**One result tuple:** One tuple = one customer whose paid total is above the average customer's.

```sql
WITH spend AS (
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
ORDER BY s.paid_total DESC;
```

### Window function: rank courts by revenue within each facility

`window-rank` · *select* · **Concept:** RANK() OVER (PARTITION BY … ORDER BY …)

**Objective:** Find each facility's best-earning court without collapsing rows like GROUP BY would.

**Tables:** courts, bookings, payments, facilities  
**One result tuple:** One tuple = one court with its rank and revenue share inside its own facility.

```sql
WITH court_revenue AS (
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
ORDER BY f.name, rank_in_facility;
```

### Window function: running total of collected revenue

`window-running-total` · *select* · **Concept:** SUM() OVER (ORDER BY …) cumulative aggregate

**Objective:** Show daily collected revenue and the running total.

**Tables:** payments  
**One result tuple:** One tuple = one calendar day with money collected that day and in total so far.

```sql
SELECT paid_at::date AS day,
       SUM(amount) AS collected,
       SUM(SUM(amount)) OVER (ORDER BY paid_at::date) AS running_total
FROM payments
WHERE payment_status = 'paid'
GROUP BY paid_at::date
ORDER BY day;
```

## E. Design & integrity

### Inspect primary keys (incl. composite and weak-entity keys)

`pk-inspection` · *select* · **Concept:** Primary keys from the system catalogue

**Objective:** Show the PK of every application table, read directly from pg_constraint.

**Tables:** pg_constraint, pg_class  
**One result tuple:** One tuple = the primary-key constraint of one table.

```sql
SELECT c.relname AS table_name, k.conname AS constraint_name,
       pg_get_constraintdef(k.oid) AS definition,
       array_length(k.conkey, 1) AS key_columns
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
WHERE k.contype = 'p'
  AND c.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY c.relname;
```

> payments and reviews use booking_id (the owner's key) as PK; maintenance has a 2-column composite PK.

### Inspect foreign keys and their ON DELETE rules

`fk-inspection` · *select* · **Concept:** Referential integrity metadata

**Objective:** List every relationship edge with its delete rule and deferrability.

**Tables:** pg_constraint, pg_class  
**One result tuple:** One tuple = one foreign-key constraint.

```sql
SELECT src.relname AS child_table, pg_get_constraintdef(k.oid) AS definition,
       CASE k.confdeltype WHEN 'a' THEN 'NO ACTION' WHEN 'c' THEN 'CASCADE'
                          WHEN 'r' THEN 'RESTRICT' WHEN 'n' THEN 'SET NULL' END AS on_delete,
       k.condeferrable AS deferrable, k.condeferred AS initially_deferred
FROM pg_constraint k
JOIN pg_class src ON src.oid = k.conrelid
WHERE k.contype = 'f'
  AND src.relname IN ('courts','bookings','payments','reviews','maintenance')
ORDER BY src.relname, k.conname;
```

> Weak entities (payments, reviews, maintenance) use ON DELETE CASCADE; history-bearing parents use NO ACTION so the database refuses to delete them. Django creates FKs as DEFERRABLE INITIALLY DEFERRED: they are checked at COMMIT unless SET CONSTRAINTS ALL IMMEDIATE.

### Inspect UNIQUE, CHECK and EXCLUDE constraints

`unique-check-inspection` · *select* · **Concept:** Domain and key constraints

**Objective:** List the business rules enforced by the database itself.

**Tables:** pg_constraint, pg_class  
**One result tuple:** One tuple = one constraint.

```sql
SELECT c.relname AS table_name, k.conname AS constraint_name,
       CASE k.contype WHEN 'u' THEN 'UNIQUE' WHEN 'c' THEN 'CHECK' WHEN 'x' THEN 'EXCLUDE' END AS type,
       pg_get_constraintdef(k.oid) AS definition
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
WHERE k.contype IN ('u','c','x')
  AND c.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY c.relname, type, k.conname;
```

### CHECK constraints reject invalid data

`invalid-check` · *sandbox* · **Concept:** Domain integrity enforced by the DBMS

**Objective:** Attempt three invalid inserts and read PostgreSQL's errors.

**Tables:** reviews, bookings, payments  

```sql
BEGIN;
INSERT INTO reviews (booking_id, rating, comment, created_at)
SELECT MIN(b.booking_id), 7, 'seven stars!', now() FROM bookings b
WHERE NOT EXISTS (SELECT 1 FROM reviews r WHERE r.booking_id = b.booking_id);   -- rating must be 1..5
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
VALUES (2, 1, now() + interval '3 days', now() + interval '3 days', 400, 'pending', now());   -- zero-length booking: end_time = start_time violates bookings_time_order
UPDATE payments SET amount = -50 WHERE booking_id = (SELECT MIN(booking_id) FROM payments);   -- negative payment amount
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
VALUES (2, 1, now() + interval '30 days', now() + interval '30 days 1 hour', 400, 'reserved', now());   -- status not in the allowed set
ROLLBACK;
```

> Each failing statement is wrapped in a SAVEPOINT so the demo can continue; SQLSTATE 23514 = check_violation. Curiosity: if end_time < start_time, PostgreSQL fails even earlier with SQLSTATE 22000, because building tstzrange(start, end) for the exclusion constraint's index raises 'range lower bound must be less than or equal to range upper bound'.

### Referential integrity: invalid and dangling references

`invalid-fk` · *sandbox* · **Concept:** Foreign keys prevent orphans

**Objective:** Insert a booking for a court that does not exist, and delete a facility that still has courts.

**Tables:** bookings, facilities, users  

```sql
BEGIN;
SET CONSTRAINTS ALL IMMEDIATE;   -- Django's FKs are DEFERRABLE INITIALLY DEFERRED; this makes them fire per statement.
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
VALUES (2, 999999, now() + interval '40 days', now() + interval '40 days 1 hour', 400, 'pending', now());   -- court 999999 does not exist
DELETE FROM facilities WHERE facility_id = 1;   -- facility 1 still has courts (ON DELETE NO ACTION)
DELETE FROM users WHERE user_id = 2;   -- user 2 has bookings (history must be preserved)
ROLLBACK;
```

> SQLSTATE 23503 = foreign_key_violation.

### UNIQUE / PRIMARY KEY violations

`unique-violations` · *sandbox* · **Concept:** Key constraints, including the 1:1 rule of a weak entity

**Objective:** Insert a duplicate email and a second review for an already-reviewed booking.

**Tables:** users, reviews, maintenance  

```sql
BEGIN;
INSERT INTO users (name, email, password_hash, role, created_at, is_active)
VALUES ('Copycat', 'aarav.sharma@example.com', 'x', 'customer', now(), true);   -- email is UNIQUE
INSERT INTO users (name, email, password_hash, role, created_at, is_active)
VALUES ('Shouty', 'AARAV.SHARMA@EXAMPLE.COM', 'x', 'customer', now(), true);   -- upper-case variant is rejected by the lowercase CHECK
INSERT INTO reviews (booking_id, rating, comment, created_at)
SELECT booking_id, 5, 'second review', now() FROM reviews ORDER BY booking_id LIMIT 1;   -- reviews.booking_id is the PK, so one review per booking
INSERT INTO maintenance (court_id, start_time, end_time, reason)
SELECT court_id, start_time, start_time + interval '10 minutes', 'duplicate key' FROM maintenance LIMIT 1;   -- composite PK (court_id, start_time) already exists
ROLLBACK;
```

> SQLSTATE 23505 = unique_violation.

### EXCLUDE constraint + trigger: no double booking

`exclusion-overlap` · *sandbox* · **Concept:** Exclusion constraint on (court_id =, tstzrange &&) and a cross-table trigger

**Objective:** Try to double-book a court, book during maintenance, and show that a cancelled booking does not block.

**Tables:** bookings, maintenance  

```sql
BEGIN;
SELECT booking_id, court_id, start_time, end_time, status FROM bookings
WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1;   -- An existing confirmed booking.
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
SELECT 3, court_id, start_time, end_time, total_amount, 'pending', now() FROM bookings
WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1;   -- Same court, same time → bookings_no_overlap
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
SELECT 3, court_id, start_time, end_time, total_amount, 'cancelled', now() FROM bookings
WHERE status = 'confirmed' AND start_time > now() ORDER BY booking_id LIMIT 1
RETURNING booking_id, court_id, start_time, status;   -- Allowed: the constraint has WHERE (status <> 'cancelled').
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
SELECT 3, court_id, start_time, end_time, 0, 'pending', now() FROM maintenance
ORDER BY start_time DESC LIMIT 1;   -- Overlaps a maintenance window → trigger raises an exclusion_violation
ROLLBACK;
```

> tstzrange(start,end,'[)') is half-open, so 10:00–11:00 and 11:00–12:00 do NOT overlap. SQLSTATE 23P01 = exclusion_violation.

### ON DELETE CASCADE for weak entities

`cascade-weak-entity` · *sandbox* · **Concept:** Existence dependency of PAYMENT and REVIEW on BOOKING

**Objective:** Delete a booking that has a payment and a review, and watch the weak-entity rows disappear.

**Tables:** bookings, payments, reviews  

```sql
BEGIN;
SELECT r.booking_id, p.payment_status, r.rating FROM reviews r
JOIN payments p ON p.booking_id = r.booking_id ORDER BY r.booking_id LIMIT 1;
DELETE FROM bookings WHERE booking_id = (
  SELECT r.booking_id FROM reviews r JOIN payments p ON p.booking_id = r.booking_id
  ORDER BY r.booking_id LIMIT 1) RETURNING booking_id;
SELECT (SELECT COUNT(*) FROM payments) AS payments_now, (SELECT COUNT(*) FROM reviews) AS reviews_now;   -- Both counts dropped by one: the dependent rows were cascaded.
ROLLBACK;
```

Verification after rollback:
```sql
SELECT (SELECT COUNT(*) FROM payments) AS payments_after_rollback, (SELECT COUNT(*) FROM reviews) AS reviews_after_rollback
```

> In the application bookings are cancelled, not deleted; this demonstrates the FK rule only.

### SQL views: definition of v_booking_details

`view-definition` · *select* · **Concept:** Views as stored queries (no data duplication)

**Objective:** Show the SQL behind the reporting view.

**Tables:** pg_views  
**One result tuple:** One tuple = one view and its stored SELECT.

```sql
SELECT viewname, pg_get_viewdef(viewname::regclass, true) AS definition
FROM pg_views
WHERE schemaname = 'public'
ORDER BY viewname;
```

## F. Transactions & concurrency

### Atomic booking: BEGIN … ROLLBACK

`atomic-booking` · *sandbox* · **Concept:** Atomicity: all statements of a transaction succeed or none persist

**Objective:** Reproduce the application's booking+payment transaction, fail half-way and roll back.

**Tables:** courts, bookings, payments  

```sql
BEGIN;
SELECT court_id, court_name, hourly_rate FROM courts WHERE court_id = 1 FOR UPDATE;   -- Step 1 – lock the court row so concurrent bookings for this court wait.
INSERT INTO bookings (user_id, court_id, start_time, end_time, total_amount, status, created_at)
VALUES (2, 1, date_trunc('day', now()) + interval '60 days 7 hours',
        date_trunc('day', now()) + interval '60 days 9 hours', 2 * 400.00, 'pending', now())
RETURNING booking_id, status, total_amount;   -- Step 2 – insert the booking (price = 2 h × rate).
INSERT INTO payments (booking_id, amount, payment_method, payment_status, paid_at)
SELECT MAX(booking_id), 800.00, 'upi', 'paid', now() FROM bookings
RETURNING booking_id, payment_status;   -- Step 3 – record the payment.
UPDATE bookings SET status = 'confirmed' WHERE booking_id = (SELECT MAX(booking_id) FROM bookings)
RETURNING booking_id, status;   -- Step 4 – confirm the booking.
INSERT INTO payments (booking_id, amount, payment_method, payment_status)
SELECT MAX(booking_id), 800.00, 'upi', 'pending' FROM bookings;   -- Step 5 – a faulty second payment row violates the PK → the transaction must be rolled back.
ROLLBACK;
```

Verification after rollback:
```sql
SELECT COUNT(*) AS bookings_on_that_day_after_rollback FROM bookings WHERE court_id = 1 AND start_time = date_trunc('day', now()) + interval '60 days 7 hours'
```

> After ROLLBACK the verification query (run in a new transaction) finds 0 rows: neither the booking nor the payment persisted. The app does the same with transaction.atomic().

### Transaction settings of the lab connection

`isolation-level` · *select* · **Concept:** Isolation level, read-only transactions, statement timeout

**Objective:** Show the safety settings under which every lab query runs.

**One result tuple:** One tuple describing the current transaction.

```sql
SELECT current_user                              AS role,
       current_setting('transaction_isolation')  AS isolation_level,
       current_setting('transaction_read_only')  AS read_only,
       current_setting('statement_timeout')      AS statement_timeout,
       pg_backend_pid()                          AS server_process_id;
```

> PostgreSQL's default isolation is READ COMMITTED: each statement sees data committed before it began. Double booking is prevented not by isolation but by the row lock on the court (FOR UPDATE) plus the EXCLUDE constraint, which is checked atomically even between concurrent transactions.

### SAVEPOINT and ROLLBACK TO SAVEPOINT

`savepoints` · *sandbox* · **Concept:** Partial rollback inside a transaction

**Objective:** Keep the first insert while undoing a failed second one.

**Tables:** sports  

```sql
BEGIN;
INSERT INTO sports (name) VALUES ('Archery') RETURNING sport_id, name;
SAVEPOINT before_duplicate;
INSERT INTO sports (name) VALUES ('archery');   -- Duplicate (case-insensitive unique index on lower(name))
ROLLBACK TO SAVEPOINT before_duplicate;
SELECT sport_id, name FROM sports WHERE lower(name) = 'archery';   -- 'Archery' survived the partial rollback.
ROLLBACK;
```

Verification after rollback:
```sql
SELECT COUNT(*) AS archery_after_full_rollback FROM sports WHERE lower(name) = 'archery'
```

### Locks currently held (pg_locks)

`locks-view` · *select* · **Concept:** Lock manager inspection

**Objective:** See the locks taken by the lab's own read-only transaction.

**Tables:** pg_locks  
**One result tuple:** One tuple = one lock held by this session.

```sql
SELECT l.locktype, l.relation::regclass AS relation, l.mode, l.granted
FROM pg_locks l
WHERE l.pid = pg_backend_pid()
ORDER BY relation NULLS FIRST;
```

> A plain SELECT takes only AccessShareLock, which conflicts with nothing but DDL. A booking takes a RowExclusiveLock on bookings and a row lock on the court.

## G. Performance & query plans

### Indexes with size and usage counters

`index-inspection` · *select* · **Concept:** Index catalogue and statistics

**Objective:** List every index, its definition, size and how often the planner has used it.

**Tables:** pg_stat_user_indexes  
**One result tuple:** One tuple = one index.

```sql
SELECT s.relname AS table_name, s.indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(s.indexrelid)) AS size,
       s.idx_scan AS times_used,
       pg_get_indexdef(s.indexrelid) AS definition
FROM pg_stat_user_indexes s
WHERE s.relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY s.relname, s.indexrelname;
```

> Every PK and UNIQUE constraint is backed by a B-tree index; each EXCLUDE constraint by a GiST index.

### EXPLAIN ANALYZE: a user's booking history

`explain-user-history` · *select* · **Concept:** Reading a query plan

**Objective:** See how PostgreSQL finds one user's ten most recent bookings.

**Tables:** bookings  

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT booking_id, start_time, status, total_amount
FROM bookings
WHERE user_id = 2
ORDER BY start_time DESC
LIMIT 10;
```

> With only ~90 seeded bookings the planner picks a Seq Scan + Sort: the table is a couple of pages, so an index would only add work. After `python manage.py seed_data --reset --bulk 20000` the plan changes to an index scan that returns rows already ordered (no Sort node). Which index it picks is a cost decision: it may use bookings_user_start_idx (user_id = 2, ordered by start_time), or walk bookings_start_idx backwards and filter on user_id — with LIMIT 10 and a user owning ~8% of the rows, the 10 matches are found after reading ~100 index entries, which the planner estimates as cheaper.

### EXPLAIN: availability check using the GiST index

`explain-availability` · *select* · **Concept:** Range overlap (&&) served by the exclusion constraint's GiST index

**Objective:** Plan for 'is court 1 busy between these times?' — the same predicate the app uses.

**Tables:** bookings  

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT booking_id, start_time, end_time
FROM bookings
WHERE court_id = 1
  AND status <> 'cancelled'
  AND tstzrange(start_time, end_time, '[)') && tstzrange(now(), now() + interval '7 days', '[)');
```

> The range predicate and WHERE status <> 'cancelled' match the definition of the partial GiST index behind bookings_no_overlap. On a large table (seed with --bulk) PostgreSQL combines a Bitmap Index Scan on that GiST index with one on bookings(court_id) using a BitmapAnd, then visits only matching pages.

### Compare: planner's choice vs. index scans disabled

`compare-index-vs-seq` · *compare* · **Concept:** Indexes do not automatically make every query faster

**Objective:** Run the same query twice and compare PostgreSQL's real measured timings.

**Tables:** bookings  

```sql
SELECT booking_id, start_time, status
FROM bookings
WHERE user_id = 2
ORDER BY start_time DESC
LIMIT 10
```

> The second run sets enable_indexscan / enable_bitmapscan / enable_indexonlyscan = off for that transaction only, forcing a sequential scan. Timings are measured by EXPLAIN ANALYZE and vary run to run (caching, machine load). On tiny tables the difference is negligible or reversed.

### Sequential vs index scans per table (statistics collector)

`table-stats` · *select* · **Concept:** Planner statistics and access-path counters

**Objective:** Show how each table has been accessed since statistics were reset.

**Tables:** pg_stat_user_tables  
**One result tuple:** One tuple = access statistics of one table.

```sql
SELECT relname AS table_name, n_live_tup AS live_rows, seq_scan, idx_scan,
       last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE relname IN ('users','facilities','sports','courts','bookings','payments','reviews','maintenance')
ORDER BY relname;
```

## H. Reports

### Revenue by facility (view v_facility_revenue)

`report-facility-revenue` · *select* · **Concept:** Reporting query

**Objective:** Revenue by facility

**One result tuple:** One tuple = one facility. revenue_collected counts only payments with status 'paid'; refunds are shown separately and excluded from revenue.

```sql
SELECT facility_name, city, courts, active_bookings, cancelled_bookings,
       revenue_collected, revenue_pending, amount_refunded, avg_rating
FROM v_facility_revenue
ORDER BY revenue_collected DESC;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Sport popularity

`report-sport-popularity` · *select* · **Concept:** Reporting query

**Objective:** Sport popularity and revenue

**One result tuple:** One tuple = one sport (LEFT JOIN keeps sports with no bookings).

```sql
SELECT s.name AS sport,
       COUNT(b.booking_id) FILTER (WHERE b.status <> 'cancelled') AS bookings,
       COALESCE(SUM(EXTRACT(EPOCH FROM b.end_time - b.start_time) / 3600)
                FILTER (WHERE b.status <> 'cancelled'), 0)::numeric(10,1) AS hours_booked,
       COALESCE(SUM(p.amount) FILTER (WHERE p.payment_status = 'paid'), 0) AS revenue_collected
FROM sports s
LEFT JOIN courts   c ON c.sport_id   = s.sport_id
LEFT JOIN bookings b ON b.court_id   = c.court_id
LEFT JOIN payments p ON p.booking_id = b.booking_id
GROUP BY s.sport_id, s.name
ORDER BY bookings DESC, sport;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Court utilisation, last 30 days

`report-court-utilization` · *select* · **Concept:** Reporting query

**Objective:** Court utilisation (last 30 days, 17 bookable hours per day)

**One result tuple:** One tuple = one court; utilisation = hours booked / (30 days × 17 bookable hours).

```sql
SELECT f.name AS facility, c.court_name, c.is_active,
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
ORDER BY utilisation_pct DESC, facility, c.court_name;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Average rating per court

`report-ratings` · *select* · **Concept:** Reporting query

**Objective:** Average rating per court

**One result tuple:** One tuple = one court that has at least one review.

```sql
SELECT f.name AS facility, c.court_name, COUNT(r.booking_id) AS reviews,
       ROUND(AVG(r.rating), 2) AS avg_rating, MIN(r.rating) AS worst, MAX(r.rating) AS best
FROM reviews r
JOIN bookings   b ON b.booking_id  = r.booking_id
JOIN courts     c ON c.court_id    = b.court_id
JOIN facilities f ON f.facility_id = c.facility_id
GROUP BY f.name, c.court_id, c.court_name
ORDER BY avg_rating DESC, reviews DESC;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Maintenance schedule

`report-upcoming-maintenance` · *select* · **Concept:** Reporting query

**Objective:** Upcoming maintenance

**One result tuple:** One tuple = one future or ongoing maintenance window.

```sql
SELECT f.name AS facility, c.court_name, m.start_time, m.end_time, m.reason
FROM maintenance m
JOIN courts     c ON c.court_id    = m.court_id
JOIN facilities f ON f.facility_id = c.facility_id
WHERE m.end_time > now()
ORDER BY m.start_time;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Collected revenue per month

`report-monthly-revenue` · *select* · **Concept:** Reporting query

**Objective:** Collected revenue per month

**One result tuple:** One tuple = one calendar month.

```sql
SELECT to_char(date_trunc('month', p.paid_at), 'YYYY-MM') AS month,
       COUNT(*) AS payments, SUM(p.amount) AS revenue_collected
FROM payments p
WHERE p.payment_status = 'paid'
GROUP BY date_trunc('month', p.paid_at)
ORDER BY month;
```

> Same SQL as the admin Reports page (defined once in sports/reports.py).

### Booking history of one user

`report-user-history` · *select* · **Concept:** Reporting from a view

**Objective:** Full history for customer user_id = 2, via v_booking_details.

**Tables:** v_booking_details  
**One result tuple:** One tuple = one booking of user 2 with all related information.

```sql
SELECT booking_id, facility_name, court_name, sport_name, start_time, hours,
       total_amount, booking_status, payment_status, rating
FROM v_booking_details
WHERE user_id = 2
ORDER BY start_time DESC;
```
