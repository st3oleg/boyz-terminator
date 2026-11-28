FROM python:3.12-slim
WORKDIR /app
COPY hub/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hub/app.py hub/dashboard.html .
COPY schemas/hub-event-v1.schema.json ./schema.json
USER 10001:10001
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--max-request-body-size=65536", "--call", "app:create_app"]
