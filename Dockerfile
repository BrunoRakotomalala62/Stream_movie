# ============================================================
# MovieBox API - Dockerfile pour déploiement Render.com
# ============================================================

# ---- Étape 1 : Builder (optionnel, garde l'image légère) ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Copier les dépendances en premier (meilleur cache Docker)
COPY requirements.txt .

# Installer dans un venv pour copie propre
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- Étape 2 : Image finale ----
FROM python:3.11-slim

WORKDIR /app

# Copier le venv complet
COPY --from=builder /opt/venv /opt/venv

# Copier le code
COPY server.py .

# Créer le dossier cache
RUN mkdir -p /app/cache

# Utiliser le venv
ENV PATH="/opt/venv/bin:$PATH"

# Render.com définit automatiquement PORT (généralement 10000)
# On écoute sur 0.0.0.0 pour être accessible
EXPOSE ${PORT:-5000}

# Gunicorn en production (performant + stable)
# --preload : charge l'app avant le fork (économise la mémoire)
# 2 workers : adapté aux conteneurs Render (mémoire limitée)
CMD gunicorn server:app \
    --bind 0.0.0.0:${PORT:-5000} \
    --workers 2 \
    --timeout 30 \
    --keep-alive 5 \
    --preload \
    --access-logfile - \
    --error-logfile -
