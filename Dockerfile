# ─── Stage 1: Use official Python as the base image ───
FROM python:3.12-slim

# ─── Set the working directory inside the container ───
WORKDIR /app

# ─── Copy only requirements first (for Docker layer caching) ───
COPY requirements.txt .

# ─── Install Python dependencies ───
RUN pip install --no-cache-dir -r requirements.txt

# ─── Copy the rest of the project code ───
COPY . .

# ─── Tell Docker this app uses port 8000 ───
EXPOSE 8000

# ─── Run the app when the container starts ───
# Render sets PORT env var automatically, fallback to 8000
CMD alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
