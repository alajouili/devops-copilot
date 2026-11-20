import json
from llm import complete
from tools import TOOLS, AVAILABLE

BROKEN_YAML = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 3
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
          image: nginx:1.27
          ports:
            - containerPort: 80
"""

messages = [
    {"role": "system", "content": "Tu es un expert Kubernetes. Réponds en français. "
                                  "Vérifie toujours le YAML avec l'outil avant de conclure."},
    {"role": "user", "content": f"Ce YAML est-il correct ?\n\n{BROKEN_YAML}"},
]

# ① Premier appel : le LLM décide s'il a besoin d'un outil
message, provider, tokens = complete(messages, tools=TOOLS)
print(f"[{provider}, {tokens} tokens]")

if message.tool_calls:
    # On garde la demande du LLM dans l'historique
    messages.append({
        "role": "assistant",
        "content": message.content or "",
        "tool_calls": [{"id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                       for tc in message.tool_calls],
    })
    # ② On exécute chaque outil demandé
    for tc in message.tool_calls:
        name = tc.function.name
        args = json.loads(tc.function.arguments)
        print(f"\n🔧 Le LLM demande l'outil : {name}")
        if name not in AVAILABLE:
            result = f"Outil inconnu : {name}"
        else:
            result = AVAILABLE[name](**args)
        print(f"📋 Résultat :\n{result}")
        # ③ On renvoie le résultat au LLM
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    # ④ Deuxième appel : le LLM explique le résultat
    message, provider, tokens = complete(messages, tools=TOOLS)
    print(f"\n[{provider}, {tokens} tokens]")

print(f"\n🤖 Réponse finale :\n{message.content}")