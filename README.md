# DevOps Copilot

Une plateforme multi-agents IA qui ecrit des manifests Kubernetes, les **verifie avec de vrais outils** (kubeconform, Trivy, documentation officielle), estime leur cout, et attend l'**approbation d'un humain** avant tout enregistrement.

> Projet d'apprentissage DevOps / Cloud / MLOps, construit etape par etape avec des outils gratuits.

---

## Le probleme

Ecrire des manifests Kubernetes est difficile, et un LLM seul produit souvent un YAML qui **a l'air** correct mais que personne n'a verifie : syntaxe invalide, conteneur en root, image `:latest`, pas de limites de ressources... Exemple reel rencontre pendant le projet : un nginx "securise" genere par un LLM plantait au demarrage (`readOnlyRootFilesystem` sans volume temporaire).

**DevOps Copilot ne se contente pas de dire que le YAML est bon : il le prouve avec des outils, et un humain garde le dernier mot.**

## L'equipe d'agents

| Agent | Role | Outils autorises |
|---|---|---|
| **Planner** | Comprend la demande, liste les ressources, refuse les demandes hors sujet | `search_k8s_docs` (RAG) |
| **Writer** | Ecrit le YAML et le valide | `search_k8s_docs`, `validate_k8s_yaml` (kubeconform) |
| **Security** | Relecture independante, refuse si le scan n'est pas propre | `scan_k8s_security` (Trivy), `search_k8s_docs` |
| **Cost** | Explique le cout mensuel estime | `estimate_k8s_cost` (calcul deterministe) |
| **Humain** | Approuve ou refuse l'enregistrement | Page web |

Si Security refuse, le Writer recoit les problemes et corrige (3 essais maximum).

## Architecture

```mermaid
flowchart LR
    U[Utilisateur<br/>page web] -->|HTTP| API[API FastAPI]
    EXT[Autre agent IA] -->|A2A| A2A[Serveur A2A] -->|HTTP| API
    API --> G[Graphe LangGraph]
    G --> P[Planner] --> W[Writer] --> S[Security]
    S -->|refuse| W
    S -->|approuve| C[Cost] --> H{Approbation<br/>humaine}
    G <-->|checkpoints| PG[(PostgreSQL)]
    P & W & S & C -->|MCP| MCP[Serveur MCP]
    MCP --> KC[kubeconform] & TR[Trivy] & RAG[(pgvector<br/>doc Kubernetes)]
    P & W & S & C -->|LLM| LLM[Groq / Gemini / Mistral]
    G -.->|traces| LF[Langfuse]
```

## Fonctionnalites

- **Multi-agents orchestres avec LangGraph** : etat partage, boucle de correction Writer/Security, pause et reprise avec `interrupt()`.
- **Humain dans la boucle** : rien n'est enregistre sans approbation, meme quand la demande vient d'un autre agent.
- **Outils via MCP** (Model Context Protocol) : kubeconform (avec catalogue de CRD), Trivy, RAG, estimation de cout.
- **RAG** : documentation officielle Kubernetes, embeddings Gemini, recherche vectorielle pgvector.
- **Missions durables** : checkpoints dans PostgreSQL ; une mission survit a un redemarrage du serveur.
- **Plusieurs fournisseurs LLM** : Groq, puis Gemini, puis Mistral en secours ; fail fast (timeouts, budget), attente sur limite de debit, fournisseur "collant" pendant une mission.
- **Garde-fous** : outils autorises par agent, limites d'appels, compaction du contexte, manifest vide refuse, demande hors sujet refusee, approbation interdite par le code si le scan n'est pas `SECURISE`.
- **Observabilite avec Langfuse** : une session par mission, un bloc par agent, tokens et durees.
- **Interface web** : suivi en direct des agents, historique, boutons Approuver / Refuser.
- **Docker + Kubernetes** : image non-root avec les outils, deploiement sur kind (manifest ecrit par DevOps Copilot lui-meme).
- **A2A** (Agent-to-Agent) : DevOps Copilot est decouvrable et utilisable par d'autres agents IA.

## Stack technique

| Domaine | Outils |
|---|---|
| Agents et orchestration | Python 3.14, LangGraph, OpenAI SDK (API compatibles) |
| Protocoles | MCP (SDK 2.x), A2A (a2a-sdk 1.3.1) |
| LLM | Groq (`gpt-oss-120b`), Google Gemini, Mistral |
| Donnees | PostgreSQL 18 + pgvector |
| Verification | kubeconform, Trivy |
| API et interface | FastAPI, Uvicorn, HTML/JavaScript |
| Observabilite | Langfuse (auto-heberge) |
| Deploiement | Docker, Kubernetes (kind) |

## Structure du projet

```
copilot/                    Code de l'application
  llm.py                    Le seul endroit qui parle aux LLM (fournisseurs, secours, quotas)
  agent.py                  Boucle d'agent reutilisable (LLM + outils MCP + garde-fous)
  mcp_server.py             Serveur MCP : validate, scan, count, search_k8s_docs, estimate_k8s_cost
  rag.py                    Embeddings et decoupage de la documentation Kubernetes
  writer.py                 Prompt et extraction YAML du Writer
  team.py                   Prompts du Planner, de Security et de Cost
  graph.py                  Orchestration LangGraph (noeuds, aretes conditionnelles, interrupt)
  tracing.py                Regroupement des traces Langfuse par agent et par mission
  api.py                    API FastAPI (missions, decisions) + checkpoints PostgreSQL
  static/index.html         Interface web
  a2a_server.py             Adaptateur A2A vers l'API
scripts/                    Utilitaires lances a la main
  ingest.py                 Indexation de la documentation Kubernetes
  a2a_client.py             Agent client de test A2A
  check_providers.py        Diagnostic des fournisseurs LLM
  list_mcp_tools.py         Liste les outils du serveur MCP
  search_test.py            Teste la recherche RAG
examples/                   Scripts d'apprentissage
docs/                       Guide de mise en fonction + documentation Kubernetes (RAG)
k8s/                        Manifest de deploiement Kubernetes
Dockerfile                  Image non-root avec kubeconform et Trivy
start.sh                    Script de demarrage
Makefile                    Raccourcis (build, test, deploy...)
```

