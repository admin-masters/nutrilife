FROM python:3.11-slim

# WORKDIR /app
# ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# COPY requirements.txt requirements-dev.txt ./
# RUN pip install --upgrade pip \
#  && pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# COPY . .
# CMD ["gunicorn", "myapp.wsgi:application", "--bind", "0.0.0.0:8000"]   # or your entrypoint
# system deps for mysqlclient
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential default-libmysqlclient-dev pkg-config \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# copy only settings/apps at runtime via bind mount
