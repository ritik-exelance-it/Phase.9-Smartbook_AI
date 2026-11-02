from collections.abc import Sequence
from datetime import date, datetime, time

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from middleware import require_permission, validate_positive_int
from models import (
    Booking,
    Conversation,
    ConversationMessage,
    Escalation,
    Movie,
    SessionLocal,
    Showtime,
    utc_now,
)

MAX_CONVERSATION_MESSAGE_LENGTH = 64_000


def _movie_matches_genre(movie: Movie, genre: str) -> bool:
    requested = genre.strip().casefold()
    if requested == "romantic":
        requested = "romance"
    movie_genres = {
        item.strip().casefold()
        for item in (movie.genre or "").split(",")
    }
    return requested in movie_genres


def movie_genres(role: str) -> set[str]:
    require_permission(role, "list_movies")
    with SessionLocal() as session:
        movies = session.scalars(select(Movie).order_by(Movie.movie_id)).all()
        return {
            genre.strip()
            for movie in movies
            for genre in (movie.genre or "").split(",")
            if genre.strip()
        }


def _showtime_record(showtime: Showtime) -> dict:
    return {
        "showtime_id": showtime.showtime_id,
        "date": showtime.date.isoformat(),
        "day_of_week": showtime.day_of_week,
        "screen_number": showtime.screen_number,
        "time": showtime.time.strftime("%H:%M"),
        "price_per_seat": showtime.price,
        "total_seats": showtime.total_seats,
        "booked_seats": showtime.booked_seats,
        "available_seats": showtime.available_seats,
    }


def _showtime_is_upcoming(showtime: Showtime, now: datetime | None = None) -> bool:
    current = now or datetime.now()
    return (
        showtime.date > current.date()
        or (
            showtime.date == current.date()
            and showtime.time > current.time().replace(second=0, microsecond=0)
        )
    )


def _movie_record(movie: Movie, showtimes: Sequence[Showtime]) -> dict:
    return {
        "movie_id": movie.movie_id,
        "title": movie.title,
        "genre": movie.genre,
        "showtimes": [_showtime_record(showtime) for showtime in showtimes],
    }


def _catalogue_records(
    session,
    genre: str | None,
    on_date: date | None,
) -> tuple[list[dict], int, int]:
    movies = session.scalars(select(Movie).order_by(Movie.movie_id)).all()
    scheduled_movies = []
    matching_catalogue_count = 0
    screening_count = 0
    for movie in movies:
        if genre and not _movie_matches_genre(movie, genre):
            continue
        matching_catalogue_count += 1
        query = select(Showtime).where(Showtime.movie_id == movie.movie_id)
        if on_date:
            query = query.where(Showtime.date == on_date)
        showtimes = session.scalars(query.order_by(Showtime.date, Showtime.time)).all()
        if on_date and not showtimes:
            continue
        screening_count += len(showtimes)
        scheduled_movies.append(_movie_record(movie, showtimes))
    return scheduled_movies, matching_catalogue_count, screening_count


def list_movies(
    role: str,
    genre: str | None = None,
    on_date: date | None = None,
) -> dict:
    require_permission(role, "list_movies")
    with SessionLocal() as session:
        movies, matching_count, screening_count = _catalogue_records(session, genre, on_date)
        return {
            "movies": movies,
            "count": len(movies),
            "catalogue_count": matching_count,
            "screening_count": screening_count,
            "genre_filter": genre,
            "date_filter": on_date.isoformat() if on_date else None,
        }


def list_available_movies(
    role: str,
    genre: str | None = None,
    on_date: date | None = None,
) -> dict:
    require_permission(role, "list_movies")
    with SessionLocal() as session:
        catalogue = session.scalars(select(Movie).order_by(Movie.movie_id)).all()
        matching_movies = [
            movie for movie in catalogue
            if genre is None or _movie_matches_genre(movie, genre)
        ]
        result = []
        matching_showtime_count = 0
        sold_out_count = 0
        available_screening_count = 0

        for movie in matching_movies:
            query = select(Showtime).where(Showtime.movie_id == movie.movie_id)
            if on_date:
                query = query.where(Showtime.date == on_date)
            showtimes = session.scalars(
                query.order_by(Showtime.date, Showtime.time)
            ).all()
            matching_showtime_count += len(showtimes)
            available_showtimes = [
                showtime for showtime in showtimes
                if showtime.available_seats > 0 and _showtime_is_upcoming(showtime)
            ]
            sold_out_count += sum(
                showtime.available_seats <= 0
                for showtime in showtimes
                if _showtime_is_upcoming(showtime)
            )
            available_screening_count += len(available_showtimes)
            if available_showtimes:
                result.append(_movie_record(movie, available_showtimes))

        return {
            "movies": result,
            "count": len(result),
            "available_screening_count": available_screening_count,
            "catalogue_count": len(catalogue),
            "matching_catalogue_count": len(matching_movies),
            "matching_showtime_count": matching_showtime_count,
            "sold_out_count": sold_out_count,
            "genre_filter": genre,
            "date_filter": on_date.isoformat() if on_date else None,
        }


