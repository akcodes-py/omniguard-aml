FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY db/ ./db/
ENV PYTHONPATH=/app/src
EXPOSE 8000
