from quart import Quart, g
from sqlalchemy.ext.asyncio import AsyncSession
from app.errors import register_error_handlers
from .extensions import AsyncSessionLocal, rate_limiter
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
    async def open_db_session():
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

    register_error_handlers(app)
    logger.debug("Custom error handler for RateLimitExceeded has been registered.")

    logger.info("Attaching ws manager")
    app.ws_manager = WebSocketManager()

    @app.before_serving
    async def start_background_tasks():
        """
        This function runs once when the app is ready to start serving.
        """
        logger.info("--- Starting background tasks... ---")
        # Get the manager instance from the app and call its startup method
        await app.ws_manager.startup()  # type: ignore

    logger.info("--- Application creation complete. ---")
    # app = cors(app, allow_origin="*")
    return app
