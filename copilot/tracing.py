"""Etape 7-C : regrouper les appels LLM par agent et par mission dans Langfuse."""
from langfuse import get_client, propagate_attributes

AGENT_NODES = ("planner", "writer", "security", "cost")


def traced(name, fn):
    """Enveloppe un noeud du graphe : tout ce qu'il fait devient un span nomme,
    rattache a la session de la mission (session_id = thread_id de LangGraph)."""
    async def wrapper(state, config):
        thread_id = (config or {}).get("configurable", {}).get("thread_id", "local")
        langfuse = get_client()
        with langfuse.start_as_current_observation(as_type="span", name=name) as span:
            with propagate_attributes(session_id=thread_id, tags=["devops-copilot", name]):
                result = await fn(state)
            span.update(output=result)
        return result
    return wrapper