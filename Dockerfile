# Use Python 3.9 slim image
FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security
# สร้าง user ก่อนที่จะเปลี่ยน ownership และสร้างโฟลเดอร์ที่จำเป็น
RUN useradd -m -u 1000 botuser

# Change ownership of the entire /app directory to botuser
RUN chown -R botuser:botuser /app

# --- แก้ไขเพิ่มเติมตรงนี้ ---
# Create the logs directory and ensure botuser has write permissions
# ทำให้แน่ใจว่าโฟลเดอร์ logs ถูกสร้างขึ้น และเป็นของ botuser ด้วย
RUN mkdir -p /app/logs && chown botuser:botuser /app/logs
# หรือถ้าคุณต้องการให้แน่ใจว่า botuser มีสิทธิ์เขียนในโฟลเดอร์ logs อย่างแน่นอน
# RUN mkdir -p /app/logs && chmod 755 /app/logs
# Note: 755 (rwxr-xr-x) means owner can read/write/execute, group/others can read/execute.
# If botuser is the owner, it can write. If not, you might need 775 or 777 temporarily for testing.
# แต่เนื่องจาก chown /app ไปแล้ว โฟลเดอร์ที่สร้างใหม่ภายใต้ /app ก็ควรจะเป็นของ botuser

# Switch to the non-root user
USER botuser

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe')" || exit 1

# Run the application
CMD ["python", "main.py"]