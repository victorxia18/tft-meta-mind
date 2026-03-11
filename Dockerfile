FROM mcr.microsoft.com/playwright/python:v1.51.0-noble

WORKDIR /app

# Layer-cached dependency install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium matching the pip playwright version
RUN playwright install chromium

# Copy application code
COPY . .

# Create non-root user and ensure volume directories exist with correct ownership
RUN useradd --create-home appuser \
    && mkdir -p /app/data/raw /app/chroma_db /app/logs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
