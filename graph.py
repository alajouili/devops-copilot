import asyncio
import json
import os
import re
import sys
from typing import TypedDict

import yaml

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent import run_agent
from tracing import AGENT_NODES, traced
from team import COST_SYSTEM, MAX_ESSAIS, PLANNER_SYSTEM, SECURITY_SYSTEM
from writer import DEFAULT_REQUEST, TEAM_SYSTEM as WRITER_SYSTEM, extract_yaml



class State(TypedDict, total=False):
    request: str
    plan: dict
    manifest: str
    feedback: str
    essais: int
    verdict: dict
    cout: str
    decision: str
    hors_sujet: bool
    message: str

def parse_json(text):
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def manifest_vide(text):
    """Vrai si le manifest ne contient aucune ressource Kubernetes (aucun document avec "kind")."""
    if not (text or "").strip():
        return True
    try:
        docs = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return False        # du YAML casse n'est pas "vide" : Security le signalera
    return not any(isinstance(d, dict) and d.get("kind") for d in docs)


def title(name):
    print("\n" + "=" * 60 + f"\n[{name}]\n" + "=" * 60)


def build_graph(session, checkpointer=None):
    async def planner(state):
        title("PLANNER")
        answer, _, _ = await run_agent(session, PLANNER_SYSTEM, state["request"], allowed=["search_k8s_docs"])
        plan = parse_json(answer) or {"note": answer}
        print(json.dumps(plan, indent=2, ensure_ascii=True))
        return {"plan": plan, "essais": 0, "feedback": "", "hors_sujet": plan.get("hors_sujet") is True}

    def hors_sujet(state):
        raison = (state["plan"].get("raison") or "la demande ne concerne pas des ressources Kubernetes").rstrip(". ")
        message = (f"Demande hors sujet : {raison}. DevOps Copilot ne genere que des manifests "
                   "Kubernetes (Deployment, Service, Ingress...). Reformulez votre demande.")
        print(f"\n{message}")
        return {"message": message}

    async def writer(state):
        essai = state["essais"] + 1
        title(f"WRITER (essai {essai}/{MAX_ESSAIS})")
        task = (f"Demande : {state['request']}\n\n"
                f"Plan du Planner :\n{json.dumps(state['plan'], indent=2, ensure_ascii=True)}")
        if state.get("feedback"):
            task += f"\n\nL'agent Security a refuse la version precedente :\n{state['feedback']}\nCorrige ces problemes."
        answer, _, _ = await run_agent(session, WRITER_SYSTEM, task,
                                       allowed=["search_k8s_docs", "validate_k8s_yaml"])
        return {"manifest": extract_yaml(answer) or "", "essais": essai}
  
    async def security(state):
        title("SECURITY")
        if manifest_vide(state.get("manifest")):
            # Garde-fou : un manifest vide n'est jamais un succes (et ne coute aucun appel LLM)
            verdict = {"approuve": False,
                       "problemes": ["manifest vide : ta reponse ne contenait aucun bloc ```yaml "
                                     "avec des ressources Kubernetes. Fournis le manifest complet."],
                       "resume": "manifest vide"}
            print(json.dumps(verdict, indent=2, ensure_ascii=True))
            return {"verdict": verdict, "feedback": f"- {verdict['problemes'][0]}"}
        task = f"Verifie ce manifest :\n```yaml\n{state['manifest']}\n```"
        answer, _, _ = await run_agent(session, SECURITY_SYSTEM, task,
                                       allowed=["scan_k8s_security", "search_k8s_docs"])
        verdict = parse_json(answer) or {"approuve": False,
                                         "problemes": ["verdict illisible"], "resume": answer}
        print(json.dumps(verdict, indent=2, ensure_ascii=True))
        feedback = "\n".join(f"- {p}" for p in verdict.get("problemes", []))
        return {"verdict": verdict, "feedback": feedback}
 
    async def cost(state):
        title("COST")
        task = f"Estime le cout mensuel de ce manifest :\n```yaml\n{state['manifest']}\n```"
        answer, _, _ = await run_agent(session, COST_SYSTEM, task,
                                       allowed=["estimate_k8s_cost"])
        print(answer)
        return {"cout": answer}
   
    def approval(state):
        # PAUSE : le graphe sauvegarde son etat et rend la main.
        # A la reprise, interrupt() renvoie la valeur de Command(resume=...).
        decision = interrupt({"question": "Enregistrer ce manifest ? (o/n)",
                              "manifest": state["manifest"]})
        return {"decision": str(decision).strip().lower()}

    def save(state):
        os.makedirs("output", exist_ok=True)
        with open("output/manifest.yaml", "w") as f:
            f.write(state["manifest"])
        with open("output/rapport.md", "w") as f:
            f.write(f"# Rapport DevOps Copilot\n\n## Demande\n{state['request']}\n\n"
                    f"## Securite\n{state['verdict'].get('resume', '')}\n\n"
                    f"## Cout\n{state['cout']}\n")
        print("\nEnregistre : output/manifest.yaml et output/rapport.md")
        return {}

    def echec(state):
        print(f"\nEchec : Security a refuse {MAX_ESSAIS} versions. Derniers problemes :\n{state['feedback']}")
        return {}

    # ---------- Les aretes conditionnelles : (etat) -> nom du noeud suivant ----------

    def after_planner(state):
        return "hors_sujet" if state.get("hors_sujet") else "writer"

    def after_security(state):
        if state["verdict"].get("approuve") is True and not manifest_vide(state.get("manifest")):
            return "cost"
        if state["essais"] >= MAX_ESSAIS:
            return "echec"
        return "writer"

    def after_approval(state):
        return "save" if state["decision"].startswith("o") else END

    # ---------- Assemblage du graphe ----------

    g = StateGraph(State)
    for name, fn in [("planner", planner), ("writer", writer), ("security", security),
                     ("cost", cost), ("approval", approval), ("save", save), ("echec", echec),
                     ("hors_sujet", hors_sujet)]:
        g.add_node(name, traced(name, fn) if name in AGENT_NODES else fn)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", after_planner, {"writer": "writer", "hors_sujet": "hors_sujet"})
    g.add_edge("writer", "security")
    g.add_conditional_edges("security", after_security,
                            {"cost": "cost", "writer": "writer", "echec": "echec"})
    g.add_edge("cost", "approval")
    g.add_conditional_edges("approval", after_approval, {"save": "save", END: END})
    g.add_edge("save", END)
    g.add_edge("echec", END)
    g.add_edge("hors_sujet", END)

    return g.compile(checkpointer=checkpointer or InMemorySaver())


async def main(request):
    server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            graph = build_graph(session)
            config = {"configurable": {"thread_id": "mission-1"}}

            print(f"Demande : {request}")
            result = await graph.ainvoke({"request": request}, config)

            # Tant que le graphe est en pause, on demande a l'humain puis on reprend
            while "__interrupt__" in result:
                pause = result["__interrupt__"][0].value
                answer = input(f"\n{pause['question']} ")
                result = await graph.ainvoke(Command(resume=answer), config)

            if result.get("hors_sujet"):
                print(f"\nFin du graphe : {result.get('message')}")
                return
            print(f"\nFin du graphe. Essais du Writer : {result.get('essais')}, "
                  f"decision : {result.get('decision', '-')}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--draw":
        # Le dessin n'execute aucun noeud : pas besoin de session
        print(build_graph(None).get_graph().draw_mermaid())
    else:
        asyncio.run(main(" ".join(args) or DEFAULT_REQUEST))  