def movie_details(
    role: str,
    movie_id: int | None = None,
    title: str | None = None,
    on_date: date | None = None,
) -> dict:
    require_permission(role, "movie_details")
    with SessionLocal() as session:
        if movie_id is not None:
            movie = session.get(Movie, movie_id)
        elif title:
            movie = session.scalar(
                select(Movie)
                .where(Movie.title.ilike(f"%{title.strip()}%"))
                .limit(1)
            )
        else:
            return {"error": "Please provide a movie title or movie ID."}
        if movie is None:
            return {"error": "I couldn't find that movie in the catalogue."}
        query = select(Showtime).where(Showtime.movie_id == movie.movie_id)
        if on_date:
            query = query.where(Showtime.date == on_date)
        showtimes = session.scalars(
            query.order_by(Showtime.date, Showtime.time)
        ).all()
        return {"movie": _movie_record(movie, showtimes)}


def create_booking(
    role: str,
    user_id: str,
    movie_id: int | None,
    movie_title: str | None,
    customer_name: str | None,
    seats: int | None,
    showtime_id: int | None = None,
    on_date: date | None = None,
    at_time: time | None = None,
    idempotency_key: str | None = None,
) -> dict:
    require_permission(role, "create_booking")
    seats = validate_positive_int(seats, "Seats")
    if not customer_name or not customer_name.strip():
        return {"error": "Please provide the name for the booking."}
    if not user_id or not user_id.strip():
        return {"error": "A customer identity is required to create a booking."}
    if showtime_id is None:
        return {"error": "Please select a specific screening before confirming a booking."}
    if idempotency_key is not None and (
        not idempotency_key.strip() or len(idempotency_key) > 64
    ):
        return {"error": "The booking confirmation token is invalid. Please start again."}

    def confirmed_booking(booking: Booking) -> dict:
        showtime = booking.showtime
        movie = showtime.movie if showtime else None
        return {
            "status": booking.status,
            "booking_id": booking.id,
            "movie": movie.title if movie else booking.historical_movie_title or "Unknown movie",
            "showtime_id": showtime.showtime_id if showtime else None,
            "date": showtime.date.isoformat() if showtime else None,
            "day_of_week": showtime.day_of_week if showtime else None,
            "screen_number": showtime.screen_number if showtime else None,
            "show_time": showtime.time.strftime("%H:%M") if showtime else None,
            "customer": booking.customer_name,
            "seats": booking.seats,
            "total_amount": booking.total_amount,
        }

    now = datetime.now()
    today = now.date()
    current_time = now.time().replace(second=0, microsecond=0)
    with SessionLocal() as session:
        try:
            if idempotency_key is not None:
                existing = session.scalar(
                    select(Booking).where(Booking.idempotency_key == idempotency_key)
                )
                if existing is not None:
                    if existing.user_id != user_id:
                        return {"error": "This booking request could not be verified for your account."}
                    return confirmed_booking(existing)

            if movie_id is not None:
                movie = session.get(Movie, movie_id)
            elif movie_title:
                movie = session.scalar(
                    select(Movie)
                    .where(Movie.title.ilike(movie_title.strip()))
                )
            else:
                return {"error": "Please provide a movie title or movie ID."}
            if movie is None:
                return {"error": "I couldn't find that movie in the catalogue."}

            screening = session.get(Showtime, showtime_id)
            if screening is None or screening.movie_id != movie.movie_id:
                return {"error": "That screening is no longer available. Please choose another screening."}
            if on_date is not None and screening.date != on_date:
                return {"error": "The selected screening no longer matches the booking details."}
            if at_time is not None and screening.time != at_time:
                return {"error": "The selected screening no longer matches the booking details."}

            conditions = [
                Showtime.showtime_id == showtime_id,
                Showtime.movie_id == movie.movie_id,
                or_(
                    Showtime.date > today,
                    and_(Showtime.date == today, Showtime.time > current_time),
                ),
                Showtime.total_seats - Showtime.booked_seats >= seats,
            ]
            if on_date is not None:
                conditions.append(Showtime.date == on_date)
            result = session.execute(
                update(Showtime)
                .where(*conditions)
                .values(booked_seats=Showtime.booked_seats + seats)
                .returning(Showtime.showtime_id)
            )
            if result.scalar_one_or_none() is None:
                screening = session.get(Showtime, showtime_id)
                if screening is None or screening.movie_id != movie.movie_id:
                    return {"error": "That screening is no longer available. Please choose another screening."}
                if not _showtime_is_upcoming(screening, now):
                    return {"error": "That screening has already started or ended. Please choose a future screening."}
                if screening.available_seats < seats:
                    return {
                        "error": (
                            f"Only {screening.available_seats} seat(s) remain for that screening. "
                            "Please choose fewer tickets or another screening."
                        )
                    }
                return {"error": "The selected screening no longer matches the booking details."}

            showtime = session.get(Showtime, showtime_id)
            if showtime is None:
                raise RuntimeError("The selected screening disappeared during booking.")
            booking = Booking(
                user_id=user_id,
                showtime_id=showtime.showtime_id,
                customer_name=customer_name.strip(),
                seats=seats,
                total_amount=round(seats * showtime.price, 2),
                status="confirmed",
                idempotency_key=idempotency_key,
            )
            session.add(booking)
            session.commit()
            session.refresh(booking)
            return confirmed_booking(booking)
        except IntegrityError:
            session.rollback()
            if idempotency_key is not None:
                existing = session.scalar(
                    select(Booking).where(Booking.idempotency_key == idempotency_key)
                )
                if existing is not None and existing.user_id == user_id:
                    return confirmed_booking(existing)
            return {"error": "The booking request conflicted with another update. Please retry once."}
        except SQLAlchemyError:
            session.rollback()
            return {
                "error": "The booking could not be saved because of a database error. "
                "No confirmation was created."
            }


