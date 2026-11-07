# Build a partir da RAIZ do repositório (o docker-compose.yml já faz isso):
#   docker compose up -d --build
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
# fontes para a Label 228 (no Linux não há Arial)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY portal_envios/requirements.txt portal_envios/requirements.txt
RUN pip install -r portal_envios/requirements.txt

# lógica do painel atual (sem o dashboard.py do Streamlit) + o portal
COPY sheets.py tracker.py emissao_shippo.py leitor_foto.py label_passaporte.py departamentos.py atualizar_tarefas.py LABEL_3.png ./
COPY portal_envios/ portal_envios/

# roda sem root; o secrets.toml chega pelo volume em /app/.streamlit/
RUN useradd --uid 1000 --create-home app && mkdir -p /app/.streamlit && chown -R app /app
USER app

EXPOSE 8080
CMD ["uvicorn", "portal_envios.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
