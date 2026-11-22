"""Application entrypoint served with Waitress locally (debug off unless FLASK_DEBUG=true)."""

from __future__ import annotations

import logging
import os

from waitress import serve

from app import create_app

logger = logging.getLogger(__name__)
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    debug = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    if debug:
        app.run(host="0.0.0.0", port=port, debug=True)
    else:
        logger.info("Starting AI Citizen Assistant with Waitress on http://127.0.0.1:%d", port)
        serve(app, host="0.0.0.0", port=port, threads=6)
