from quart import Quart, Response, g, jsonify, request
from quart_rate_limiter import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from .extensions import AsyncSessionLocal, rate_limiter
from app.common.response_utils import create_error_response
from app.websocket_manager import WebSocketManager
import config
from app.logger_setup import get_logger
from quart_cors import cors  # type: ignore


logger = get_logger(__name__)


def create_app():
    """
    Application factory for the Quart app.
    """
    logger.info("--- Creating new Quart application instance ---")
    app = Quart(__name__)

    # 1. Load Configuration
    logger.debug("Loading configuration from config.py object.")
    app.config.from_object(config)

    @app.before_request
    async def open_db_session():  # type: ignore
        g.session = AsyncSessionLocal()
        logger.info("DB session opened")

    @app.teardown_appcontext
    async def close_db_session(exception=None):  # type: ignore
        session: AsyncSession | None = g.pop("session", None)

        if session is None:
            logger.debug("Session was none")
        else:
            if exception:
                logger.info(f"Rolliing back transaction due to exception {exception}")
                await session.rollback()
            else:
                logger.info("Commiting transaction")
                await session.commit()
            await session.close()
        logger.info("--- DB Session Closed ---")

    # 2. Register Blueprints
    logger.debug("Registering blueprints...")

    from main_routes import main_bp
    from .auth.routes import auth_bp
    from .game.routes import game_bp

    app.register_blueprint(main_bp)
    logger.debug("Registered 'main_bp'.")

    app.register_blueprint(auth_bp)
    logger.debug("Registered 'auth_bp'.")

    app.register_blueprint(game_bp)
    logger.debug("Registered 'game_bp'.")

    logger.debug("Initializing extensions (Rate Limiter)...")
    rate_limiter.init_app(app)
    logger.info("Rate limiter initialized successfully.")

    # --- Register a custom error handler for rate limit exceeded ---
    @app.errorhandler(RateLimitExceeded)
    async def handle_rate_limit_exceeded(e: RateLimitExceeded) -> tuple[Response, int]:  # type: ignore
        """
        Custom handler for when a rate limit is exceeded.
        This function is registered with Quart and will be called automatically.
        """
        logger.warning(
            f"Rate limit exceeded for request: {request.method} {request.path}. "
            f"Client will need to wait {e.retry_after} seconds."
        )

        response_dict, status_code = create_error_response(
            f"Rate limit exceeded. Try again in {e.retry_after} seconds.", 429
        )

        logger.debug(f"Returning 429 Too Many Requests error response.")
        return jsonify(response_dict), status_code

    logger.debug("Custom error handler for RateLimitExceeded has been registered.")

    logger.info("Attaching ws manager")
    app.ws_manager = WebSocketManager()  # type: ignore

    @app.before_serving
    async def start_background_tasks():  # type: ignore
        """
        This function runs once when the app is ready to start serving.
        """
        logger.info("--- Starting background tasks... ---")
        # Get the manager instance from the app and call its startup method
        await app.ws_manager.startup()  # type: ignore

    logger.info("--- Application creation complete. ---")
    # app = cors(app, allow_origin="*")
    return app
