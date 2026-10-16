FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY campuspulse ./campuspulse
COPY web ./web
RUN useradd --create-home --uid 10001 campuspulse && mkdir /app/data && chown campuspulse /app/data
USER campuspulse
EXPOSE 8080
CMD ["sh", "-c", "exec python -m uvicorn campuspulse.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
