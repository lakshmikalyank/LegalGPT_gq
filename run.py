"""
Application entry point for LegalGPT.

Local development:
    python run.py

Production (Render):
    Render starts the app via gunicorn (see render.yaml), so this
    __main__ block is not used in production — gunicorn imports the
    `app` object directly instead.
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