def list_customer_bookings(
    role: str,
    user_id: str,
    period: str = "all",
) -> dict:
    require_permission(role, "list_own_bookings")
    if not user_id or not user_id.strip():
        return {"error": "A customer identity is required to retrieve bookings."}
    if period not in {"all", "upcoming", "past"}:
        raise ValueError("Booking period must be all, upcoming, or past.")
    now = datetime.now()
    with SessionLocal() as session:
        query = select(Booking).where(Booking.user_id == user_id)
        bookings = session.scalars(query.order_by(Booking.booked_at.desc(), Booking.id.desc())).all()
        records = []
        for booking in bookings:
            screening = booking.showtime
            is_upcoming = bool(screening and _showtime_is_upcoming(screening, now))
            if period == "upcoming" and not is_upcoming:
                continue
            if period == "past" and is_upcoming:
                continue
            movie = screening.movie if screening else None
            records.append({
                "booking_id": booking.id,
                "movie": movie.title if movie else booking.historical_movie_title or "Unknown movie",
                "date": screening.date.isoformat() if screening else None,
                "day_of_week": screening.day_of_week if screening else None,
                "show_time": screening.time.strftime("%H:%M") if screening else None,
                "screen_number": screening.screen_number if screening else None,
                "seats": booking.seats,
                "total_amount": booking.total_amount,
                "status": booking.status,
                "historical_record": screening is None,
            })
        return {"bookings": records, "count": len(records), "period": period}


def create_or_get_conversation(
    user_id: str,
    conversation_id: str,
    title: str = "New conversation",
) -> dict:
    if not user_id or not conversation_id:
        raise ValueError("A guest identity and conversation ID are required.")
    if len(user_id) > 100 or len(conversation_id) > 100:
        raise ValueError("The guest identity or conversation ID is too long.")
    with SessionLocal.begin() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is not None:
            if conversation.user_id != user_id:
                return {"error": "Conversation not found for this guest identity."}
            return {
                "conversation_id": conversation.conversation_id,
                "title": conversation.title,
            }
        conversation = Conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            title=(title.strip() or "New conversation")[:200],
        )
        session.add(conversation)
        session.flush()
        return {
            "conversation_id": conversation.conversation_id,
            "title": conversation.title,
        }


