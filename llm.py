import os
from dotenv import load_dotenv
from openai import OpenAI, APIError, APIConnectionError, RateLimitError

load_dotenv()

# Les fournisseurs, dans l'ordre de préférence
PROVIDERS = []
if os.getenv("GROQ_API_KEY"):
    PROVIDERS.append({
        "name": "groq",
        "client": OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1"),
        "model": os.getenv("GROQ_MODEL"),
    })
if os.getenv("GEMINI_API_KEY"):
    PROVIDERS.append({
        "name": "gemini",
        "client": OpenAI(api_key=os.getenv("GEMINI_API_KEY"),
                         base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
        "model": os.getenv("GEMINI_MODEL"),
    })


def complete(messages, tools=None, temperature=0.2):
    """Appel brut : renvoie (message complet, fournisseur, tokens).
    Le message peut contenir du texte OU des demandes d'outils (tool_calls)."""
    last_error = None
    for p in PROVIDERS:
        try:
            kwargs = {"model": p["model"], "messages": messages, "temperature": temperature}
            if tools:
                kwargs["tools"] = tools
            r = p["client"].chat.completions.create(**kwargs)
            return r.choices[0].message, p["name"], r.usage.total_tokens
        except (RateLimitError, APIConnectionError, AuthenticationError, APIError) as e:
            print(f"⚠️  {p['name']} indisponible ({type(e).__name__}) : {e}")
            last_error = e
    raise RuntimeError(f"Aucun fournisseur disponible : {last_error}")


def chat(messages, temperature=0.3):
    """Version simple, pour du texte seulement (utilisée par chat.py)."""
    message, provider, tokens = complete(messages, temperature=temperature)
    return message.content, provider, tokens