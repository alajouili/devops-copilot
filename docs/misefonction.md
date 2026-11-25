# Mise en fonction de DevOps Copilot

Ce fichier explique comment demarrer, verifier et arreter tous les services du projet.
Dossier du projet : `~/devops-copilot`

---

## 1. Au demarrage du PC (a faire a chaque fois)

```bash
cd ~/devops-copilot
source .venv/bin/activate
docker start copilot-db
docker ps
```

Verifications :
- le prompt commence par `(.venv)` ;
- `copilot-db` (PostgreSQL + pgvector, port 5433) est `Up` ;
- `airport-control-plane` (cluster kind) est `Up` (sinon : `docker start airport-control-plane`).

Raccourci (optionnel, a creer une seule fois) :

```bash
echo 'alias copilot="cd ~/devops-copilot && source .venv/bin/activate && docker start copilot-db >/dev/null"' >> ~/.bashrc
source ~/.bashrc
```

Ensuite, il suffit de taper `copilot` dans chaque nouveau terminal.

---

## 2. Langfuse (observabilite, optionnel)

Langfuse consomme beaucoup de RAM : le demarrer seulement quand on en a besoin.

```bash
cd ~/langfuse
docker compose start
docker compose logs -f langfuse-web
```

- Attendre la ligne `Ready`, puis `Ctrl+C` (Langfuse continue de tourner).
- Interface : http://localhost:3000 (projet `devops-copilot`).
- Les cles `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` et `LANGFUSE_BASE_URL` sont dans `.env`.

Tester la connexion :

```bash
cd ~/devops-copilot
python -c "from dotenv import load_dotenv; load_dotenv(); from langfuse import get_client; print('Langfuse :', get_client().auth_check())"
```

Resultat attendu : `Langfuse : True`.

Arreter Langfuse (libere la RAM) :

```bash
cd ~/langfuse && docker compose stop
```

---

## 3. Lancer l'application

### Option A : en local (developpement)

```bash
cd ~/devops-copilot && source .venv/bin/activate
python -c "import copilot.api; print('OK')"
uvicorn copilot.api:app --port 8000
```

- Attendre la ligne `[api] pret : MCP connecte, checkpoints dans PostgreSQL`.
- Page web : http://localhost:8000
- Documentation de l'API (Swagger) : http://localhost:8000/docs

Mode ligne de commande (sans page web) :

```bash
python -m copilot.graph                 # demande par defaut (nginx)
python -m copilot.graph "ma demande"    # demande personnalisee
python -m copilot.graph --draw          # dessin du graphe (coller dans https://mermaid.live)
```

### Option B : dans Docker

Reconstruire l'image apres chaque changement de code (changer le numero de version) :

```bash
docker build -t devops-copilot:0.2 .
docker run --rm devops-copilot:0.2 sh -c "kubeconform -v && trivy --version | head -1"
docker run --rm --network host --env-file .env devops-copilot:0.2
```

- Page web : http://localhost:8000
- Le port 8000 doit etre libre (arreter `uvicorn` avant).

### Option C : dans Kubernetes (cluster kind "airport")

A faire une seule fois (ou apres un nouveau build) :

```bash
docker network connect kind copilot-db
docker network connect kind langfuse-langfuse-web-1      # seulement si Langfuse tourne
kind load docker-image devops-copilot:0.2 --name airport
kubectl apply -f k8s/devops-copilot.yaml
```

Verifier et ouvrir :

```bash
kubectl -n devops-copilot get pods
kubectl -n devops-copilot logs deploy/devops-copilot
kubectl -n devops-copilot port-forward svc/devops-copilot 8080:80
```

- Page web : http://localhost:8080
- Mettre a jour l'image : `kubectl -n devops-copilot set image deploy/devops-copilot api=devops-copilot:0.X`

---

## 4. Tests rapides apres demarrage

| Test | Demande | Resultat attendu |
|---|---|---|
| Normal | demande nginx par defaut | jusqu'a l'approbation, puis `terminee` |
| Hors sujet | `fais-moi un gateau` | statut `hors_sujet`, arret propre |
| Complexe | application e-commerce (11 ressources) | aboutit, ou echoue vite (moins de 3 min) avec un message clair |

Attention aux quotas gratuits : Gemini environ 20 requetes par jour, Groq 8000 tokens par minute.

---

## 5. Avant d'eteindre le PC

1. `Ctrl+C` dans chaque terminal qui tourne (`uvicorn`, `docker run`, `port-forward`).
2. Quitter Claude Code : `/exit`.
3. Sauvegarder le travail :

```bash
cd ~/devops-copilot
git status --short          # verifier que .env n'apparait PAS
git add -A
git commit -m "description du travail"
```

4. Eteindre : `sudo poweroff`

Les donnees restent sur le disque : missions (PostgreSQL), traces (Langfuse), cluster kind.

---

## 6. Problemes frequents

| Message | Cause | Solution |
|---|---|---|
| `python: command not found` | venv non active | `source .venv/bin/activate` |
| `externally-managed-environment` | `pip` sans venv | activer le venv, ne jamais utiliser `--break-system-packages` |
| `claude: command not found` | `~/.local/bin` absent du PATH | ouvrir un nouveau terminal |
| `connection refused` port 5433 | PostgreSQL arrete | `docker start copilot-db` |
| `Langfuse : False` | Langfuse arrete ou mauvaises cles | `cd ~/langfuse && docker compose start` |
| `address already in use` port 8000 | un autre serveur tourne | `Ctrl+C` sur l'ancien `uvicorn` ou `docker run` |
| `docker build ... requires 1 argument` | point final oublie | `docker build -t devops-copilot:0.2 .` |
| `Aucun fournisseur disponible` | quota Groq ou Gemini atteint | attendre (Groq : 1 minute, Gemini : le lendemain) |

Verifier qu'un fichier est en ASCII pur :

```bash
grep -rnP '[^\x00-\x7F]' copilot scripts
```