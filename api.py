import asyncio
import sys
import os
import uuid
from contextlib import AsyncExitStack, asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from graph import build_graph
from writer import DEFAULT_REQUEST

load_dotenv()

RUNNING = {}
ERRORS ={}

@asynccontextmanager
async def lifespan(app):
    """Au demarrage : serveur MCP + checkpointer PostgreSQL + graphe. A l'arret : on ferme tout."""
    async with AsyncExitStack() as stack:
        server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"], env=dict(os.environ))
        read, write = await stack.enter_async_context(stdio_client(server))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        checkpointer = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(os.environ["DATABASE_URL"]))
        await checkpointer.setup()
        app.state.graph = build_graph(session, checkpointer)
        print("[api] pret : MCP connecte, checkpoints dans PostgreSQL")
        yield

app = FastAPI(title="DevOps Copilot", lifespan=lifespan)


class MissionIn(BaseModel):
    request: str = DEFAULT_REQUEST

class DecisionIn(BaseModel):
    decision: str   # "o" pour enregistrer, "n" pour refuser


def config_for(thread_id):
    return {"configurable": {"thread_id": thread_id}}


def launch(thread_id, graph_input):
    """Lance (ou reprend) le graphe en arriere-plan, sans bloquer la requete HTTP."""
    async def job():
        try:
            await app.state.graph.ainvoke(graph_input, config_for(thread_id))
        except Exception as e:
            ERRORS[thread_id] = f"{type(e).__name__}: {e}"
        finally:
            RUNNING.pop(thread_id, None)

    ERRORS.pop(thread_id, None)
    RUNNING[thread_id] = asyncio.create_task(job())


@app.post("/missions")
async def create_mission(body: MissionIn):
    thread_id = uuid.uuid4().hex[:8]
    launch(thread_id, {"request": body.request})
    return {"thread_id": thread_id, "status": "en_cours"}


@app.get("/missions/{thread_id}")
async def get_mission(thread_id: str):
    snapshot = await app.state.graph.aget_state(config_for(thread_id))
    values = snapshot.values or {}
    if not values and thread_id not in RUNNING:
        raise HTTPException(404, "Mission inconnue")

    if thread_id in RUNNING:
        status = "en_cours"
    elif thread_id in ERRORS:
        status = "erreur"
    elif "approval" in snapshot.next:
        status = "en_attente_approbation"
    else:
        status = "terminee"

    return {"thread_id": thread_id, "status": status, "etape_suivante": list(snapshot.next),
            "request": values.get("request"), "essais": values.get("essais"), "plan": values.get("plan"),
            "manifest": values.get("manifest"), "verdict": values.get("verdict"),
            "cout": values.get("cout"), "decision": values.get("decision"),
            "erreur": ERRORS.get(thread_id)}


@app.post("/missions/{thread_id}/decision")
async def decide(thread_id: str, body: DecisionIn):
    if thread_id in RUNNING:
        raise HTTPException(409, "La mission travaille encore")
    snapshot = await app.state.graph.aget_state(config_for(thread_id))
    if "approval" not in snapshot.next:
        raise HTTPException(409, "Cette mission n'attend pas d'approbation")
    launch(thread_id, Command(resume=body.decision))
    return {"thread_id": thread_id, "status": "en_cours"}

from fastapi.responses import FileResponse


@app.get("/")
async def home():
    """La page web de DevOps Copilot."""
    return FileResponse("static/index.html")
