import config
from quart import Quart, g,request
from sqlalchemy.ext.asyncio import AsyncSession
from app.errors import register_error_handlers
from .extensions import AsyncSessionLocal, rate_limiter
from app.extensions import redis_client
from app.managers.game_manager import GameWebSocketManager
from app.pubsub.providers.redis_pubsub_provider import RedisPubSubProvider
from app.pubsub.providers.in_memory_provider import InMemoryPubSubProvider 
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
        if request.path == "/health":
            return
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
    from .game.ws_routes import ws_bp

    app.register_blueprint(cors(main_bp, allow_origin="*"))
    app.register_blueprint(cors(auth_bp, allow_origin="*"))
    app.register_blueprint(cors(game_bp, allow_origin="*"))

    app.register_blueprint(ws_bp)
    logger.debug("Registered 'ws_bp' (No CORS).")

    logger.debug("Initializing extensions (Rate Limiter)...")
    rate_limiter.init_app(app)
    logger.info("Rate limiter initialized successfully.")

    register_error_handlers(app)
    logger.debug("Custom error handler for RateLimitExceeded has been registered.")

    logger.info("Attaching ws manager")
    if config.USE_REDIS:
        logger.info("Using REDIS PubSub Provider")
        # redis_client comes from app.extensions (Real Redis)
        pubsub_provider = RedisPubSubProvider(redis_client) # type: ignore
    else:
        logger.info("Using IN-MEMORY PubSub Provider")
        pubsub_provider = InMemoryPubSubProvider()

    app.ws_manager = GameWebSocketManager(pubsub_provider)  # type: ignore

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

if __name__ == "__main__":
    app = create_app()
    app.run()
