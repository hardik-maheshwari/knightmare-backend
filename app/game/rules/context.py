from dataclasses import dataclass
from typing import Optional
import chess
from app.game.models import Game, Move
from app.auth.models import User


@dataclass
class MoveContext:
    game: Game
    player: User
    move_uci: str
    board: chess.Board
    latest_move_db: Optional[Move]
    parsed_move: Optional[chess.Move] = None 
