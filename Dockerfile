FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd -m -u 10001 app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/media /data/protected_media && chown -R app /app /data
USER app
ENV MEDIA_ROOT=/data/media PRIVATE_MEDIA_ROOT=/data/protected_media DJANGO_DEBUG=0
EXPOSE 8002
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8002/api/health/',timeout=4)" || exit 1
CMD ["sh","-c","python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8002 --workers ${WEB_CONCURRENCY:-3} --timeout 120 --access-logfile -"]
