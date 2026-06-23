# import logging
# import time

# logger = logging.getLogger("saed.requests")


# class RequestLogMiddleware:
#     """Log every request/response for debugging."""
    
#     def __init__(self, get_response):
#         self.get_response = get_response
    
#     def __call__(self, request):
#         start_time = time.time()
        
#         logger.info(
#             f"→ {request.method} {request.path}",
#             extra={
#                 "method": request.method,
#                 "path": request.path,
#                 "content_type": request.content_type,
#                 "content_length": request.META.get("CONTENT_LENGTH", 0),
#                 "remote_addr": request.META.get("REMOTE_ADDR"),
#                 "user_agent": request.META.get("HTTP_USER_AGENT", "")[:100],
#                 "user_id": request.user.id if request.user.is_authenticated else None,
#             }
#         )
        
#         response = self.get_response(request)
#         duration = (time.time() - start_time) * 1000
        
#         log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
#         logger.log(
#             log_level,
#             f"← {request.method} {request.path} [{response.status_code}] {duration:.1f}ms",
#             extra={
#                 "method": request.method,
#                 "path": request.path,
#                 "status_code": response.status_code,
#                 "duration_ms": round(duration, 2),
#                 "user_id": request.user.id if request.user.is_authenticated else None,
#             }
#         )
        
#         return response






# v2 - unicode -> replaced:
import logging
import time

logger = logging.getLogger("saed.requests")


class RequestLogMiddleware:
    """Log every request/response for debugging."""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        start_time = time.time()
        
        # Log incoming request (use ASCII arrows)
        logger.info(
            "-> %s %s",
            request.method,
            request.path,
            extra={
                "method": request.method,
                "path": request.path,
                "content_type": request.content_type,
                "content_length": request.META.get("CONTENT_LENGTH", 0),
                "remote_addr": request.META.get("REMOTE_ADDR"),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:100],
                "user_id": request.user.id if request.user and request.user.is_authenticated else None,
            }
        )
        
        response = self.get_response(request)
        duration = (time.time() - start_time) * 1000
        
        # Log response
        log_level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            log_level,
            "<- %s %s [%s] %.1fms",
            request.method,
            request.path,
            response.status_code,
            duration,
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round(duration, 2),
                "user_id": request.user.id if request.user and request.user.is_authenticated else None,
            }
        )
        
        return response

