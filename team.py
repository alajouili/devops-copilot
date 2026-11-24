"""DevOps Copilot : une equipe de 4 agents (Planner, Writer, Security, Cost) + validation humaine."""
import asyncio
import json
import pathlib
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent import run_agent
from writer import TEAM_SYSTEM as WRITER_SYSTEM, extract_yaml

PLANNER_SYSTEM = """Tu es l'agent Planner de DevOps Copilot. Reponds en francais.
Analyse la demande et produis un plan de travail pour l'agent Writer.
Tu peux utiliser search_k8s_docs (au maximum 1 fois) pour verifier les bonnes pratiques actuelles.
Regles : jamais d'image en :latest ; n'ajoute pas de Namespace si la demande n'en parle pas.
Ta reponse finale est du TEXTE (pas un appel d'outil) : uniquement un JSON valide, sans texte autour, de la forme :
{"ressources": ["Deployment web", "Service web"],
 "exigences": ["3 replicas", "port 8080"],
 "securite": ["non-root", "readOnlyRootFilesystem"],
 "hypotheses": ["ce que tu as du supposer car la demande ne le precise pas"]}
HORS SUJET : si la demande ne concerne PAS des ressources Kubernetes a ecrire ou deployer
(ex. un poeme, une recette, une question generale sans rapport), n'utilise aucun outil et reponds
uniquement : {"hors_sujet": true, "raison": "une phrase qui explique pourquoi"}"""

SECURITY_SYSTEM = """Tu es l'agent Security de DevOps Copilot, relecteur INDEPENDANT. Reponds en francais.
Notre code a deja lance scan_k8s_security (Trivy) sur le manifest ecrit par un autre agent :
on te donne son resultat. Tu ne fais pas confiance a l'auteur du manifest.
Si besoin, verifie avec search_k8s_docs (au maximum 1 fois) les bonnes pratiques Pod Security "restricted".
Ta reponse finale est du TEXTE (pas un appel d'outil) : uniquement un JSON valide, sans texte autour :
{"approuve": true ou false,
 "problemes": ["probleme precis (ressource, conteneur) + comment le corriger"],
 "resume": "une phrase"}
N'approuve QUE si le scan a renvoye SECURISE. Sinon, liste CHAQUE probleme du scan."""

COST_SYSTEM = """Tu es l'agent Cost de DevOps Copilot. Reponds en francais, en 5 lignes maximum.
Notre code a deja lance estimate_k8s_cost sur le manifest : on te donne son resultat.
Explique-le simplement et propose UNE piste d'economie.
Ne refais jamais les calculs toi-meme : utilise le resultat de l'outil."""

MAX_ESSAIS = 3


def extract_json(text: str) -> dict:
    """Recupere le premier objet JSON {...} d'une reponse de LLM."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError(f"Pas de JSON dans la reponse :\n{text}")
    return json.loads(match.group(0))


def title(text: str):
    print(f"\n{'=' * 60}\n{text}\n{'=' * 60}")


async def main():
    request = sys.argv[1] if len(sys.argv) > 1 else (
        "Un Deployment nginx securise avec 3 replicas, et un Service ClusterIP "
        "qui expose le port 80 vers le port 8080 des pods.")
    print(f"Demande : {request}")

    server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. PLANNER : decouper la demande
            title("[PLANNER]")
            answer, _, _ = await run_agent(session, PLANNER_SYSTEM, request,
                                           allowed=["search_k8s_docs"])
            plan = extract_json(answer)
            print(json.dumps(plan, indent=2, ensure_ascii=False))

            # 2. WRITER <-> SECURITY : ecrire, relire, corriger
            feedback = ""
            yaml_text, verdict = None, {"approuve": False}
            for essai in range(1, MAX_ESSAIS + 1):
                title(f"[WRITER] essai {essai}/{MAX_ESSAIS}")
                writer_task = (f"Demande : {request}\n\nPlan du Planner :\n"
                               f"{json.dumps(plan, ensure_ascii=False)}")
                if feedback:
                    # On renvoie seulement le dernier YAML et les problemes : pas tout l'historique
                    writer_task += f"\n\nCorrige ce manifest :\n```yaml\n{yaml_text or ''}\n```\n"
                    writer_task += f"Problemes signales par l'agent Security :\n{feedback}"
                answer, _, _ = await run_agent(session, WRITER_SYSTEM, writer_task,
                                               allowed=["search_k8s_docs", "validate_k8s_yaml"])
                yaml_text = extract_yaml(answer)
                if not yaml_text:
                    feedback = "Ta reponse ne contenait pas de bloc ```yaml."
                    continue

                title(f"[SECURITY] relecture {essai}")
                answer, _, _ = await run_agent(session, SECURITY_SYSTEM,
                                               f"Manifest a auditer :\n\n{yaml_text}",
                                               allowed=["scan_k8s_security", "search_k8s_docs"])
                verdict = extract_json(answer)
                status = "APPROUVE" if verdict.get("approuve") else "REFUSE"
                print(f"Verdict : {status} - {verdict.get('resume', '')}")
                for p in verdict.get("problemes", []):
                    print(f"   - {p}")
                if verdict.get("approuve"):
                    break
                feedback = "\n".join(f"- {p}" for p in verdict.get("problemes", []))
            else:
                print(f"\nPas d'accord entre Writer et Security apres {MAX_ESSAIS} essais.")

            if not yaml_text:
                return

            # 3. COST : estimer le cout
            title("[COST]")
            cost, _, _ = await run_agent(session, COST_SYSTEM, f"Manifest :\n\n{yaml_text}",
                                         allowed=["estimate_k8s_cost"])
            print(cost)

            # 4. VALIDATION HUMAINE : rien n'est enregistre sans votre accord
            title("[VALIDATION HUMAINE]")
            print(yaml_text)
            choice = input("\nEnregistrer ce manifest ? (o/n) : ").strip().lower()
            if choice == "o":
                out = pathlib.Path("output")
                out.mkdir(exist_ok=True)
                (out / "manifest.yaml").write_text(yaml_text + "\n")
                (out / "rapport.md").write_text(
                    f"# Rapport DevOps Copilot\n\n## Demande\n{request}\n\n## Plan\n```json\n"
                    f"{json.dumps(plan, indent=2, ensure_ascii=False)}\n```\n\n## Securite\n"
                    f"{'Approuve' if verdict.get('approuve') else 'NON approuve'} : {verdict.get('resume', '')}\n\n"
                    f"## Cout\n{cost}\n")
                print("Enregistre : output/manifest.yaml et output/rapport.md")
            else:
                print("Abandonne, rien n'a ete enregistre.")


if __name__ == "__main__":
    asyncio.run(main())