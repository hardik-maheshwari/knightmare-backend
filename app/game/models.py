from typing import Optional
from sqlalchemy import BIGINT, ForeignKey, Enum, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..extensions import Base
from app.common.types import (
    int_pk,
    str_pk_10,
    str_10,
    str_100,
    optional_str_10,
    bool_false,
)
from app.common.mixins import TimestampMixin
import enum
import chess


# --- Enums ---
# These are specific to our domain, so they live here with the models.
class GameStatus(enum.Enum):
    WAITING_FOR_OPPONENT = "waiting_for_opponent"
    ACTIVE = "active"
    WHITE_WIN = "white_win"
    BLACK_WIN = "black_win"
    DRAW = "draw"
    ABANDONED = "abandoned"


class PlayerColor(enum.Enum):
    WHITE = "white"
    BLACK = "black"


class Game(Base, TimestampMixin):
    __tablename__ = "games"

    game_id: Mapped[str_pk_10]

    # Foreign keys are specific, so we define them directly.
    white_player_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("users.user_id", ondelete="SET NULL")
    )
    black_player_id: Mapped[Optional[int]] = mapped_column(
        BIGINT, ForeignKey("users.user_id", ondelete="SET NULL")
    )

    status: Mapped[GameStatus] = mapped_column(
        Enum(GameStatus), nullable=False, default=GameStatus.WAITING_FOR_OPPONENT
    )

    white_player = relationship("User", foreign_keys=[white_player_id])
    black_player = relationship("User", foreign_keys=[black_player_id])

    current_fen: Mapped[str_100] = mapped_column(
        VARCHAR(100),
        nullable=False,
        default=chess.STARTING_FEN,
        server_default=chess.STARTING_FEN,
    )

    def __repr__(self) -> str:
        return f"<Game game_id={self.game_id} status='{self.status.value}'>"


class Move(Base, TimestampMixin):
    __tablename__ = "moves"

    move_id: Mapped[int_pk]

    game_id: Mapped[str] = mapped_column(
        VARCHAR(10), ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False
    )

    move_number: Mapped[int] = mapped_column(BIGINT, nullable=False)
    player_color: Mapped[PlayerColor] = mapped_column(Enum(PlayerColor), nullable=False)
    move_notation: Mapped[str_10]
    board_fen_after_move: Mapped[str_100]
    is_check: Mapped[bool_false]
    is_checkmate: Mapped[bool_false]
    is_castling: Mapped[bool_false]
    captured_piece: Mapped[optional_str_10]

    def __repr__(self) -> str:
        return f"<Move move_id={self.move_id} game_id='{self.game_id}' move='{self.move_notation}'>"
