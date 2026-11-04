FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LLM_PROVIDER=anthropic PORT=10000 MALLOC_ARENA_MAX=2
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
# gotowy, skompresowany indeks (data/index.npz + data/meta.json.gz) – bez budowania na serwerze
COPY data/index.npz data/meta.json.gz data/facts.yaml data/
RUN useradd -m u && chown -R u /srv
USER u
EXPOSE 10000
CMD ["sh","-c","cd app && exec uvicorn server:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
