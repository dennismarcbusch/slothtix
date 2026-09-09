FROM python:3.12-slim

WORKDIR /app
ENV FLASK_APP=wsgi.py \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p instance

EXPOSE 8000

CMD ["sh", "-c", "flask db upgrade && gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app"]
