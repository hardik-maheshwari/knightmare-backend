import chess
from app.game.commands.base import IGameCommand
from app.game.exceptions import TimeoutLossError
from app.game.repository import GameRepository
from app.game.rules.context import MoveContext
from app.game.rules.handlers import (
    GameActiveRule,
    LegalMoveRule,
    PlayerAuthRule,
    TurnRule,
)
from app.game.serializers import build_websocket_payload
from app.game.timer_service import TimerService
from app.managers.publisher import EventPublisher
from app.game.models import Game, GameStatus, Move, PlayerColor
from app.auth.models import User
from typing import Optional, Tuple, cast
from app.logger_setup import get_logger

logger = get_logger(__name__)


class MakeMoveCommand(IGameCommand):
    def __init__(
        self,
        game: Game,
        player: User,
        move_uci: str,
        game_repo: GameRepository,
        ws_manager: EventPublisher,
    ):
        self.game = game
        self.player = player
        self.move_uci = move_uci
        self.game_repo = game_repo
        self.ws_manager = ws_manager
        self.game_id = game.game_id

        # Memento: (FEN, Status)
        # We capture this NOW, before any logic runs.
        self._snapshot = (game.current_fen, game.status)

        self._created_move: Optional[Move] = None

    async def _load_board_from_history(
        self, game_id: str
    ) -> Tuple[chess.Board, Optional[Move]]:
        """
        Rebuilds the board by replaying every move of the game.

        A FEN is only a snapshot: a board built from it has no move stack, so
        python-chess can't detect repetition draws. Replaying gives the board
        its full history (a few hundred moves at most, ~1ms).

        games.current_fen is kept as a denormalized copy for broadcasts and
        timeout checks; a mismatch is logged and the replayed history wins.
        """
        moves = await self.game_repo.get_moves_for_game(game_id)
        board = chess.Board()
        for move in moves:
            board.push_uci(move.move_notation)

        if board.fen() != self.game.current_fen:
            logger.error(
                f"current_fen drift in game '{game_id}': column has "
                f"'{self.game.current_fen}', move history gives '{board.fen()}'. "
                f"Using the move history."
            )

        latest_move = moves[-1] if moves else None
        logger.debug(f"Replayed {len(moves)} moves. FEN: {board.fen()}")
        return board, latest_move

    def _get_captured_piece_symbol(
        self, board: chess.Board, move: chess.Move
    ) -> Optional[str]:
        """Determines if a move is a capture and returns the captured piece's symbol."""
        if board.is_capture(move):
            if board.is_en_passant(move):
                return "p" if board.turn == chess.WHITE else "P"

            captured_piece = board.piece_at(move.to_square)
            if captured_piece:
                return captured_piece.symbol()
        return None

    def _update_game_status(self, game: Game, board: chess.Board) -> None:
        """Checks for game-ending conditions and updates the game status."""
        if board.is_checkmate():
            game.status = (
                GameStatus.WHITE_WIN
                if board.turn == chess.BLACK
                else GameStatus.BLACK_WIN
            )
            logger.info(
                f"Checkmate detected. Game {game.game_id} status set to {game.status.value}"
            )
        elif (
            board.is_stalemate()
            or board.is_insufficient_material()
            or board.is_seventyfive_moves()
            or board.is_fivefold_repetition()
        ):
            game.status = GameStatus.DRAW
            logger.info(
                f"Draw detected. Game {game.game_id} status set to {game.status.value}"
            )

    def _create_new_move(
        self,
        game: Game,
        board: chess.Board,
        move_object: chess.Move,
        move_number: int,
        player_color: PlayerColor,
        captured_piece_symbol: Optional[str],
    ) -> Move:
        """
        Creates and returns a new Move domain object. `board` is the position
        AFTER the move. This method does NOT save the object.
        """
        new_move = Move(
            game_id=game.game_id,
            move_number=move_number,
            player_color=player_color,
            move_notation=move_object.uci(),
            board_fen_after_move=board.fen(),
            is_check=board.is_check(),
            is_checkmate=board.is_checkmate(),
            is_castling=board.is_castling(move_object),
            captured_piece=captured_piece_symbol,
        )

        logger.debug(f"Created new unsaved Move object: {new_move.move_notation}")
        return new_move

    async def execute(self) -> Move:
        # 1. Load the board (full history replay; the game row is already locked)
        board, latest_move = await self._load_board_from_history(self.game_id)

        # 2. Build Context
        move_context = MoveContext(
            game=self.game,
            player=self.player,
            move_uci=self.move_uci,
            board=board,
            latest_move_db=latest_move,
        )

        # 3. Validation (Reusing Chain from Facade)
        validation_chain = GameActiveRule()
        validation_chain.set_next(PlayerAuthRule()).set_next(TurnRule()).set_next(
            LegalMoveRule()
        )
        validation_chain.check(move_context)

        mover_color = (
            PlayerColor.WHITE
            if self.player.user_id == self.game.white_player_id
            else PlayerColor.BLACK
        )

        # Calculate deduction
        is_flag_fall = TimerService.apply_move_time(self.game, mover_color)

        if is_flag_fall:
            logger.info(f"FLAG FALL! Player {mover_color} ran out of time.")
            # 1. Update Status
            self.game.status = (
                GameStatus.BLACK_WIN
                if mover_color == PlayerColor.WHITE
                else GameStatus.WHITE_WIN
            )

            # 2. Persist Game State (Game Over)
            await self.game_repo.save_game(self.game)

            
            ws_payload = build_websocket_payload(
                self.game, latest_move
            )  # Pass latest_move (no new move made)
            # Add specific flag fall data
            ws_payload["data"]["game_over_reason"] = "timeout"
            await self.ws_manager.publish_event(self.game_id, ws_payload)

            # 4. Stop execution (Do not create a move)
            raise TimeoutLossError("Time ran out!")
            
        # Capture the parsed move object from the context (populated by LegalMoveRule)
        self._move_object = cast(chess.Move, move_context.parsed_move)

        captured_piece_symbol = self._get_captured_piece_symbol(
            board, self._move_object
        )
        # Read from the board BEFORE pushing: the full-move number of this move
        # (TurnRule already guaranteed mover_color == side to move).
        move_number = board.fullmove_number

        board.push(self._move_object)  # Update board state
        self._update_game_status(self.game, board)  # Check for checkmate/draw
        self.game.current_fen = board.fen()

        # A pending takeback offer referred to the previous position; a new
        # move makes it stale (accepting it would undo THIS move instead).
        self.game.takeback_requester_id = None

        # 6. Persist
        new_move = self._create_new_move(
            game=self.game,
            board=board,
            move_object=self._move_object,
            move_number=move_number,
            player_color=mover_color,
            captured_piece_symbol=captured_piece_symbol,
        )

        self._created_move = await self.game_repo.save_move(new_move)

        # 7. Broadcast
        ws_payload = build_websocket_payload(self.game, new_move)

        await self.ws_manager.publish_event(self.game_id, ws_payload)

        logger.info(
            f"Move '{self.move_uci}' successfully processed for game '{self.game_id}'."
        )
        return new_move
