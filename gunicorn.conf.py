"""Single-service production settings for Railway or a local container."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "gthread"
threads = 4
timeout = 300
graceful_timeout = 30
# Log failures without logging request bodies, keys, or query strings.
errorlog = "-"
accesslog = None
