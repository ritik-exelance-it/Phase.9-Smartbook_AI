import unittest
from datetime import date, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import agent
import tools
from models import Base, Movie, Showtime


class _OfflineLLM:
    def invoke(self, prompt):
        raise AssertionError(f"Deterministic booking should not call the response model: {prompt}")


class BookingOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 'bookings.db'}"
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
        )
        with self.session_factory.begin() as session:
            movie = Movie(movie_id=1, title="Pyre", genre="Drama, Crime")
            session.add(movie)
            session.add(
                Showtime(
                    showtime_id=1,
                    movie_id=1,
                    date=date(2026, 11, 3),
                    day_of_week="Tuesday",
                    screen_number="Screen 1",
                    time=time(12, 30),
                    price=150,
                    total_seats=5,
                    booked_seats=3,
                )
            )
        self.session_patch = patch.object(
            tools,
            "SessionLocal",
            self.session_factory,
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_booking_ownership_capacity_and_cancellation(self):
        booking = tools.create_booking(
            "customer",
            "customer-a",
            None,
            "Pyre",
            "Asha",
            2,
            showtime_id=1,
        )
        self.assertEqual(booking["status"], "confirmed")

        full = tools.create_booking(
            "customer",
            "customer-a",
            None,
            "Pyre",
            "Asha",
            1,
            showtime_id=1,
        )
        self.assertIn("Only 0 seat(s) remain", full["error"])
        customer_bookings = tools.list_customer_bookings("customer", "customer-a")
        self.assertEqual(customer_bookings["count"], 1)
        self.assertEqual(
            customer_bookings["bookings"][0]["booking_id"],
            booking["booking_id"],
        )
        self.assertEqual(
            tools.list_customer_bookings("customer", "customer-b")["count"],
            0,
        )

        private_to_other_user = tools.check_booking(
            "customer",
            "customer-b",
            booking["booking_id"],
        )
        self.assertEqual(private_to_other_user["error"], "Booking not found for your account.")
        denied_cancel = tools.cancel_booking(
            "customer",
            "customer-b",
            booking["booking_id"],
        )
        self.assertEqual(denied_cancel["error"], "Booking not found for your account.")

        confirmed = tools.check_booking(
            "customer",
            "customer-a",
            booking["booking_id"],
        )
        self.assertEqual(confirmed["status"], "confirmed")
        cancelled = tools.cancel_booking(
            "customer",
            "customer-a",
            booking["booking_id"],
        )
        self.assertEqual(cancelled["status"], "cancelled")
        repeated_cancel = tools.cancel_booking(
            "customer",
            "customer-a",
            booking["booking_id"],
        )
        self.assertIn("already cancelled", repeated_cancel["error"])

        with self.session_factory() as session:
            showtime = session.get(Showtime, 1)
            if showtime is None:
                self.fail("The scheduled showtime should remain in the database.")
            self.assertEqual(showtime.booked_seats, 3)
            self.assertEqual(showtime.available_seats, 2)

    def test_invalid_roles_cannot_book_or_cancel(self):
        with self.assertRaises(PermissionError):
            tools.create_booking(
                "support_agent",
                "support-user",
                None,
                "Pyre",
                "Asha",
                1,
                showtime_id=1,
            )
        with self.assertRaises(PermissionError):
            tools.cancel_booking("support_agent", "support-user", 1)

    def test_booking_matches_legacy_sqlite_time_without_fractional_seconds(self):
        on_date = date.today() + timedelta(days=7)
        with self.session_factory.begin() as session:
            screening = session.get(Showtime, 1)
            if screening is None:
                self.fail("The scheduled showtime should remain in the database.")
            screening.date = on_date
            screening.day_of_week = on_date.strftime("%A")
            session.execute(
                text("UPDATE showtimes SET time = '12:30:00' WHERE showtime_id = 1")
            )

        booking = tools.create_booking(
            "customer",
            "customer-a",
            1,
            "Pyre",
            "Asha",
            1,
            showtime_id=1,
            on_date=on_date,
            at_time=time(12, 30),
        )

        self.assertEqual(booking["status"], "confirmed")
        self.assertEqual(booking["showtime_id"], 1)

    def test_long_movie_lists_persist_in_conversation_history(self):
        user_id = "catalogue-history-user"
        conversation_id = f"catalogue-{uuid4()}"
        tools.create_or_get_conversation(user_id, conversation_id)
        movie_list = "\n".join(
            f"{number}. Movie {number}: Drama, 12:30, 150 per seat"
            for number in range(1, 121)
        )

        tools.append_conversation_message(
            user_id,
            conversation_id,
            "assistant",
            movie_list,
        )

        history = tools.get_conversation_history(user_id, conversation_id)
        self.assertEqual(history, [{"role": "assistant", "content": movie_list}])

    def test_agent_books_the_screening_selected_from_multiple_options(self):
        with self.session_factory.begin() as session:
            session.add(
                Showtime(
                    showtime_id=2,
                    movie_id=1,
                    date=date(2026, 11, 3),
                    day_of_week="Tuesday",
                    screen_number="Screen 1",
                    time=time(15, 30),
                    price=150,
                    total_seats=5,
                    booked_seats=1,
                )
            )

        thread_id = f"booking-options-{uuid4()}"
        with patch("agent.llm", _OfflineLLM()):
            first = agent.agent.invoke(
                {
                    "user_message": "Book two tickets for Pyre under the name Sam",
                    "user_id": "customer-a",
                    "role": "customer",
                    "conversation_id": thread_id,
                },
                config={"configurable": {"thread_id": thread_id}},
            )
            second = agent.agent.invoke(
                {
                    "user_message": "option 2",
                    "user_id": "customer-a",
                    "role": "customer",
                    "conversation_id": thread_id,
                },
                config={"configurable": {"thread_id": thread_id}},
            )
            with self.session_factory() as session:
                self.assertEqual(session.query(tools.Booking).count(), 0)
            third = agent.agent.invoke(
                {
                    "user_message": "yes",
                    "user_id": "customer-a",
                    "role": "customer",
                    "conversation_id": thread_id,
                },
                config={"configurable": {"thread_id": thread_id}},
            )

        self.assertIn("1. Tuesday 2026-11-03 at 12:30", first["response"])
        self.assertIn("2. Tuesday 2026-11-03 at 15:30", first["response"])
        self.assertIn("Please confirm this booking", second["response"])
        self.assertIn("Booking confirmed:", third["response"])
        with self.session_factory() as session:
            bookings = session.query(tools.Booking).all()
            self.assertEqual(len(bookings), 1)
            self.assertEqual(bookings[0].showtime_id, 2)
            showtime = session.get(Showtime, 2)
            if showtime is None:
                self.fail("The selected showtime should remain in the database.")
            self.assertEqual(showtime.booked_seats, 3)


if __name__ == "__main__":
    unittest.main()
