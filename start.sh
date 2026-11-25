#!/usr/bin/env bash
# Demarrage de DevOps Copilot.
#
# Usage :
#   ./start.sh            -> lance l'application en local (http://localhost:8000)
#   ./start.sh a2a        -> lance l'application + le serveur A2A (port 9100)
#   ./start.sh k8s        -> ouvre la version Kubernetes (http://localhost:8080)
#   ./start.sh langfuse   -> demarre Langfuse (http://localhost:3000)
#   ./start.sh check      -> teste les fournisseurs LLM (Groq, Gemini, Mistral)
#   ./start.sh status     -> affiche l'etat de tous les services
#   ./start.sh stop       -> arrete tout ce que ce script a lance

set -uo pipefail
cd "$(dirname "$0")" || exit 1

MODE="${1:-local}"
API_PORT=8000
A2A_PORT=9100
K8S_PORT=8080
VENV=".venv"
LOG_DIR="logs"
NAMESPACE="devops-copilot"

info() { echo "[start] $*"; }
fail() { echo "[start] ERREUR : $*" >&2; exit 1; }
port_busy() { ss -ltn | grep -q ":$1 "; }

wait_http() {
    # Attend qu'une URL reponde (max $2 secondes)
    local url="$1" max="$2" i=0
    while ! curl -s -o /dev/null "$url"; do
        i=$((i + 1))
        [ "$i" -ge "$max" ] && return 1
        sleep 1
    done
}

check_base() {
    [ -x "$VENV/bin/python" ] || fail "venv introuvable. Lancez : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    [ -f .env ] || fail "fichier .env introuvable (cles API et DATABASE_URL)."
    docker info >/dev/null 2>&1 || fail "Docker ne repond pas. Lancez Docker puis recommencez."
}

start_db() {
    info "Demarrage de PostgreSQL (copilot-db)..."
    docker start copilot-db >/dev/null || fail "conteneur copilot-db introuvable."
    local i=0
    until docker exec copilot-db pg_isready -U postgres >/dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -ge 30 ] && fail "PostgreSQL ne repond pas apres 30 s."
        sleep 1
    done
    info "PostgreSQL pret."
}

stop_all() {
    info "Arret des serveurs lances par ce script..."
    pkill -f "[u]vicorn copilot.api:app" 2>/dev/null && sleep 1
    pkill -9 -f "[u]vicorn copilot.api:app" 2>/dev/null
    pkill -f "[c]opilot.a2a_server" 2>/dev/null
    pkill -f "[p]ort-forward svc/devops-copilot" 2>/dev/null
    for p in $API_PORT $A2A_PORT $K8S_PORT; do
        if port_busy "$p"; then info "port $p : encore occupe (ss -ltnp | grep :$p)"; else info "port $p : libre"; fi
    done
}

start_api_foreground() {
    port_busy "$API_PORT" && { info "Port $API_PORT occupe : arret de l'ancien serveur."; stop_all; }
    info "Lancement de l'API sur http://localhost:$API_PORT (Ctrl+C pour arreter)"
    exec "$VENV/bin/uvicorn" copilot.api:app --port "$API_PORT"
}

start_api_background() {
    port_busy "$API_PORT" && { info "Port $API_PORT occupe : arret de l'ancien serveur."; stop_all; }
    mkdir -p "$LOG_DIR"
    info "Lancement de l'API en arriere-plan (logs : $LOG_DIR/api.log)..."
    nohup "$VENV/bin/uvicorn" copilot.api:app --port "$API_PORT" > "$LOG_DIR/api.log" 2>&1 &
    wait_http "http://localhost:$API_PORT/" 60 || fail "l'API ne demarre pas : voir $LOG_DIR/api.log"
    info "API prete sur http://localhost:$API_PORT"
}

show_status() {
    echo "--- Conteneurs ---"
    docker ps --format '  {{.Names}}' | grep -E "copilot-db|airport-control-plane|langfuse-langfuse-web" || echo "  (aucun)"
    echo "--- Ports ---"
    for p in $API_PORT $A2A_PORT $K8S_PORT 3000; do
        if port_busy "$p"; then echo "  $p : occupe"; else echo "  $p : libre"; fi
    done
    echo "--- Kubernetes ---"
    if kubectl -n "$NAMESPACE" get pods 2>/dev/null; then
        printf "  image : "
        kubectl -n "$NAMESPACE" get deploy devops-copilot -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null
        echo
    else
        echo "  cluster non joignable"
    fi
}

case "$MODE" in
    local)
        check_base
        start_db
        start_api_foreground
        ;;
    a2a)
        check_base
        start_db
        start_api_background
        port_busy "$A2A_PORT" && fail "port $A2A_PORT deja occupe (ss -ltnp | grep :$A2A_PORT)."
        trap 'info "Arret..."; stop_all' EXIT
        info "Serveur A2A sur http://localhost:$A2A_PORT (carte : /.well-known/agent-card.json)"
        info "Dans un autre terminal : .venv/bin/python -m scripts.a2a_client \"votre demande\""
        "$VENV/bin/python" -m copilot.a2a_server
        ;;
    k8s)
        info "Demarrage du cluster kind et de la base..."
        docker start airport-control-plane copilot-db >/dev/null || fail "conteneurs introuvables."
        info "Attente du pod devops-copilot (2 minutes max)..."
        kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l app=devops-copilot --timeout=120s \
            || fail "le pod n'est pas pret : kubectl -n $NAMESPACE describe pod -l app=devops-copilot"
        port_busy "$K8S_PORT" && pkill -f "[p]ort-forward svc/devops-copilot"
        info "Application Kubernetes sur http://localhost:$K8S_PORT (Ctrl+C pour fermer le tunnel)"
        exec kubectl -n "$NAMESPACE" port-forward svc/devops-copilot "$K8S_PORT:80"
        ;;
    langfuse)
        [ -d "$HOME/langfuse" ] || fail "dossier ~/langfuse introuvable."
        (cd "$HOME/langfuse" && docker compose start) || fail "Langfuse ne demarre pas."
        info "Langfuse demarre sur http://localhost:3000 (pret en 1 a 2 minutes)."
        ;;
    check)
        check_base
        "$VENV/bin/python" -m scripts.check_providers || true
        ;;
    status)
        show_status
        ;;
    stop)
        stop_all
        ;;
    *)
        sed -n '2,11p' "$0"
        exit 1
        ;;
esac