Toutes les commandes se lancent depuis la racine du projet (par exemple `python -m copilot.graph --draw`, `python -m scripts.ingest`, `uvicorn copilot.api:app`).

## Installation

### Prerequis

Ubuntu, Python 3.14, Docker, kind, kubectl, kubeconform, Trivy, et au moins une cle API gratuite (Groq ou Gemini).

### 1. Code et dependances

```bash
git clone https://github.com/alajouili/devops-copilot.git
cd devops-copilot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Configuration (`.env`, jamais commite)

```
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-120b
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.5-flash
MISTRAL_API_KEY=...            # optionnel
MISTRAL_MODEL=mistral-small-2603
DATABASE_URL=postgresql://postgres:copilot@localhost:5433/copilot
EMBEDDING_MODEL=gemini-embedding-001
LANGFUSE_PUBLIC_KEY=...        # optionnel
LANGFUSE_SECRET_KEY=...
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_BASE_URL=http://localhost:3000
```

### 3. Base de donnees et documentation (une seule fois)

```bash
docker run -d --name copilot-db -e POSTGRES_PASSWORD=copilot -e POSTGRES_DB=copilot \
  -p 5433:5432 -v copilot-data:/var/lib/postgresql pgvector/pgvector:pg18
# Placer les pages .md de la documentation Kubernetes dans docs/k8s/, puis :
.venv/bin/python -m scripts.ingest
```

## Utilisation

```bash
./start.sh            # application en local : http://localhost:8000
./start.sh a2a        # application + serveur A2A (port 9100)
./start.sh k8s        # version Kubernetes : http://localhost:8080
./start.sh check      # teste les fournisseurs LLM
./start.sh status     # etat des services
./start.sh stop       # arrete tout
```

Exemple de demande :

```
Deployment "frontend" (label app=frontend), image nginxinc/nginx-unprivileged:1.27, 2 replicas,
containerPort 8080, non-root, readOnlyRootFilesystem, emptyDir sur /tmp et /var/cache/nginx,
requests 50m/64Mi, limits 200m/128Mi. Service ClusterIP port 80 vers 8080.
```

Depuis un autre agent (A2A) :

```bash
curl -s localhost:9100/.well-known/agent-card.json      # la carte de l'agent
.venv/bin/python -m scripts.a2a_client "votre demande"
```

### Docker et Kubernetes

```bash
docker build -t devops-copilot:0.4 .
kind load docker-image devops-copilot:0.4 --name airport
kubeconform -strict -summary k8s/devops-copilot.yaml
kubectl apply -f k8s/devops-copilot.yaml
kubectl -n devops-copilot rollout status deploy/devops-copilot
```

Les Secrets (`copilot-keys` depuis `.env`, `copilot-db` pour `DATABASE_URL`) sont crees avec `kubectl create secret` : aucune cle n'est dans l'image ni dans Git.

## Lecons apprises

| Probleme rencontre | Cause | Solution |
|---|---|---|
| Un nginx "securise" plantait | `readOnlyRootFilesystem` sans volume | Image `nginx-unprivileged` + `emptyDir` ; tester sur un vrai cluster |
| L'agent recommandait PodSecurityPolicy | Connaissance perimee du LLM (supprime en v1.25) | RAG sur la documentation officielle |
| Le Writer depassait la limite de tokens | Historique renvoye a chaque tour | Limite d'appels par outil, resultats tronques, compaction du contexte |
| Mission bloquee 20 minutes | Pas de timeout, trop de nouvelles tentatives | Fail fast : timeout et budget total par appel |
| Manifest vide approuve | Un scan ne trouve rien dans un fichier vide | Verifier que le resultat **existe** avant de verifier qu'il est **bon** |
| Pod tue par Kubernetes pendant une mission | Appels LLM synchrones qui bloquaient la boucle asyncio (liveness probe en echec) | `asyncio.to_thread` ; sondes plus tolerantes |
| Nouvelle version jamais deployee | `kubectl apply` en echec (YAML invalide) laissait l'ancienne version | Valider avant d'appliquer ; verifier l'image reellement deployee |
| Pannes et quotas des LLM gratuits | 503 et 429 des fournisseurs | Plusieurs fournisseurs, script de diagnostic |

## Limites

- Offres gratuites des LLM : les tres grosses demandes (plus de 15 ressources) peuvent depasser les limites ; la solution prevue est de decouper le travail du Writer par composant.
- Une seule instance de l'API (missions en cours suivies en memoire).
- Pas d'authentification : a utiliser en local uniquement.

## Auteur

**Ala Jouili** - etudiant ingenieur en TIC (SUP'COM), interesse par le DevOps, le Cloud et le MLOps.
GitHub : [alajouili](https://github.com/alajouili)