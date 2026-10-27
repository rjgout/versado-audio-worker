FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
COPY app ./app
USER 10001:10001
EXPOSE 5006
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5006/health',timeout=3)" || exit 1
CMD ["gunicorn", "--workers", "1", "--threads", "8", "--bind", "0.0.0.0:5006", "--timeout", "60", "app.server:app"]
