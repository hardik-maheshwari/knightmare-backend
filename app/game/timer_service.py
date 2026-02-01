from datetime import datetime, timezone
from app.game.models import Game, PlayerColor
from app.logger_setup import get_logger

logger = get_logger(__name__)

# Config: 3 Minutes
INITIAL_TIME_MS = 3 * 60 * 1000 

class TimerService:
    @staticmethod
    def apply_move_time(game: Game, player_color: PlayerColor) -> bool:
        """
        Subtracts the elapsed thinking time from the player's bank.
        Updates 'last_move_at' to NOW.
        
        Returns:
            True if time ran out (Flag Fall).
            False if move is valid and time remains.
        """
        now = datetime.now(timezone.utc)
        
        current_white_ms = game.white_time_ms if game.white_time_ms is not None else INITIAL_TIME_MS
        current_black_ms = game.black_time_ms if game.black_time_ms is not None else INITIAL_TIME_MS
        
        # 2. If no previous anchor (Start of game), just set anchor and return.
        if not game.last_move_at:
            game.last_move_at = now
            # Initialize DB fields if they were None
            game.white_time_ms = current_white_ms
            game.black_time_ms = current_black_ms
            return False

        # 3. Calculate Elapsed
        elapsed_delta = now - game.last_move_at
        elapsed_ms = int(elapsed_delta.total_seconds() * 1000)

        # 4. Deduct from the player who JUST moved
        is_flag_fall = False

        if player_color == PlayerColor.WHITE:
            current_white_ms -= elapsed_ms
            logger.debug(f"White spent {elapsed_ms}ms. Remaining: {current_white_ms}")
            
            if current_white_ms <= 0:
                current_white_ms = 0
                is_flag_fall = True
            
            # Save back to object
            game.white_time_ms = current_white_ms
            
        else:
            current_black_ms -= elapsed_ms
            logger.debug(f"Black spent {elapsed_ms}ms. Remaining: {current_black_ms}")
            
            if current_black_ms <= 0:
                current_black_ms = 0
                is_flag_fall = True
            
            # Save back to object
            game.black_time_ms = current_black_ms

        # 5. Update Anchor for the NEXT player
        game.last_move_at = now
        
        return is_flag_fall