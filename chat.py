from llm import chat

SYSTEM = {"role": "system",
          "content": "Tu es DevOps Copilot, un assistant DevOps. Réponds en français, de façon concise."}
MAX_MESSAGES = 20          # au-delà, on oublie les plus anciens

history = [SYSTEM]         # LA MÉMOIRE : une simple liste
print("DevOps Copilot. Tapez 'quit' pour quitter.")

while True:
    question = input("\nVous : ").strip()
    if question.lower() in ("quit", "exit"):
        break
    if not question:
        continue

    history.append({"role": "user", "content": question})          # ① on ajoute la question
    answer, provider, tokens = chat(history)                        # ② on envoie TOUT l'historique
    history.append({"role": "assistant", "content": answer})       # ③ on ajoute la réponse

    print(f"\nCopilot [{provider}, {tokens} tokens] : {answer}")

    if len(history) > MAX_MESSAGES:                                 # ④ on garde le system + les derniers
        history = [SYSTEM] + history[-(MAX_MESSAGES - 1):]