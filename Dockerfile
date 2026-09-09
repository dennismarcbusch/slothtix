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

# --preload lädt die App einmal im Master-Prozess, bevor die Worker
# geforkt werden - sonst würde jeder der 4 Worker beim eigenen Import
# unabhängig create_app() (und damit den Admin-Bootstrap) ausführen und
# es könnten mehrere Admin-User gleichzeitig angelegt werden.
CMD ["sh", "-c", "flask db upgrade && gunicorn --preload -w 4 -b 0.0.0.0:8000 wsgi:app"]
