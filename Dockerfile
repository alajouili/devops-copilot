# Etape 7-D : image de DevOps Copilot
FROM python:3.14-slim

# Pas de fichiers .pyc ; les logs Python s'affichent tout de suite
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Les dependances d'abord : cette couche reste en cache tant que requirements.txt ne change pas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) Les outils DevOps utilises par le serveur MCP
COPY bin/kubeconform bin/trivy /usr/local/bin/

# 3) Un utilisateur non-root (on applique a nous-memes ce que Security exige des autres)
RUN useradd --create-home --uid 10001 copilot \
 && mkdir -p /app/output && chown copilot:copilot /app/output

# 4) Le code en dernier : c'est ce qui change le plus souvent
COPY --chown=copilot:copilot *.py ./
COPY --chown=copilot:copilot static/ ./static/

USER 10001
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]