FROM python:3.11-slim

WORKDIR /srv/glossify

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# SQLite file lives in a volume so data survives container restarts.
ENV DATABASE_URL=sqlite:////data/glossify.db
VOLUME ["/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
