"""
Custom error classes for MT5 API with detailed error information.
"""
import uuid
from datetime import datetime
from typing import Optional, Dict, Any
import pytz

UTC = pytz.utc


class MT5APIError(Exception):
    """Base exception for MT5 API errors."""
    
    def __init__(
        self,
        message: str,
        mt5_error: Optional[str] = None,
        retcode: Optional[int] = None,
        suggestion: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        self.error_id = str(uuid.uuid4())
        self.message = message
        self.mt5_error = mt5_error
        self.retcode = retcode
        self.suggestion = suggestion
        self.endpoint = endpoint
        self.request_context = request_context or {}
        self.timestamp = datetime.now(UTC).isoformat()
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for JSON response."""
        result = {
            "error_id": self.error_id,
            "error": self.message,
            "timestamp": self.timestamp
        }
        if self.mt5_error:
            result["mt5_error"] = self.mt5_error
        if self.retcode is not None:
            result["retcode"] = self.retcode
        if self.suggestion:
            result["suggestion"] = self.suggestion
        if self.endpoint:
            result["endpoint"] = self.endpoint
        if self.request_context:
            result["request_context"] = self.request_context
        return result


class ValidationError(MT5APIError):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        suggestion = f"Check the '{field}' field" if field else "Check request parameters"
        super().__init__(
            message=message,
            suggestion=suggestion,
            endpoint=endpoint,
            request_context=request_context
        )
        self.field = field


class MT5ConnectionError(MT5APIError):
    """Raised when MT5 connection fails or is unavailable."""
    
    def __init__(
        self,
        message: str = "MT5 connection failed",
        mt5_error: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        suggestion = "Ensure MT5 terminal is running and connected"
        super().__init__(
            message=message,
            mt5_error=mt5_error,
            suggestion=suggestion,
            endpoint=endpoint,
            request_context=request_context
        )


class OrderError(MT5APIError):
    """Raised when order/position operations fail."""
    
    def __init__(
        self,
        message: str,
        mt5_error: Optional[str] = None,
        retcode: Optional[int] = None,
        endpoint: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        suggestion = "Check order parameters, account balance, and market conditions"
        super().__init__(
            message=message,
            mt5_error=mt5_error,
            retcode=retcode,
            suggestion=suggestion,
            endpoint=endpoint,
            request_context=request_context
        )


class DataError(MT5APIError):
    """Raised when data fetching operations fail."""
    
    def __init__(
        self,
        message: str,
        mt5_error: Optional[str] = None,
        endpoint: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None
    ):
        suggestion = "Check symbol name, timeframe, and date range parameters"
        super().__init__(
            message=message,
            mt5_error=mt5_error,
            suggestion=suggestion,
            endpoint=endpoint,
            request_context=request_context
        )
