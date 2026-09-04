FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libxcb-shm0 \
        libxcb-render0 \
        libxcb-xfixes0 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

ENTRYPOINT ["python", "main.py", "--web", "--host", "0.0.0.0", "--port", "8501"]
