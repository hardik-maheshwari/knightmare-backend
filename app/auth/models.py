# backend/app/auth/models.py

from sqlalchemy.orm import Mapped
from ..extensions import Base
from app.common.types import (
    int_pk,
    str_50,
    str_255,
)
from app.common.mixins import TimestampMixin


# --- Models ---
class User(Base, TimestampMixin):
    __tablename__ = "users"

    user_id: Mapped[int_pk]
    username: Mapped[str_50]
    password_hash: Mapped[str_255]

    def __repr__(self) -> str:
        return f"<User user_id={self.user_id} username='{self.username}'>"
