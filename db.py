import csv
from collections import defaultdict
from datetime import date, time
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from models import Base, engine

DATA_DIR = Path(__file__).parent
MOVIES_PATH = DATA_DIR / "movies_normalized.csv"
SHOWTIMES_PATH = DATA_DIR / "showtimes_normalized.csv"
SCHEMA_REVISION = "normalized-movie-showtime-schema-v1"
ESCALATION_SUPPORT_REVISION = "support-escalation-slack-v1"
CATALOG_REVISION = "normalized-catalog-2026-11-v1"
BOOKING_IDEMPOTENCY_REVISION = "booking-idempotency-v1"
EXPECTED_IDS = set(range(1, 121))
MIN_SCREEN_GAP_MINUTES = 150


def _read_csv(path: Path, expected_headers: list[str]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != expected_headers:
            raise ValueError(f"{path.name} has an unexpected CSV header.")
        return list(reader)


def _read_normalized_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_movies = _read_csv(MOVIES_PATH, ["movie_id", "title", "genre"])
    raw_showtimes = _read_csv(
        SHOWTIMES_PATH,
        [
            "showtime_id", "movie_id", "date", "day_of_week", "screen_number",
            "time", "price", "total_seats", "booked_seats",
        ],
    )

    movies = []
    movie_ids = set()
    titles = set()
    for line_number, row in enumerate(raw_movies, start=2):
        movie = {
            "movie_id": int(row["movie_id"]),
            "title": row["title"].strip(),
            "genre": row["genre"].strip(),
        }
        title_key = movie["title"].casefold()
        if not movie["title"] or not movie["genre"]:
            raise ValueError(f"{MOVIES_PATH.name}:{line_number} has an empty title or genre.")
        if movie["movie_id"] in movie_ids or title_key in titles:
            raise ValueError(f"{MOVIES_PATH.name}:{line_number} has a duplicate ID or title.")
        movie_ids.add(movie["movie_id"])
        titles.add(title_key)
        movies.append(movie)

    if movie_ids != EXPECTED_IDS:
        raise ValueError("The movies file must contain each movie_id from 1 through 120 exactly once.")

    showtimes = []
    showtime_ids = set()
    occupied_slots = set()
    slots_by_screen: dict[tuple[date, str], list[time]] = defaultdict(list)
    for line_number, row in enumerate(raw_showtimes, start=2):
        show_date = date.fromisoformat(row["date"])
        start_time = time.fromisoformat(row["time"])
        showtime = {
            "showtime_id": int(row["showtime_id"]),
            "movie_id": int(row["movie_id"]),
            "date": show_date,
            "day_of_week": row["day_of_week"].strip(),
            "screen_number": row["screen_number"].strip(),
            "time": start_time,
            "price": float(row["price"]),
            "total_seats": int(row["total_seats"]),
            "booked_seats": int(row["booked_seats"]),
        }
        slot = (show_date, showtime["screen_number"], start_time)
        if showtime["showtime_id"] in showtime_ids:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} repeats a showtime_id.")
        if showtime["movie_id"] not in movie_ids:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} references an unknown movie_id.")
        if not showtime["screen_number"]:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} has no screen number.")
        if showtime["day_of_week"] != show_date.strftime("%A"):
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} has an incorrect day_of_week.")
        if slot in occupied_slots:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} overlaps a screen/time slot.")
        if showtime["price"] < 0 or showtime["total_seats"] < 0:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} has a negative price or capacity.")
        if not 0 <= showtime["booked_seats"] <= showtime["total_seats"]:
            raise ValueError(f"{SHOWTIMES_PATH.name}:{line_number} has invalid booked_seats.")
        showtime_ids.add(showtime["showtime_id"])
        occupied_slots.add(slot)
        slots_by_screen[(show_date, showtime["screen_number"])].append(start_time)
        showtimes.append(showtime)

    if showtime_ids != EXPECTED_IDS:
        raise ValueError("The showtimes file must contain each showtime_id from 1 through 120 exactly once.")
    if len(showtimes) != len(movies):
        raise ValueError("The supplied schedule must have one showtime for every movie.")

    for (_, screen_number), starts in slots_by_screen.items():
        sorted_starts = sorted(starts)
        for earlier, later in zip(sorted_starts, sorted_starts[1:]):
            earlier_minutes = earlier.hour * 60 + earlier.minute
            later_minutes = later.hour * 60 + later.minute
            if later_minutes - earlier_minutes < MIN_SCREEN_GAP_MINUTES:
                raise ValueError(
                    f"Screen {screen_number} has less than a 2.5-hour gap between showtimes."
                )

    return movies, showtimes


def _ensure_migration_table(connection: Any) -> None:
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(revision VARCHAR(100) PRIMARY KEY)"
    )


