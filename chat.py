from llm import chat
SYSTEM = {"role": "system",
          "content": "Tu es DevOps Copilot, un assistant DevOps. Reponds en francais, de facon concise."}
MAX_MESSAGES = 20

history = [SYSTEM]
print("DevOps Copilot. Tapez 'quit' pour quitter.")

while True:
    question = input("\nVous : ").strip()
    if question.lower() in ("quit", "exit"):
        break
    if not question:
        continue

    history.append({"role": "user", "content": question})
    answer, provider, tokens = chat(history)
    history.append({"role":"assistant", "content": answer})

    print(f"\nCopilot [{provider}, {tokens} tokens] : {answer}")

    if len(history) > MAX_MESSAGES:                                 # ④ on garde le system + les derniers
        history = [SYSTEM] + history[-(MAX_MESSAGES - 1):]