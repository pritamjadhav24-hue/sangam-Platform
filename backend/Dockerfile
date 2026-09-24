FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini main.py ./

# /app/data/sandboxes holds the department sandbox databases. Creating it
# here (owned by the runtime user) means a fresh named volume mounted on it
# inherits a writable directory instead of a root-owned one.
RUN addgroup --system sangam && adduser --system --ingroup sangam sangam \
    && mkdir -p /app/data/sandboxes \
    && chown -R sangam:sangam /app
USER sangam

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
