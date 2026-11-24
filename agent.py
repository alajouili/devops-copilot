"""Boucle d'agent reutilisable : LLM + outils MCP, jusqu'a la reponse finale."""
import json
import re
from collections import Counter

from llm import complete_from

MAX_TOOL_CHARS = 1500        # taille maximale d'un resultat d'outil renvoye au LLM
MAX_CALLS_PER_TOOL = 3       # nombre maximal d'appels d'un meme outil par mission
COMPACT_AT_CHARS = 12000     # au-dela (~3000 tokens d'historique), on compacte le passe
OLD_MANIFEST = "[ancienne version du manifest omise : la derniere version suit plus bas]"


def summarize(name, text):
    """Resume court d'un resultat d'outil, calcule sur le texte COMPLET (avant troncature)."""
    first = text.splitlines()[0] if text else "(vide)"
    if name == "validate_k8s_yaml":
        if first.startswith("VALIDE"):
            return "VALIDE (ancien resultat)"
        m = re.search(r"Invalid: (\d+), Errors: (\d+)", text)
        n = int(m.group(1)) + int(m.group(2)) if m else text.count(" is invalid") + text.count(" failed validation")
        return f"INVALIDE : {n} erreur(s) (ancien resultat, voir le dernier resultat)"
    if name == "search_k8s_docs":
        sources = sorted(set(re.findall(r"\[Source : ([^|\]]+)", text)))
        return ("[documentation deja lue, omise pour economiser le contexte. Sources : "
                + (", ".join(s.strip() for s in sources) or "aucune") + "]")
    return f"{first[:200]} (ancien resultat, detail omis)"


def _size(messages):
    total = 0
    for m in messages:
        total += len(m.get("content") or "")
        for tc in m.get("tool_calls") or []:
            total += len(tc.get("function", {}).get("arguments") or "")
    return total


def compact(messages, summaries):
    """Quand l'historique devient long, remplace le PASSE par des resumes courts :
    - les resultats d'outils des tours precedents -> resume (ex. "INVALIDE : 3 erreur(s)") ;
    - les anciens manifests passes en argument d'outil -> une phrase.
    On garde intacts : le prompt systeme, la tache, les resultats du dernier tour et
    le dernier manifest. La structure des messages (id des appels, extra_content avec
    la thought signature de Gemini) n'est jamais modifiee. Renvoie le nombre de caracteres gagnes."""
    before = _size(messages)
    if before <= COMPACT_AT_CHARS:
        return 0
    steps = [i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")]
    if len(steps) < 2:
        return 0
    last_step = steps[-1]

    # Le dernier appel d'outil qui portait un manifest (yaml_text) reste intact
    last_manifest = None
    for i in steps:
        for tc in messages[i]["tool_calls"]:
            if "yaml_text" in (tc.get("function", {}).get("arguments") or ""):
                last_manifest = tc.get("id")

    for i, m in enumerate(messages):
        if i >= last_step:
            break
        if m.get("role") == "tool" and m.get("tool_call_id") in summaries:
            m["content"] = summaries.pop(m["tool_call_id"])   # pop : chaque resultat n'est compacte qu'une fois
        elif m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                if tc.get("id") != last_manifest and "yaml_text" in (fn.get("arguments") or "") \
                        and OLD_MANIFEST not in fn["arguments"]:
                    fn["arguments"] = json.dumps({"yaml_text": OLD_MANIFEST})
    return before - _size(messages)


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
    summaries = {}       # tool_call_id -> resume court, utilise par compact()

    for tour in range(1, max_tours + 1):
        saved = compact(messages, summaries)
        if saved:
            print(f"    [contexte] historique compacte : -{saved} caracteres")
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
                summaries[tc.id] = summarize(name, text)
                if len(text) > MAX_TOOL_CHARS:
                    text = text[:MAX_TOOL_CHARS] + "\n[... resultat tronque]"
            print(f"    [outil] {name} -> {text.splitlines()[0] if text else '(vide)'}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

    raise RuntimeError(f"L'agent n'a pas conclu en {max_tours} tours.")
