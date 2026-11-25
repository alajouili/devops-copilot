"""Etape 8 : un autre agent qui decouvre DevOps Copilot et lui confie une mission par A2A."""
import asyncio
import sys
import uuid

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_artifact_text, get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

AGENT_URL = "http://127.0.0.1:9100"
DEFAULT = "Un Deployment nginx securise avec 2 replicas et un Service ClusterIP sur le port 80 vers 8080."


async def main(request):
    # Une mission peut durer plusieurs minutes : on attend jusqu a 15 min entre deux evenements
    http = httpx.AsyncClient(timeout=httpx.Timeout(900, connect=10))

    # 1. Decouverte : comme n'importe quel agent, on lit d'abord la "carte de visite"
    card = (await http.get(f"{AGENT_URL}/.well-known/agent-card.json")).json()
    print(f"Agent decouvert : {card['name']} (version {card['version']})")
    for skill in card.get("skills", []):
        print(f"  competence : {skill['name']}")

    client = await create_client(AGENT_URL, client_config=ClientConfig(httpx_client=http))

    message = Message(role=Role.ROLE_USER, message_id=str(uuid.uuid4()), parts=[Part(text=request)])
    print(f"Demande envoyee : {request}\n")
    # 2. On confie la tache, puis on recoit les mises a jour au fil de l eau (streaming)
    async for event in client.send_message(SendMessageRequest(message=message)):
        if event.HasField("status_update"):
            st = event.status_update.status
            text = get_message_text(st.message) if st.HasField("message") else ""
            print(f"[statut] {TaskState.Name(st.state)} {text}")
        elif event.HasField("artifact_update"):
            print(f"[artefact] {event.artifact_update.artifact.name}\n{get_artifact_text(event.artifact_update.artifact)}")
        elif event.HasField("task"):
            t = event.task
            print(f"[tache] {t.id} etat={TaskState.Name(t.status.state)}")
            for a in t.artifacts:
                print(f"[artefact] {a.name}\n{get_artifact_text(a)}")
        elif event.HasField("message"):
            print(f"[message] {get_message_text(event.message)}")
    await client.close()
    await http.aclose()


if __name__ == "__main__":
    asyncio.run(main(" ".join(sys.argv[1:]) or DEFAULT))