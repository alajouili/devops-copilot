"""Etape 8 : DevOps Copilot expose comme agent A2A.

Ce serveur est un ADAPTATEUR : il recoit des demandes d'autres agents (protocole A2A),
les transmet a l'API HTTP de DevOps Copilot (api.py), suit la mission, et renvoie le resultat.
L'approbation reste HUMAINE : la mission attend toujours un clic dans la page web.
"""
import asyncio
import os

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

COPILOT_API = os.getenv("COPILOT_API", "http://localhost:8000")   # l'API de DevOps Copilot
A2A_HOST = os.getenv("A2A_HOST", "127.0.0.1")
A2A_PORT = int(os.getenv("A2A_PORT", "9100"))
POLL_SECONDS = 5
MAX_WAIT_SECONDS = 900   # 15 minutes au plus pour une mission


def build_agent_card():
    """La carte de visite de l'agent : ce que les autres agents lisent pour le decouvrir."""
    skill = AgentSkill(
        id="k8s_manifest",
        name="Ecrire un manifest Kubernetes verifie",
        description=("Une equipe de 4 agents (Planner, Writer, Security, Cost) ecrit un manifest "
                     "Kubernetes, le valide avec kubeconform, le scanne avec Trivy et estime son cout. "
                     "Un humain doit approuver avant tout enregistrement."),
        tags=["kubernetes", "devops", "security", "yaml"],
        examples=["Un Deployment nginx securise avec 3 replicas et un Service ClusterIP"],
    )
    return AgentCard(
        name="DevOps Copilot",
        description="Genere des manifests Kubernetes valides, securises et chiffres.",
        version="0.8.0",
        supported_interfaces=[AgentInterface(url=f"http://{A2A_HOST}:{A2A_PORT}/",
                                             protocol_binding="JSONRPC",
                                             protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[skill],
    )


def summary(m):
    """Resume texte d'une mission, pour l'agent qui a fait la demande."""
    verdict = m.get("verdict") or {}
    return (f"Mission {m['thread_id']} : manifest pret, en attente d'approbation HUMAINE "
            f"dans la page web de DevOps Copilot.\n"
            f"Securite : {'approuve' if verdict.get('approuve') else 'non approuve'} - {verdict.get('resume', '')}\n"
            f"Cout : {m.get('cout') or '-'}")


class CopilotExecutor(AgentExecutor):
    """Le pont entre le protocole A2A et l'API de DevOps Copilot."""

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        request = context.get_user_input()

        async with httpx.AsyncClient(base_url=COPILOT_API, timeout=30) as api:
            r = await api.post("/missions", json={"request": request})
            r.raise_for_status()
            thread_id = r.json()["thread_id"]
            await updater.start_work(updater.new_agent_message(
                [new_text_part(f"Mission {thread_id} lancee : Planner, Writer, Security, Cost...")]))

            waited = 0
            while waited < MAX_WAIT_SECONDS:
                await asyncio.sleep(POLL_SECONDS)
                waited += POLL_SECONDS
                m = (await api.get(f"/missions/{thread_id}")).json()
                status = m.get("status")

                if status == "en_attente_approbation":
                    await updater.add_artifact([new_text_part(m.get("manifest") or "")],
                                               name="manifest.yaml")
                    await updater.complete(updater.new_agent_message([new_text_part(summary(m))]))
                    return
                if status == "hors_sujet":
                    await updater.reject(updater.new_agent_message(
                        [new_text_part(m.get("message") or "Demande hors sujet : seulement Kubernetes.")]))
                    return
                if status in ("erreur", "terminee"):
                    detail = m.get("erreur") or "Security a refuse toutes les versions du manifest."
                    await updater.failed(updater.new_agent_message(
                        [new_text_part(f"Mission {thread_id} en echec : {detail}")]))
                    return

            await updater.failed(updater.new_agent_message(
                [new_text_part(f"Mission {thread_id} : delai depasse ({MAX_WAIT_SECONDS} s).")]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError("L'annulation n'est pas prise en charge.")


def build_app():
    card = build_agent_card()
    handler = DefaultRequestHandler(agent_executor=CopilotExecutor(),
                                    task_store=InMemoryTaskStore(), agent_card=card)
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/")
    return Starlette(routes=routes)


if __name__ == "__main__":
    print(f"[a2a] DevOps Copilot sur http://{A2A_HOST}:{A2A_PORT}/  (API : {COPILOT_API})")
    uvicorn.run(build_app(), host=A2A_HOST, port=A2A_PORT)