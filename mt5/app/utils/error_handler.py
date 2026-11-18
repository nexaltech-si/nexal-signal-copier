"""
Standardized error response handler for MT5 API.
"""
import logging
import traceback
from flask import jsonify
from typing import Optional, Dict, Any
from errors import MT5APIError

logger = logging.getLogger(__name__)


def format_error_response(
    error: Exception,
    status_code: int = 500,
    endpoint: Optional[str] = None,
    request_context: Optional[Dict[str, Any]] = None
):
    """
    Format error response with consistent structure.
    
    Args:
        error: The exception that occurred
        status_code: HTTP status code to return
        endpoint: The endpoint where the error occurred
        request_context: Request parameters and context for debugging
    
    Returns:
        Tuple of (jsonified response, status_code)
    """
    # If it's a custom MT5APIError, use its to_dict method
    if isinstance(error, MT5APIError):
        if endpoint:
            error.endpoint = endpoint
        if request_context:
            error.request_context.update(request_context)
        
        logger.error(
            "Error ID: %s | Endpoint: %s | Message: %s | MT5 Error: %s | Retcode: %s",
            error.error_id,
            error.endpoint,
            error.message,
            error.mt5_error,
            error.retcode
        )
        return jsonify(error.to_dict()), status_code
    
    # For generic exceptions, create a standardized response
    error_id = str(id(error))  # Simple ID for generic errors
    
    # Log full stack trace for unexpected errors
    logger.error(
        "Unexpected Error ID: %s | Endpoint: %s | Type: %s | Message: %s\nStack trace:\n%s",
        error_id,
        endpoint,
        type(error).__name__,
        str(error),
        traceback.format_exc()
    )
    
    response = {
        "error_id": error_id,
        "error": str(error) if str(error) else "Internal server error",
        "error_type": type(error).__name__,
        "timestamp": None  # Could add timestamp here if needed
    }
    
    if endpoint:
        response["endpoint"] = endpoint
    
    # For development/debugging, include more details
    if request_context:
        response["request_context"] = request_context
    
    return jsonify(response), status_code


def handle_mt5_error(
    result,
    operation: str,
    endpoint: Optional[str] = None,
    request_context: Optional[Dict[str, Any]] = None
):
    """
    Handle MT5 operation result and raise appropriate error if failed.
    
    Args:
        result: MT5 operation result (can be None or TradeResult)
        operation: Description of the operation that failed
        endpoint: The endpoint where the error occurred
        request_context: Request parameters for debugging
    
    Raises:
        OrderError: If MT5 operation failed
    """
    from constants import TRADE_OK_RETCODES
    if result is None or (hasattr(result, 'retcode') and result.retcode not in TRADE_OK_RETCODES):
        import MetaTrader5 as mt5
        ec, es = mt5.last_error()
        
        retcode = result.retcode if result and hasattr(result, 'retcode') else ec
        
        # Get official description from TRADE_RETCODE_DESCRIPTION
        from constants import build_constants
        _, TRADE_RETCODE_DESCRIPTION, _, _ = build_constants()
        mt5_error = TRADE_RETCODE_DESCRIPTION.get(retcode, es) if retcode else es
        if not mt5_error:
            mt5_error = result.comment if result and hasattr(result, 'comment') else "Unknown error"
        
        from errors import OrderError
        raise OrderError(
            message=f"{operation} failed",
            mt5_error=mt5_error,
            retcode=retcode,
            endpoint=endpoint,
            request_context=request_context
        )


def get_request_context(request, include_body: bool = False) -> Dict[str, Any]:
    """
    Extract request context for error logging.
    
    Args:
        request: Flask request object
        include_body: Whether to include request body (may contain sensitive data)
    
    Returns:
        Dictionary with request context
    """
    context = {
        "method": request.method,
        "path": request.path,
        "remote_addr": request.remote_addr
    }
    
    # Add query parameters
    if request.args:
        context["query_params"] = dict(request.args)
    
    # Add body if requested (be careful with sensitive data)
    if include_body and request.is_json:
        try:
            body = request.get_json()
            # Sanitize sensitive fields
            if body:
                sanitized = body.copy()
                for field in ['password', 'api_key', 'secret', 'token']:
                    if field in sanitized:
                        sanitized[field] = '***REDACTED***'
                context["body"] = sanitized
        except Exception:
            pass
    
    return context
