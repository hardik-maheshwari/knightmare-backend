from quart import Blueprint, jsonify
from app.logger_setup import get_logger
from app.common.response_utils import create_error_response, create_success_response

logger = get_logger(__name__)
main_bp = Blueprint("main", __name__)


@main_bp.route("/health", methods=["GET"])
def health_check():

    try:
        logger.info("Processing request for /health endpoint.")

        response_dict, status_code = create_success_response(data="ok")
        return jsonify(response_dict), status_code

    except Exception as error:
        logger.error(f"Error in /health endpoint: {error}", exc_info=True)

        response_dict, status_code = create_error_response("Internal Server Error", 500)
        return jsonify(response_dict), status_code
