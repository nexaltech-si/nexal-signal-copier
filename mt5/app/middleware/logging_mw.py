import time
import logging
import uuid
from flask import request, g

logger = logging.getLogger("mt5.access")


def _sanitize_value(key: str, value: str) -> str:
    """Sanitize sensitive data in logs."""
    sensitive_keys = ['password', 'api_key', 'secret', 'token', 'authorization', 'x-api-key']
    if key.lower() in sensitive_keys:
        return '***REDACTED***'
    return value


def _sanitize_dict(data: dict) -> dict:
    """Sanitize sensitive keys in a dictionary."""
    if not data:
        return data
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = _sanitize_value(key, value)
        else:
            sanitized[key] = value
    return sanitized


def register(app):
    @app.before_request
    def start_timer():
        g.start = time.perf_counter()
        g.request_id = str(uuid.uuid4())

    @app.after_request
    def log_request(response):
        # Always set the correlation header (cheap)
        request_id = getattr(g, 'request_id', 'unknown')
        response.headers['X-Request-ID'] = request_id

        duration_ms = round((time.perf_counter() - g.start) * 1000, 2)
        status = response.status_code

        # Fast path: 2xx/3xx responses skip JSON body re-parsing entirely.
        # error_id is only meaningful on 4xx/5xx, where the error_handler set it.
        error_id = None
        if status >= 400 and response.is_json:
            try:
                import json
                data = json.loads(response.get_data(as_text=True))
                if isinstance(data, dict) and 'error_id' in data:
                    error_id = data['error_id']
            except Exception:
                pass

        log_data = {
            'request_id': request_id,
            'method': request.method,
            'path': request.path,
            'status': status,
            'duration_ms': duration_ms,
            'remote_addr': request.remote_addr,
        }
        if request.args:
            log_data['query_params'] = _sanitize_dict(dict(request.args))
        if error_id:
            log_data['error_id'] = error_id

        # Feed /metrics (it was never called, so /metrics always reported zeros). The route RULE is the
        # key, not the raw path, so random 404 probes cannot grow the table without bound.
        try:
            from routes.metrics import record_request, record_error
            rule = request.url_rule.rule if request.url_rule is not None else "(unmatched)"
            record_request(f"{request.method} {rule}", status, duration_ms / 1000.0)
            if status >= 500:
                record_error(rule, f"HTTP {status}")
        except Exception:
            logger.debug("metrics recording failed", exc_info=True)

        if status >= 500:
            logger.error("Request failed: %s", log_data)
        elif status >= 400:
            logger.warning("Request error: %s", log_data)
        else:
            logger.info("Request: %s", log_data)

        return response
