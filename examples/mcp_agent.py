"""Agent qui découvre ses outils via MCP au lieu de les avoir codés en dur."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from copilot.llm import complete

YAML = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: nginx:latest
          securityContext:
            privileged: true
"""


def to_openai_tool(tool):
    """Traduit la fiche d'un outil MCP au format "tools" attendu par le LLM."""
    return {"type": "function",
            "function": {"name": tool.name, "description": tool.description,
                         "parameters": tool.input_schema}}


async def main():
    server = StdioServerParameters(command=sys.executable, args=["-m", "copilot.mcp_server"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ① Découvrir les outils proposés par le serveur MCP
            tools = [to_openai_tool(t) for t in (await session.list_tools()).tools]
            print("Outils découverts :", [t["function"]["name"] for t in tools])

            messages = [
                {"role": "system", "content": "Tu es un expert Kubernetes et sécurité. Réponds en français. "
                                              "Vérifie la syntaxe ET la sécurité avec les outils avant de conclure."},
                {"role": "user", "content": f"Audite ce manifest :\n\n{YAML}"},
            ]

                        # ② LA BOUCLE D'AGENT
            MAX_TOURS = 6
            for tour in range(1, MAX_TOURS + 1):
                message, provider, tokens = complete(messages, tools=tools)
                print(f"\n--- Tour {tour} [{provider}, {tokens} tokens] ---")

                if not message.tool_calls:          # plus d'outil demandé → réponse finale
                    print(f"\n🤖 Audit :\n{message.content}")
                    break

                messages.append({
                    "role": "assistant", "content": message.content or "",
                    "tool_calls": [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                   for tc in message.tool_calls],
                })
                for tc in message.tool_calls:       # ③ exécuter chaque outil via MCP
                    print(f"🔧 Appel MCP : {tc.function.name}")
                    result = await session.call_tool(tc.function.name, json.loads(tc.function.arguments))
                    text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
                    print(f"📋 Résultat :\n{text[:1500]}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            else:
                print(f"\n⛔ Arrêt : plus de {MAX_TOURS} tours sans réponse finale.")
                for tc in message.tool_calls:
                    print(f"\n🔧 Appel MCP : {tc.function.name}")
                    result = await session.call_tool(tc.function.name, json.loads(tc.function.arguments))
                    text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
                    print(f"📋 Résultat :\n{text[:1500]}")
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})

                # ④ Le LLM rédige son audit
                message, provider, tokens = complete(messages, tools=tools)
                print(f"\n[{provider}, {tokens} tokens]")

            print(f"\n🤖 Audit :\n{message.content}")


asyncio.run(main())