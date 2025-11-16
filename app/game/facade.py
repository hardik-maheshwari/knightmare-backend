from typing import Dict, Any, List, Optional, Tuple

import chess
from app.auth.models import User
from app.common.utils import generate_game_id
from app.game.exceptions import (
    AlreadyInGameError,
    GameNotFoundError,
    GameNotJoinableError,
    MoveNotPossibleError,
    UserNotPlayerError,
)
from app.game.models import Game, GameStatus, Move, PlayerColor
from app.game.repository import GameRepository
from app.auth.repository import AuthRepository
from app.websocket_manager import WebSocketManager
from app.logger_setup import get_logger

logger = get_logger(__name__)


class GameFacade:
    def __init__(
        self,
        game_repo: GameRepository,
        auth_repo: AuthRepository,
        ws_manager: WebSocketManager,
    ):
        self.game_repo = game_repo
        self.auth_repo = auth_repo
        self.ws_manager = ws_manager

    async def create_game(self, creator: User) -> Game:
        """
        Orchestrates the creation of a new game.
        """
        logger.debug(f"FACADE: Creating a new game for user '{creator.username}'.")

        # 1. Business Logic: Generate a unique ID for the game.
        game_id = generate_game_id()

        # 2. Business Logic: Assign the creator's color.
        assigned_color = PlayerColor.WHITE

        # 3. Business Logic: Prepare the Game object based on rules.
        game_kwargs: Dict[str, Any] = {
            "game_id": game_id,
            "status": GameStatus.WAITING_FOR_OPPONENT,
        }
        if assigned_color == PlayerColor.WHITE:
            game_kwargs["white_player_id"] = creator.user_id
        else:
            game_kwargs["black_player_id"] = creator.user_id

        new_game = Game(**game_kwargs)

        # 4. Delegate Persistence: Tell the repository to save the fully-formed object.
        created_game = await self.game_repo.save_game(new_game)

        logger.info(
            f"FACADE: Successfully orchestrated creation of game '{created_game.game_id}'."
        )

        # 5. Return the persisted object.
        return created_game

    async def get_serialized_game_state(self, game_id: str) -> Dict[str, Any]:
        """
        Assembles the rich game state payload for WebSocket broadcasts.
        """
        # 1. Call the efficient repository method to get the game and its players.
        game = await self.game_repo.get_game_with_players(game_id)

        if not game:
            logger.warning(f"Failed to serialize state: Game '{game_id}' not found.")
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        # 2. Fetch the game's moves.
        moves = await self.game_repo.get_moves_for_game(game_id)

        # 3. Calculate board state from the moves.
        current_fen = (
            chess.STARTING_FEN if not moves else moves[-1].board_fen_after_move
        )
        board = chess.Board(current_fen)

        # 4. Prepare the player data dictionaries from the eagerly loaded objects.
        white_player_data = None
        if game.white_player:
            white_player_data = {
                "id": game.white_player.user_id,
                "username": game.white_player.username,
            }

        black_player_data = None
        if game.black_player:
            black_player_data = {
                "id": game.black_player.user_id,
                "username": game.black_player.username,
            }

        # 5. Assemble the final, clean payload.
        payload: Dict[str, Any] = {
            "type": "game_update",
            "data": {
                "game_id": game_id,
                # --- FIX: Directly use the prepared data dictionaries ---
                "white_player": white_player_data,
                "black_player": black_player_data,
                # --- End Fix ---
                "status": game.status.value,
                "current_fen": current_fen,
                "turn": "w" if board.turn == chess.WHITE else "b",
                "is_check": board.is_check(),
                "is_checkmate": board.is_checkmate(),
                "is_draw": board.is_stalemate()
                or board.is_insufficient_material()
                or board.is_seventyfive_moves()
                or board.is_fivefold_repetition(),
                "moves": [move.move_notation for move in moves],
            },
        }

        return payload

    async def join_game(self, game_id: str, joining_player: User) -> Game:
        game = await self.game_repo.get_game_by_id(game_id)

        if game is None:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        if game.status != GameStatus.WAITING_FOR_OPPONENT:
            raise GameNotJoinableError("Game cannot be joined")

        white_player_id = game.white_player_id
        black_player_id = game.black_player_id

        if joining_player.user_id in (white_player_id, black_player_id):
            raise AlreadyInGameError("You cannot play against yourself")

        if white_player_id is None:
            game.white_player_id = joining_player.user_id

        else:
            game.black_player_id = joining_player.user_id

        game.status = GameStatus.ACTIVE

        logger.info(
            f"User {joining_player.user_id} joined game {game_id}. Game is now ACTIVE."
        )

        rich_event_payload = await self.get_serialized_game_state(game_id)

        await self.ws_manager.publish_event(game_id, rich_event_payload)

        return game

    async def _get_and_validate_game_state(self, game_id: str, player: User) -> Game:
        """Fetches the game and runs pre-condition checks."""
        game = await self.game_repo.get_game_by_id(game_id)
        if not game:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")
        if game.status != GameStatus.ACTIVE:
            raise MoveNotPossibleError(
                f"Game is not active. Status: {game.status.value}"
            )
        if player.user_id not in (game.white_player_id, game.black_player_id):
            raise UserNotPlayerError("You are not a player in this game.")
        return game

    async def _load_board_from_history(
        self, game_id: str
    ) -> Tuple[chess.Board, Optional[Move]]:
        """Loads the chess.Board object from the latest move in the DB."""
        latest_move = await self.game_repo.get_latest_move(game_id)
        current_fen = (
            latest_move.board_fen_after_move if latest_move else chess.STARTING_FEN
        )
        logger.debug(f"Loading board with FEN: {current_fen}")
        return chess.Board(current_fen), latest_move

    def _validate_move_legality(
        self, board: chess.Board, move_uci: str, player: User, game: Game
    ) -> chess.Move:
        """Validates the move against game rules (turn order, legality)."""
        is_whites_turn = board.turn == chess.WHITE
        if (is_whites_turn and player.user_id != game.white_player_id) or (
            not is_whites_turn and player.user_id != game.black_player_id
        ):
            raise MoveNotPossibleError("It is not your turn.")

        try:
            move_object = chess.Move.from_uci(move_uci)

            if move_object not in board.legal_moves:
                raise chess.IllegalMoveError("Move is not in the list of legal moves.")
            return move_object
        except (ValueError, chess.IllegalMoveError) as e:
            logger.warning(f"Illegal move '{move_uci}' attempted. Reason: {e}")
            raise MoveNotPossibleError(f"Illegal move: {move_uci}")

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
        latest_move: Optional[Move],
        player: User,
        captured_piece_symbol: Optional[str],
    ) -> Move:
        """
        Creates and returns a new Move domain object based on the game state.
        This method does NOT save the object.
        """
        player_color = (
            PlayerColor.WHITE
            if player.user_id == game.white_player_id
            else PlayerColor.BLACK
        )

        if latest_move is None:
            new_move_number = 1
        elif latest_move.player_color == PlayerColor.BLACK:
            new_move_number = latest_move.move_number + 1
        else:
            new_move_number = latest_move.move_number

        new_fen = board.fen()
        # Data integrity check for a potential bug in the chess library's FEN generation on checkmate
        if board.is_checkmate() and ("k" not in new_fen or "K" not in new_fen):
            logger.warning(
                f"Invalid FEN '{new_fen}' on checkmate. Reverting FEN to pre-move state."
            )
            # Temporarily undo the move to get the last valid FEN
            board.pop()
            new_fen = board.fen()
            # Re-apply the move to keep the board state consistent for subsequent checks
            board.push(move_object)

        new_move = Move(
            game_id=game.game_id,
            move_number=new_move_number,
            player_color=player_color,
            move_notation=move_object.uci(),
            board_fen_after_move=new_fen,
            is_check=board.is_check(),
            is_checkmate=board.is_checkmate(),
            is_castling=board.is_castling(move_object),
            captured_piece=captured_piece_symbol,
        )

        logger.debug(f"Created new unsaved Move object: {new_move.move_notation}")
        return new_move

    async def make_move(self, game_id: str, player: User, move_uci: str) -> Move:
        """
        Orchestrates the entire process of making a move.
        It calls a series of private helpers to perform validation and state changes.
        """
        logger.debug(
            f"--- make_move orchestrator started for game '{game_id}' by user '{player.username}' ---"
        )

        game = await self._get_and_validate_game_state(game_id, player)

        board, latest_move = await self._load_board_from_history(game_id)

        move_object = self._validate_move_legality(board, move_uci, player, game)

        # 4. Apply the move to the board and update the game's overall status.
        captured_piece_symbol = self._get_captured_piece_symbol(board, move_object)
        board.push(move_object)
        self._update_game_status(game, board)

        # 5. Persist the new move to the database.
        new_move = self._create_new_move(
            game=game,
            board=board,
            move_object=move_object,
            latest_move=latest_move,
            player=player,
            captured_piece_symbol=captured_piece_symbol,
        )

        await self.game_repo.save_move(new_move)

        rich_event_payload = await self.get_serialized_game_state(game_id)

        await self.ws_manager.publish_event(game_id, rich_event_payload)

        logger.info(f"Move '{move_uci}' successfully processed for game '{game_id}'.")
        return new_move
    
    async def get_game_details(self, game_id: str, requesting_user: User) -> Dict[str, Any]:
        """
        Fetches the detailed history and state of a game, ensuring the
        requesting user has permission to view it.
        """
        logger.debug(f"FACADE: Getting details for game '{game_id}' for user '{requesting_user.username}'.")

        # 1. Fetch the game.
        game = await self.game_repo.get_game_by_id(game_id)
        if not game:
            raise GameNotFoundError(f"Game with ID {game_id} not found.")

        # 2. Business Logic: Authorize the user.
        is_player = (
            requesting_user.user_id == game.white_player_id
            or requesting_user.user_id == game.black_player_id
        )
        if not is_player:
            logger.warning(f"FORBIDDEN: User '{requesting_user.username}' attempted to access game '{game_id}'.")
            raise UserNotPlayerError("You are not authorized to view this game.")

        # 3. Fetch related data.
        moves = await self.game_repo.get_moves_for_game(game_id)

        # 4. Domain Logic: Calculate current board state.
        current_fen = chess.STARTING_FEN if not moves else moves[-1].board_fen_after_move
        board = chess.Board(current_fen)
        turn = "w" if board.turn == chess.WHITE else "b"

        # 5. DTO Assembly: Prepare the final payload.
        serializable_moves : List[Any] = [
            {
                "move_id": move.move_id,
                "move_number": move.move_number,
                "player_color": move.player_color.value,
                "move_notation": move.move_notation,
                "created_at": move.created_at.isoformat(),
            }
            for move in moves
        ]

        response_data: Dict[str, Any] = {
            "game_id": game_id,
            "white_player_id": game.white_player_id,
            "black_player_id": game.black_player_id,
            "status": game.status.value,
            "current_fen": current_fen,
            "turn": turn,
            "moves": serializable_moves,
        }

        return response_data
