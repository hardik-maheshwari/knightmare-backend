FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr (Logs show up faster)
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y \
  build-essential \
  libpq-dev \
  curl \
  && rm -rf /var/lib/apt/lists/*

# App directory
WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Copy and setup entrypoint
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Render documentation recommends exposing 10000
ENV PORT=10000
EXPOSE 10000

# Use the entrypoint script
CMD ["./entrypoint.sh"]