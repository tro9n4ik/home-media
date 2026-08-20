from __future__ import annotations
from datetime import datetime, UTC
from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id:           Mapped[int]      = mapped_column(primary_key=True)
    username:     Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str]     = mapped_column(String(256))
    is_admin:     Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