def _showtime_sql_rows(showtimes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **showtime,
            "date": showtime["date"].isoformat(),
            "time": showtime["time"].isoformat(),
        }
        for showtime in showtimes
    ]


def _remove_empty_migration_artifacts(connection: Any, table_names: set[str]) -> None:
    expected_columns = {
        "movies_normalized": {"movie_id", "title", "genre"},
        "showtimes": {
            "showtime_id", "movie_id", "date", "day_of_week", "screen_number",
            "time", "price", "total_seats", "booked_seats",
        },
        "bookings_normalized": {
            "id", "user_id", "showtime_id", "historical_movie_title",
            "customer_name", "seats", "total_amount", "status", "booked_at",
        },
    }
    for table_name in ("bookings_normalized", "showtimes", "movies_normalized"):
        if table_name not in table_names:
            continue
        columns = {
            column["name"]
            for column in inspect(connection).get_columns(table_name)
        }
        if columns != expected_columns[table_name]:
            raise RuntimeError(
                f"Cannot resume the legacy database migration: existing "
                f"{table_name} table has an unexpected schema."
            )
        row_count = connection.exec_driver_sql(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).scalar_one()
        if row_count:
            raise RuntimeError(
                f"Cannot resume the legacy database migration: existing "
                f"{table_name} table contains data."
            )
        connection.exec_driver_sql(f'DROP TABLE "{table_name}"')


def _copy_flat_schema_to_normalized(
    movies: list[dict[str, Any]],
    showtimes: list[dict[str, Any]],
) -> None:
    table_names = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            _remove_empty_migration_artifacts(connection, table_names)
            booking_rows: list[dict[str, Any]] = []
            if "bookings" in table_names:
                booking_rows = [
                    dict(row)
                    for row in connection.execute(text(
                        "SELECT b.id, b.user_id, b.customer_name, b.seats, "
                        "b.total_amount, b.status, b.booked_at, m.title AS historical_movie_title "
                        "FROM bookings AS b LEFT JOIN movies AS m ON m.id = b.movie_id "
                        "ORDER BY b.id"
                    )).mappings()
                ]

            connection.execute(text(
                "CREATE TABLE movies_normalized ("
                "movie_id INTEGER PRIMARY KEY, "
                "title VARCHAR(150) NOT NULL UNIQUE, "
                "genre VARCHAR(200) NOT NULL)"
            ))
            connection.execute(text(
                "CREATE TABLE showtimes ("
                "showtime_id INTEGER PRIMARY KEY, "
                "movie_id INTEGER NOT NULL REFERENCES movies_normalized(movie_id) ON DELETE RESTRICT, "
                "date DATE NOT NULL, "
                "day_of_week VARCHAR(9) NOT NULL, "
                "screen_number VARCHAR(30) NOT NULL, "
                "time TIME NOT NULL, "
                "price FLOAT NOT NULL CHECK(price >= 0), "
                "total_seats INTEGER NOT NULL CHECK(total_seats >= 0), "
                "booked_seats INTEGER NOT NULL "
                "CHECK(booked_seats >= 0 AND booked_seats <= total_seats), "
                "CONSTRAINT uq_showtime_screen_slot UNIQUE(date, screen_number, time))"
            ))
            connection.execute(text(
                "CREATE TABLE bookings_normalized ("
                "id INTEGER PRIMARY KEY, "
                "user_id VARCHAR(100) NOT NULL, "
                "showtime_id INTEGER REFERENCES showtimes(showtime_id) ON DELETE RESTRICT, "
                "historical_movie_title VARCHAR(150), "
                "customer_name VARCHAR(150) NOT NULL, "
                "seats INTEGER NOT NULL, "
                "total_amount FLOAT NOT NULL, "
                "status VARCHAR(30) NOT NULL, "
                "booked_at DATETIME NOT NULL, "
                "CONSTRAINT ck_booking_has_showtime_or_history "
                "CHECK(showtime_id IS NOT NULL OR historical_movie_title IS NOT NULL))"
            ))

            connection.execute(
                text("INSERT INTO movies_normalized (movie_id, title, genre) "
                     "VALUES (:movie_id, :title, :genre)"),
                movies,
            )
            connection.execute(
                text(
                    "INSERT INTO showtimes "
                    "(showtime_id, movie_id, date, day_of_week, screen_number, time, "
                    "price, total_seats, booked_seats) VALUES "
                    "(:showtime_id, :movie_id, :date, :day_of_week, :screen_number, "
                    ":time, :price, :total_seats, :booked_seats)"
                ),
                _showtime_sql_rows(showtimes),
            )
            if booking_rows:
                connection.execute(
                    text(
                        "INSERT INTO bookings_normalized "
                        "(id, user_id, showtime_id, historical_movie_title, customer_name, "
                        "seats, total_amount, status, booked_at) VALUES "
                        "(:id, :user_id, NULL, "
                        "COALESCE(:historical_movie_title, 'Legacy booking'), "
                        ":customer_name, :seats, :total_amount, :status, :booked_at)"
                    ),
                    booking_rows,
                )

            if "bookings" in table_names:
                connection.exec_driver_sql("DROP TABLE bookings")
            connection.exec_driver_sql("DROP TABLE movies")
            connection.exec_driver_sql("ALTER TABLE movies_normalized RENAME TO movies")
            connection.exec_driver_sql("ALTER TABLE bookings_normalized RENAME TO bookings")
            connection.exec_driver_sql(
                "CREATE INDEX ix_showtimes_movie_id ON showtimes (movie_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_showtimes_date ON showtimes (date)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_bookings_user_id ON bookings (user_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_bookings_showtime_id ON bookings (showtime_id)"
            )
            _ensure_migration_table(connection)
            connection.execute(
                text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
                {"revision": SCHEMA_REVISION},
            )
            connection.execute(
                text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
                {"revision": CATALOG_REVISION},
            )
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        except Exception:
            connection.rollback()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            raise


