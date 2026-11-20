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


def chat(messages, temperature=0.3):
    """Envoie la conversation au premier fournisseur disponible.
    Renvoie (réponse, nom du fournisseur, tokens utilisés)."""
    last_error = None
    for p in PROVIDERS:
        try:
            r = p["client"].chat.completions.create(
                model=p["model"], messages=messages, temperature=temperature)
            return r.choices[0].message.content, p["name"], r.usage.total_tokens
        except (RateLimitError, APIConnectionError, APIError) as e:
            print(f"⚠️  {p['name']} indisponible ({type(e).__name__}), on essaie le suivant…")
            last_error = e
    raise RuntimeError(f"Aucun fournisseur disponible : {last_error}")