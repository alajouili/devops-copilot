"""Teste les fournisseurs LLM configures dans .env : Groq, Gemini, Mistral.

Usage : python check_providers.py

Les cles API ne sont JAMAIS affichees : on indique seulement si elles sont
presentes, et tout message d'erreur est nettoye avant affichage.
"""
import os
import re
import sys
import time

from dotenv import load_dotenv
from openai import OpenAI  # client brut, sans trace Langfuse

load_dotenv()

TIMEOUT = 60  # secondes par requete (les modeles "thinking" sont lents)

PROVIDERS = [
    {"name": "groq", "key_var": "GROQ_API_KEY", "model_var": "GROQ_MODEL",
     "base_url": "https://api.groq.com/openai/v1"},
    {"name": "gemini", "key_var": "GEMINI_API_KEY", "model_var": "GEMINI_MODEL",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
    {"name": "mistral", "key_var": "MISTRAL_API_KEY", "model_var": "MISTRAL_MODEL",
     "base_url": "https://api.mistral.ai/v1"},
]

# Motifs ressemblant a des cles (gsk_..., AIza..., sk-..., longues suites alphanumeriques)
KEY_PATTERN = re.compile(r"(gsk_|AIza|sk-)[A-Za-z0-9_\-]+|[A-Za-z0-9_\-]{32,}")


def redact(text, secrets):
    """Retire toute trace de cle d'un message, puis force l'ASCII."""
    for s in secrets:
        if s:
            text = text.replace(s, "***")
            if len(s) > 8:
                # certaines API renvoient seulement le debut ou la fin de la cle
                text = text.replace(s[:8], "***").replace(s[-6:], "***")
    text = KEY_PATTERN.sub("***", text)
    text = text.encode("ascii", "replace").decode("ascii")
    return text[:200]


def check(p, secrets):
    key = os.getenv(p["key_var"], "").strip()
    model = os.getenv(p["model_var"], "").strip()
    print("[%s]" % p["name"])
    print("  %-16s : %s" % (p["key_var"], "presente" if key else "ABSENTE"))
    print("  %-16s : %s" % (p["model_var"], model if model else "ABSENT"))
    if not key or not model:
        print("  resultat         : IGNORE (configuration incomplete)")
        return None

    client = OpenAI(api_key=key, base_url=p["base_url"], timeout=TIMEOUT, max_retries=0)
    start = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: OK"}],
            max_tokens=256,  # les modeles a raisonnement consomment des tokens avant de repondre
            temperature=0,
        )
        elapsed = time.time() - start
        answer = (resp.choices[0].message.content or "").strip()
        print("  resultat         : OK (%.1fs) -> %s" % (elapsed, redact(answer, secrets)[:40]))
        return True
    except Exception as e:  # on veut un diagnostic, quelle que soit l'erreur
        elapsed = time.time() - start
        status = getattr(e, "status_code", None)
        label = type(e).__name__ + (" %s" % status if status else "")
        print("  resultat         : ECHEC (%.1fs) %s" % (elapsed, label))
        print("  detail           : %s" % redact(str(e), secrets))
        return False


def main():
    secrets = [os.getenv(p["key_var"], "").strip() for p in PROVIDERS]
    results = {}
    for p in PROVIDERS:
        results[p["name"]] = check(p, secrets)
        print()

    ok = [n for n, r in results.items() if r is True]
    ko = [n for n, r in results.items() if r is False]
    skipped = [n for n, r in results.items() if r is None]
    print("Resume : OK=%s  ECHEC=%s  IGNORE=%s" % (
        ",".join(ok) or "-", ",".join(ko) or "-", ",".join(skipped) or "-"))
    sys.exit(0 if ok and not ko else 1)


if __name__ == "__main__":
    main()
