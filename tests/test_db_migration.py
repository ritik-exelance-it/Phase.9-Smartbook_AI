import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sqlalchemy import create_engine, text

import db


class DatabaseMigrationTests(unittest.TestCase):
    def test_migration_serializes_showtimes_and_recovers_empty_staging_tables(self):
        movies, showtimes = db._read_normalized_data()
        with TemporaryDirectory() as temp_dir:
            engine = create_engine(f"sqlite:///{Path(temp_dir) / 'cinema.db'}")
            try:
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "CREATE TABLE movies ("
                        "id INTEGER PRIMARY KEY, title TEXT NOT NULL, genre TEXT NOT NULL, "
                        "show_time TEXT NOT NULL, price FLOAT NOT NULL, "
                        "total_seats INTEGER NOT NULL, booked_seats INTEGER NOT NULL, "
                        "is_active BOOLEAN NOT NULL DEFAULT 1)"
                    )
                    connection.exec_driver_sql(
                        "CREATE TABLE bookings ("
                        "id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, movie_id INTEGER NOT NULL, "
                        "customer_name TEXT NOT NULL, seats INTEGER NOT NULL, "
                        "total_amount FLOAT NOT NULL, status TEXT NOT NULL, booked_at DATETIME NOT NULL, "
                        "FOREIGN KEY(movie_id) REFERENCES movies(id))"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO movies "
                        "(id, title, genre, show_time, price, total_seats, booked_seats) "
                        "VALUES (121, 'Legacy movie', 'Drama', '10:00 AM', 100, 100, 2)"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO bookings VALUES "
                        "(7, 'test-user', 121, 'Test', 2, 200, 'confirmed', "
                        "'2026-10-01 10:00:00')"
                    )
                    connection.exec_driver_sql(
                        "CREATE TABLE movies_normalized "
                        "(movie_id INTEGER PRIMARY KEY, title VARCHAR(150) NOT NULL UNIQUE, "
                        "genre VARCHAR(200) NOT NULL)"
                    )
                    connection.exec_driver_sql(
                        "CREATE TABLE showtimes ("
                        "showtime_id INTEGER PRIMARY KEY, movie_id INTEGER NOT NULL "
                        "REFERENCES movies_normalized(movie_id), date DATE NOT NULL, "
                        "day_of_week VARCHAR(9) NOT NULL, screen_number VARCHAR(30) NOT NULL, "
                        "time TIME NOT NULL, price FLOAT NOT NULL, total_seats INTEGER NOT NULL, "
                        "booked_seats INTEGER NOT NULL)"
                    )
                    connection.exec_driver_sql(
                        "CREATE TABLE bookings_normalized ("
                        "id INTEGER PRIMARY KEY, user_id TEXT, showtime_id INTEGER, "
                        "historical_movie_title TEXT, customer_name TEXT, seats INTEGER, "
                        "total_amount FLOAT, status TEXT, booked_at DATETIME)"
                    )

                with patch.object(db, "engine", engine):
                    db._copy_flat_schema_to_normalized(movies, showtimes)
                    db._import_catalog_if_needed(movies, showtimes)

                with engine.connect() as connection:
                    self.assertEqual(
                        connection.execute(text("SELECT COUNT(*) FROM movies")).scalar_one(),
                        120,
                    )
                    self.assertEqual(
                        connection.execute(text("SELECT COUNT(*) FROM showtimes")).scalar_one(),
                        120,
                    )
                    self.assertEqual(
                        connection.execute(
                            text(
                                "SELECT date, time FROM showtimes WHERE showtime_id = 1"
                            )
                        ).one(),
                        ("2026-11-02", "10:00:00"),
                    )
                    self.assertEqual(
                        connection.execute(
                            text(
                                "SELECT historical_movie_title, showtime_id "
                                "FROM bookings WHERE id = 7"
                            )
                        ).one(),
                        ("Legacy movie", None),
                    )
                    self.assertEqual(
                        connection.exec_driver_sql("PRAGMA foreign_key_check").all(),
                        [],
                    )
            finally:
                engine.dispose()


if __name__ == "__main__":
    unittest.main()