def _migrate_normalized_schema_if_needed() -> bool:
    table_names = set(inspect(engine).get_table_names())
    if "movies" not in table_names:
        return False
    columns = {column["name"] for column in inspect(engine).get_columns("movies")}
    if "show_time" not in columns and "price" not in columns:
        return False
    movies, showtimes = _read_normalized_data()
    _copy_flat_schema_to_normalized(movies, showtimes)
    return True


def _import_catalog_if_needed(
    movies: list[dict[str, Any]],
    showtimes: list[dict[str, Any]],
) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        imported = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE revision = :revision"),
            {"revision": CATALOG_REVISION},
        ).first()
        if imported:
            return

        movie_count = connection.scalar(text("SELECT COUNT(*) FROM movies"))
        showtime_count = connection.scalar(text("SELECT COUNT(*) FROM showtimes"))
        if movie_count or showtime_count:
            raise RuntimeError(
                "The database already contains normalized catalog data without a migration marker; "
                "refusing to overwrite it."
            )
        connection.execute(
            text("INSERT INTO movies (movie_id, title, genre) "
                 "VALUES (:movie_id, :title, :genre)"),
            movies,
        )
        connection.execute(
            text(
                "INSERT INTO showtimes "
                "(showtime_id, movie_id, date, day_of_week, screen_number, time, "
                "price, total_seats, booked_seats) VALUES "
                "(:showtime_id, :movie_id, :date, :day_of_week, :screen_number, "
                ":time, :price, :total_seats, :booked_seats)"
            ),
            _showtime_sql_rows(showtimes),
        )
        connection.execute(
            text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
            {"revision": SCHEMA_REVISION},
        )
        connection.execute(
            text("INSERT INTO schema_migrations (revision) VALUES (:revision)"),
            {"revision": CATALOG_REVISION},
        )


def _upgrade_persistent_schema() -> None:
    table_names = set(inspect(engine).get_table_names())
    if "bookings" in table_names:
        columns = {
            column["name"]
            for column in inspect(engine).get_columns("bookings")
        }
        with engine.begin() as connection:
            if "idempotency_key" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE bookings ADD COLUMN idempotency_key VARCHAR(64)"
                )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_bookings_idempotency_key "
                "ON bookings (idempotency_key)"
            )
    Base.metadata.create_all(engine)

def _upgrade_escalation_schema() -> None:
    table_names = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        if "escalations" in table_names:
            columns = {c["name"] for c in inspect(engine).get_columns("escalations")}
            additions = {
                "customer_name": "VARCHAR(150)",
                "customer_email": "VARCHAR(254)",
                "customer_phone": "VARCHAR(30)",
                "preferred_contact_method": "VARCHAR(10)",
                "contact_consent": "BOOLEAN NOT NULL DEFAULT 0",
                "booking_id": "INTEGER",
                "assigned_employee_id": "INTEGER",
                "slack_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
                "slack_message_ts": "VARCHAR(50)",
                "notification_error": "TEXT",
                "updated_at": "DATETIME",
            }
            for column, sql_type in additions.items():
                if column not in columns:
                    connection.exec_driver_sql(
                        f'ALTER TABLE escalations ADD COLUMN "{column}" {sql_type}'
                    )
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO schema_migrations (revision) "
            "VALUES (:revision)",
            {"revision": ESCALATION_SUPPORT_REVISION},
        )

def initialize_database() -> None:
    movies, showtimes = _read_normalized_data()
    _migrate_normalized_schema_if_needed()
    _upgrade_persistent_schema()
    _upgrade_escalation_schema()

    _import_catalog_if_needed(movies, showtimes)
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        connection.execute(
            text("INSERT OR IGNORE INTO schema_migrations (revision) VALUES (:revision)"),
            {"revision": BOOKING_IDEMPOTENCY_REVISION},
        )
