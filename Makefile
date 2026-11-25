# Makefile de DevOps Copilot
# Usage : make help
# Attention : dans un Makefile, les lignes de commande commencent par une TABULATION, pas des espaces.

VERSION    ?= 0.2
IMAGE      := devops-copilot:$(VERSION)
VENV       := .venv
PY         := $(VENV)/bin/python
PORT       ?= 8000
CLUSTER    := airport
NAMESPACE  := devops-copilot
K8S_FILE   := k8s/devops-copilot.yaml
LANGFUSE   := $(HOME)/langfuse

.DEFAULT_GOAL := help
.PHONY: help install up db langfuse-up langfuse-down run dev cli stop check-ascii check-import \
        check-providers test build image-check docker-run scan-image kind-load deploy status logs \
        open undeploy commit-check

help: ## Affiche cette aide
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------- Installation et services ----------

install: ## Cree le venv et installe les dependances
	test -d $(VENV) || python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

db: ## Demarre PostgreSQL + pgvector (copilot-db)
	docker start copilot-db

langfuse-up: ## Demarre Langfuse (http://localhost:3000)
	cd $(LANGFUSE) && docker compose start

langfuse-down: ## Arrete Langfuse (libere la RAM)
	cd $(LANGFUSE) && docker compose stop

up: db ## Demarre les services necessaires (base de donnees)
	@docker ps --format '{{.Names}}' | grep -q airport-control-plane || docker start airport-control-plane
	@echo "Services prets. Lancez : make run"

# ---------- Lancer l'application ----------

run: db stop ## Lance l'API + la page web (http://localhost:8000)
	$(VENV)/bin/uvicorn copilot.api:app --port $(PORT)

dev: db stop ## Comme run, mais redemarre a chaque modification du code
	$(VENV)/bin/uvicorn copilot.api:app --port $(PORT) --reload

cli: db ## Lance une mission en ligne de commande (make cli REQ="ma demande")
	$(PY) -m copilot.graph $(REQ)

stop: ## Libere le port 8000 (arrete un ancien uvicorn)
	-@pkill -f "[u]vicorn copilot.api:app" && sleep 1 || true
	-@pkill -9 -f "[u]vicorn copilot.api:app" || true
	@ss -ltn | grep -q ':$(PORT) ' && echo "Port $(PORT) encore occupe" || echo "Port $(PORT) libre"

# ---------- Verifications ----------

check-ascii: ## Verifie que les fichiers sont en ASCII pur
	@! grep -nP '[^\x00-\x7F]' copilot/*.py copilot/static/*.html scripts/*.py Dockerfile Makefile && echo "ASCII OK"

check-import: ## Verifie que l'API se charge sans erreur
	$(PY) -c "import copilot.api; print('import api OK')"

check-providers: ## Teste les fournisseurs LLM (Groq, Gemini, Mistral)
	$(PY) -m scripts.check_providers

test: check-ascii check-import ## Lance toutes les verifications rapides (sans LLM)
	@echo "Verifications OK"

# ---------- Docker ----------

build: check-ascii ## Construit l'image Docker (make build VERSION=0.3)
	docker build -t $(IMAGE) .

image-check: ## Verifie l'image : utilisateur non-root et outils presents
	docker run --rm $(IMAGE) id
	docker run --rm $(IMAGE) sh -c "kubeconform -v && trivy --version | head -1"

docker-run: stop ## Lance l'application dans le conteneur (http://localhost:8000)
	docker run --rm --network host --env-file .env $(IMAGE)

scan-image: ## Scanne l'image avec Trivy (HIGH et CRITICAL)
	trivy image --severity HIGH,CRITICAL $(IMAGE)

# ---------- Kubernetes (cluster kind) ----------

kind-load: ## Charge l'image dans le cluster kind
	kind load docker-image $(IMAGE) --name $(CLUSTER)

deploy: kind-load ## Deploie (ou met a jour) l'application sur Kubernetes
	kubeconform -strict -summary $(K8S_FILE)
	kubectl apply -f $(K8S_FILE)
	kubectl -n $(NAMESPACE) set image deploy/devops-copilot api=$(IMAGE)
	kubectl -n $(NAMESPACE) rollout status deploy/devops-copilot

status: ## Affiche l'etat des pods
	kubectl -n $(NAMESPACE) get pods,svc

logs: ## Affiche les logs de l'application dans Kubernetes
	kubectl -n $(NAMESPACE) logs deploy/devops-copilot --tail=50

open: ## Ouvre l'application du cluster sur http://localhost:8080
	kubectl -n $(NAMESPACE) port-forward svc/devops-copilot 8080:80

undeploy: ## Supprime l'application du cluster
	kubectl delete -f $(K8S_FILE)

# ---------- Git ----------

commit-check: test ## Verifie avant un commit (ASCII, import, pas de .env)
	@! git status --short | grep -E '(^| )\.env$$' && echo "Pas de .env dans git : OK"