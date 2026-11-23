"""Boucle d'agent reutilisable : LLM + outils MCP, jusqu'a la reponse finale."""
import json
from collections import Counter

from llm import complete_from

MAX_TOOL_CHARS = 1500        # taille maximale d'un resultat d'outil renvoye au LLM
MAX_CALLS_PER_TOOL = 3       # nombre maximal d'appels d'un meme outil par mission


def to_openai_tool(tool):
    """Traduit la fiche d'un outil MCP au format "tools" attendu par le LLM."""
    return {"type": "function",
            "function": {"name": tool.name, "description": tool.description,
                         "parameters": tool.input_schema}}


async def run_agent(session, system, user, max_tours=8, allowed=None):
    """Fait travailler un agent jusqu'a sa reponse finale.
    allowed : liste des outils autorises pour cet agent (None = tous).
    Le LLM ne voit QUE les outils autorises (Groq rejette toute la requete si le modele
    appelle un outil absent de la liste), et NOTRE code refuse quand meme les autres.
    Renvoie (reponse finale, nombre de tours, total de tokens consommes)."""
    tools = [to_openai_tool(t) for t in (await session.list_tools()).tools
             if allowed is None or t.name in allowed]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    total_tokens = 0
    calls = Counter()
    provider_index = 0   # une fois bascule sur le secours, on y reste jusqu'a la fin de la mission

    for tour in range(1, max_tours + 1):
        message, provider, tokens, provider_index = complete_from(messages, tools=tools,
                                                                  start=provider_index)
        total_tokens += tokens
        print(f"--- Tour {tour} [{provider}, {tokens} tokens]")

        if not message.tool_calls:
            return message.content, tour, total_tokens

        # model_dump garde TOUS les champs, dont extra_content (thought signature de Gemini 3)
        messages.append({
            "role": "assistant", "content": message.content or "",
            "tool_calls": [tc.model_dump(exclude_none=True) for tc in message.tool_calls],
        })
        for tc in message.tool_calls:
            name = tc.function.name
            calls[name] += 1
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if allowed is not None and name not in allowed:
                text = (f"REFUSED : l'outil {name} n'est pas autorise pour cet agent. "
                        "Un autre agent s'en charge. Continue sans lui.")
            elif calls[name] > MAX_CALLS_PER_TOOL:
                text = (f"LIMIT : tu as deja utilise {name} {MAX_CALLS_PER_TOOL} fois. "
                        "Arrete de l'utiliser et donne ta reponse finale maintenant.")
            elif not isinstance(args, dict):
                text = "ERROR : arguments JSON invalides. Reessaie avec un objet JSON valide."
            else:
                result = await session.call_tool(name, args)
                text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
                if len(text) > MAX_TOOL_CHARS:
                    text = text[:MAX_TOOL_CHARS] + "\n[... resultat tronque]"
            print(f"    [outil] {name} -> {text.splitlines()[0] if text else '(vide)'}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

    raise RuntimeError(f"L'agent n'a pas conclu en {max_tours} tours.")
