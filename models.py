from datetime import date, datetime, time, timezone

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy import event

DATABASE_URL = "sqlite:///./cinema.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Movie(Base):
    __tablename__ = "movies"

    movie_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)
    genre: Mapped[str] = mapped_column(String(200), nullable=False)
    showtimes: Mapped[list["Showtime"]] = relationship(back_populates="movie")


class Showtime(Base):
    __tablename__ = "showtimes"
    __table_args__ = (
        UniqueConstraint("date", "screen_number", "time", name="uq_showtime_screen_slot"),
        CheckConstraint("price >= 0", name="ck_showtime_price_nonnegative"),
        CheckConstraint("total_seats >= 0", name="ck_showtime_seats_nonnegative"),
        CheckConstraint(
            "booked_seats >= 0 AND booked_seats <= total_seats",
            name="ck_showtime_booked_seats_valid",
        ),
    )

    showtime_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.movie_id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    day_of_week: Mapped[str] = mapped_column(String(9), nullable=False)
    screen_number: Mapped[str] = mapped_column(String(30), nullable=False)
    time: Mapped[time] = mapped_column(Time, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    total_seats: Mapped[int] = mapped_column(Integer, nullable=False)
    booked_seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    movie: Mapped[Movie] = relationship(back_populates="showtimes")
    bookings: Mapped[list["Booking"]] = relationship(back_populates="showtime")

    @property
    def available_seats(self) -> int:
        return max(0, self.total_seats - self.booked_seats)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "showtime_id IS NOT NULL OR historical_movie_title IS NOT NULL",
            name="ck_booking_has_showtime_or_history",
        ),
        Index("uq_bookings_idempotency_key", "idempotency_key", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    showtime_id: Mapped[int | None] = mapped_column(
        ForeignKey("showtimes.showtime_id"),
        nullable=True,
        index=True,
    )
    historical_movie_title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(150), nullable=False)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="confirmed", nullable=False)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)

    showtime: Mapped[Showtime | None] = relationship(back_populates="bookings")


class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.id",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

class SupportEmployee(Base):
    __tablename__ = "support_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    team: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    max_open_tickets: Mapped[int | None] = mapped_column(Integer, nullable=True)

class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    customer_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    preferred_contact_method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contact_consent: Mapped[bool] = mapped_column(default=False, nullable=False)
    booking_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("support_employees.id"), nullable=True, index=True
    )
    slack_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    slack_message_ts: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    assigned_employee: Mapped[SupportEmployee | None] = relationship()


def init_db() -> None:
    Base.metadata.create_all(engine)
