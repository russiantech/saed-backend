from django.middleware.gzip import GZipMiddleware


class JsonGZipMiddleware(GZipMiddleware):
    """gzip only buffered JSON/text API responses.

    Private media (video/PDF) is streamed with Range support and must never be re-encoded, and
    streaming/partial responses are skipped entirely.
    """

    COMPRESSIBLE = ("application/json", "text/html", "text/plain", "application/javascript", "text/css")

    def process_response(self, request, response):
        ctype = (response.get("Content-Type") or "").split(";")[0].strip().lower()
        if response.streaming or response.status_code != 200 or ctype not in self.COMPRESSIBLE:
            return response
        return super().process_response(request, response)
