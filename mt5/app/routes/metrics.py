from flask import Blueprint, jsonify, request
import os
import time
import threading
import logging
from collections import deque
from flasgger import swag_from
from middleware.auth import require_api_key
from swagger_specs import (
    get_metrics_spec, metrics_health_spec, reset_metrics_spec
)

metrics_bp = Blueprint("metrics", __name__)
logger = logging.getLogger(__name__)

# Configurable constants
MAX_REQUEST_TIMES = int(os.environ.get("METRICS_MAX_REQUEST_TIMES", 1000))

# Metrics storage
request_metrics = {
    "total_requests": 0,
    "requests_by_endpoint": {},
    "requests_by_status": {},
    "request_times": deque(maxlen=MAX_REQUEST_TIMES),   # O(1) append/evict (list.pop(0) was O(n))
    "errors": 0,                # all 4xx/5xx
    "server_errors": 0,         # 5xx only - what "health" is based on
    "start_time": None,
    "last_error": None
}

metrics_lock = threading.Lock()


def record_request(endpoint, status_code, duration):
    """Record request metrics."""
    with metrics_lock:
        request_metrics["total_requests"] += 1

        # Count by endpoint
        request_metrics["requests_by_endpoint"][endpoint] = \
            request_metrics["requests_by_endpoint"].get(endpoint, 0) + 1

        # Count by status
        status_str = str(status_code)
        request_metrics["requests_by_status"][status_str] = \
            request_metrics["requests_by_status"].get(status_str, 0) + 1

        # Track request times (bounded deque keeps the last MAX_REQUEST_TIMES)
        request_metrics["request_times"].append(duration)

        # Count errors
        if status_code >= 400:
            request_metrics["errors"] += 1
        if status_code >= 500:
            request_metrics["server_errors"] += 1


def record_error(endpoint, error):
    """Record error metrics."""
    with metrics_lock:
        request_metrics["last_error"] = {
            "endpoint": endpoint,
            "error": str(error),
            "error_type": type(error).__name__,
            "timestamp": time.time()
        }


@metrics_bp.route("/metrics", methods=["GET"])
@require_api_key
@swag_from(get_metrics_spec)
def get_metrics():
    with metrics_lock:
        times = list(request_metrics["request_times"])
        avg_time = sum(times) / len(times) if times else 0
        p50_time = sorted(times)[len(times)//2] if times else 0
        p95_time = sorted(times)[int(len(times)*0.95)] if len(times) >= 20 else 0
        
        error_rate = (request_metrics["errors"] / request_metrics["total_requests"] * 100) \
                    if request_metrics["total_requests"] > 0 else 0
        
        return jsonify({
            "total_requests": request_metrics["total_requests"],
            "errors": request_metrics["errors"],
            "error_rate": round(error_rate, 2),
            "avg_response_time_ms": round(avg_time * 1000, 2),
            "p50_response_time_ms": round(p50_time * 1000, 2),
            "p95_response_time_ms": round(p95_time * 1000, 2),
            "requests_by_endpoint": request_metrics["requests_by_endpoint"],
            "requests_by_status": request_metrics["requests_by_status"],
            "last_error": request_metrics["last_error"]
        })


@metrics_bp.route("/metrics/health", methods=["GET"])
@require_api_key
@swag_from(metrics_health_spec)
def metrics_health():
    with metrics_lock:
        total = request_metrics["total_requests"]
        errors = request_metrics["server_errors"]   # 4xx are caller mistakes (bad key, validation), not unhealthiness
        
        # Calculate health score
        if total == 0:
            health_score = 100
        else:
            error_rate = errors / total
            health_score = max(0, 100 - (error_rate * 100))
        
        status = "healthy" if health_score >= 90 else "degraded" if health_score >= 70 else "unhealthy"
        
        return jsonify({
            "status": status,
            "health_score": round(health_score, 2),
            "total_requests": total,
            "error_count": errors,
            "uptime_seconds": time.time() - (request_metrics.get("start_time") or time.time())
        })


@metrics_bp.route("/metrics/reset", methods=["POST"])
@require_api_key
@swag_from(reset_metrics_spec)
def reset_metrics():
    with metrics_lock:
        request_metrics["total_requests"] = 0
        request_metrics["requests_by_endpoint"] = {}
        request_metrics["requests_by_status"] = {}
        request_metrics["request_times"] = deque(maxlen=MAX_REQUEST_TIMES)
        request_metrics["errors"] = 0
        request_metrics["server_errors"] = 0
        request_metrics["last_error"] = None
        request_metrics["start_time"] = time.time()
    
    return jsonify({"message": "Metrics reset successfully"})


# Initialize start time
request_metrics["start_time"] = time.time()


