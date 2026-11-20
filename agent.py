"""Boucle d'agent réutilisable : LLM + outils MCP, jusqu'à la réponse finale."""
import json

from llm import complete


def to_openai_tool(tool):
    """Traduit la fiche d'un outil MCP au format "tools" attendu par le LLM."""
    return {"type": "function",
            "function": {"name": tool.name, "description": tool.description,
                         "parameters": tool.input_schema}}


async def run_agent(session, system, user, max_tours=8):
    """Fait travailler un agent jusqu'à sa réponse finale.
    Renvoie (réponse finale, nombre de tours, total de tokens consommés)."""
    tools = [to_openai_tool(t) for t in (await session.list_tools()).tools]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    total_tokens = 0

    for tour in range(1, max_tours + 1):
        message, provider, tokens = complete(messages, tools=tools)
        total_tokens += tokens
        print(f"--- Tour {tour} [{provider}, {tokens} tokens]")

        if not message.tool_calls:
            return message.content, tour, total_tokens

        messages.append({
            "role": "assistant", "content": message.content or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                           for tc in message.tool_calls],
        })
        for tc in message.tool_calls:
            result = await session.call_tool(tc.function.name, json.loads(tc.function.arguments))
            text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
            print(f"    🔧 {tc.function.name} → {text.splitlines()[0] if text else '(vide)'}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

    raise RuntimeError(f"L'agent n'a pas conclu en {max_tours} tours.")