def list_user_conversations(user_id: str) -> list[dict]:
    if not user_id:
        return []
    with SessionLocal() as session:
        conversations = session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        ).all()
        return [
            {
                "conversation_id": item.conversation_id,
                "title": item.title,
                "updated_at": item.updated_at.isoformat(),
            }
            for item in conversations
        ]


def get_conversation_history(user_id: str, conversation_id: str) -> list[dict]:
    with SessionLocal() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            return []
        return [
            {"role": item.role, "content": item.content}
            for item in conversation.messages
        ]


def append_conversation_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("Conversation messages must have a user or assistant role.")
    if not content or len(content) > MAX_CONVERSATION_MESSAGE_LENGTH:
        raise ValueError(
            "Conversation messages must contain at most "
            f"{MAX_CONVERSATION_MESSAGE_LENGTH} characters."
        )
    with SessionLocal.begin() as session:
        conversation = session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise PermissionError("Conversation not found for this guest identity.")
        conversation.messages.append(
            ConversationMessage(role=role, content=content)
        )
        conversation.updated_at = utc_now()
        if role == "user" and conversation.title == "New conversation":
            title = " ".join(content.split())[:180]
            conversation.title = title or "New conversation"


def check_booking(role: str, user_id: str, booking_id: int | None) -> dict:
    require_permission(role, "check_own_booking")
    if booking_id is None:
        return {"error": "Please provide your booking ID."}
    with SessionLocal() as session:
        booking = session.get(Booking, booking_id)
        if booking is None or (role != "admin" and booking.user_id != user_id):
            return {"error": "Booking not found for your account."}
        showtime = booking.showtime
        movie = showtime.movie if showtime else None
        return {
            "booking_id": booking.id,
            "movie": movie.title if movie else booking.historical_movie_title or "Unknown movie",
            "date": showtime.date.isoformat() if showtime else None,
            "day_of_week": showtime.day_of_week if showtime else None,
            "show_time": showtime.time.strftime("%H:%M") if showtime else None,
            "screen_number": showtime.screen_number if showtime else None,
            "customer": booking.customer_name,
            "seats": booking.seats,
            "total_amount": booking.total_amount,
            "status": booking.status,
            "historical_record": showtime is None,
        }


def cancel_booking(role: str, user_id: str, booking_id: int | None) -> dict:
    require_permission(role, "cancel_own_booking")
    if booking_id is None:
        return {"error": "Please provide your booking ID."}
    with SessionLocal() as session:
        try:
            booking = session.get(Booking, booking_id)
            if booking is None or (role != "admin" and booking.user_id != user_id):
                return {"error": "Booking not found for your account."}
            if booking.status != "confirmed":
                return {"error": f"Booking #{booking.id} is already {booking.status.lower()}."}
            showtime = booking.showtime
            if showtime is None:
                return {
                    "error": "This historical booking has no linked showtime and cannot be cancelled online. "
                    "Please contact cinema support."
                }
            showtime.booked_seats = max(0, showtime.booked_seats - booking.seats)
            booking.status = "cancelled"
            session.commit()
            return {
                "status": "cancelled",
                "booking_id": booking.id,
                "refund_amount": booking.total_amount,
                "message": "The booking was cancelled successfully. Refund timing depends on the cinema's policy.",
            }
        except SQLAlchemyError:
            session.rollback()
            return {
                "error": "Cancellation failed because of a database error. Please try again or contact support."
            }


def create_escalation(
    user_id: str,
    conversation_id: str,
    reason: str,
    details: str = "",
    priority: str = "normal",
) -> dict:
    with SessionLocal() as session:
        record = Escalation(
            user_id=user_id,
            conversation_id=conversation_id,
            reason=reason[:300],
            details=details[:4000],
            priority=priority if priority in {"low", "normal", "high"} else "normal",
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return {
            "escalation_id": record.id,
            "status": record.status,
            "message": "I've created a request for human assistance.",
        }
