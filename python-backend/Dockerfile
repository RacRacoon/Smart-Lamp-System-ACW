FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default proses Docker itu root - kalau container ini pernah kena RCE (dependency
# ter-compromise, dst.), root di dalam container jauh lebih leluasa (mis. baca socket
# Docker kalau ke-mount, ubah file punya proses lain) dibanding user biasa. Tidak
# mencegah RCE itu sendiri, cuma mempersempit apa yang bisa dilakukan sesudahnya.
RUN useradd --create-home --shell /usr/sbin/nologin acw \
    && chown -R acw:acw /app
USER acw

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
