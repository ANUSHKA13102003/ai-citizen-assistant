"""Application entrypoint served with Flask dev reloader (FLASK_DEBUG=1) or Waitress."""

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
    url = f"http://127.0.0.1:{port}"
    if debug:
        print(f"AI Citizen Assistant (dev reloader) running at {url}", flush=True)
        app.run(host="0.0.0.0", port=port, debug=True, use_reloader=True)
    else:
        print(f"AI Citizen Assistant (Waitress) running at {url}", flush=True)
        logger.info("Starting AI Citizen Assistant with Waitress on %s", url)
        serve(app, host="0.0.0.0", port=port, threads=6)
