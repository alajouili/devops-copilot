"""Le seul endroit qui parle aux LLM : Groq en premier, Gemini en secours."""
import copy
import os
import re
import time

from dotenv import load_dotenv
from openai import (OpenAI, APIError, APIConnectionError, AuthenticationError,
                    BadRequestError, RateLimitError)

load_dotenv()
from langfuse.openai import OpenAI  # meme client, mais chaque appel LLM est trace dans Langfuse

# Fail fast : un fournisseur lent ou en panne (503, timeout) ne doit pas bloquer
# une mission pendant 16 minutes. Chaque appel complete_from() a un BUDGET total :
# tous fournisseurs et toutes tentatives compris, il echoue en moins de 3 minutes.
REQUEST_TIMEOUT = 90   # secondes, timeout maximal d'une requete HTTP
SDK_RETRIES = 1        # nouvelles tentatives automatiques du SDK (429, 5xx, timeout)
CALL_BUDGET = 170      # secondes, duree maximale d'un appel complete_from()
MIN_SLICE = 15         # en dessous de ce temps restant, on n'essaie plus rien

# Les fournisseurs, dans l'ordre de preference
PROVIDERS = []
if os.getenv("GROQ_API_KEY"):
    PROVIDERS.append({
        "name": "groq",
        "client": OpenAI(api_key=os.getenv("GROQ_API_KEY"), base_url="https://api.groq.com/openai/v1",
                         timeout=REQUEST_TIMEOUT, max_retries=SDK_RETRIES),
        "model": os.getenv("GROQ_MODEL"),
    })
if os.getenv("GEMINI_API_KEY"):
    PROVIDERS.append({
        "name": "gemini",
        "client": OpenAI(api_key=os.getenv("GEMINI_API_KEY"),
                         base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                         timeout=REQUEST_TIMEOUT, max_retries=SDK_RETRIES),
        "model": os.getenv("GEMINI_MODEL"),
    })

MAX_ATTEMPTS = 2   # essais par fournisseur pour une erreur ponctuelle du modele
# Erreurs 400 de Groq causees par une sortie ratee du modele (nom d'outil invente,
# arguments JSON mal formes) : un nouvel essai suffit souvent.
FLAKY_400 = ("tool call validation failed", "failed to parse tool call")

# Limite par minute (TPM) : si le fournisseur dit "try again in 12.5s" et que ce delai
# est court, on attend sur place (dans le budget) au lieu de basculer tout de suite.
RATE_WAIT_MAX = 30     # secondes, attente maximale acceptee pour un 429
RATE_WAITS = 2         # nombre maximal d'attentes 429 par fournisseur et par appel


def _retry_after(e):
    """Delai demande par un 429 ("Please try again in 1m2.5s / 847.5ms"), en secondes, ou None."""
    m = re.search(r"try again in (?:(\d+)m)?([\d.]+)(ms|s)", str(e))
    if not m:
        return None
    value = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
    return int(m.group(1) or 0) * 60 + value


# Si TOUS les fournisseurs echouent pour une raison RESEAU (coupure passagere),
# on attend puis on refait un tour complet, au lieu de perdre toute la mission
# (seulement s'il reste assez de temps dans le budget CALL_BUDGET).
NETWORK_ROUNDS = 3
NETWORK_WAIT = 20   # secondes

# Gemini 3 : chaque etape d'appels d'outils porte une "thought signature"
# (tool_calls[i].extra_content.google.thought_signature) qu'il faut renvoyer telle quelle.
# Pour des appels d'outils produits par un AUTRE modele (ex. Groq avant une bascule),
# la documentation Gemini prevoit cette valeur factice pour sauter la verification.
DUMMY_SIGNATURE = "skip_thought_signature_validator"


def _prepare(messages, provider_name):
    """Adapte l'historique au fournisseur, sans modifier l'original."""
    messages = copy.deepcopy(messages)
    for m in messages:
        calls = m.get("tool_calls") if m.get("role") == "assistant" else None
        if not calls:
            continue
        if provider_name == "gemini":
            # Seul le 1er appel de chaque etape doit porter une signature.
            google = calls[0].setdefault("extra_content", {}).setdefault("google", {})
            google.setdefault("thought_signature", DUMMY_SIGNATURE)
        else:
            # Les autres fournisseurs ne connaissent pas ce champ propre a Gemini.
            for c in calls:
                c.pop("extra_content", None)
    return messages


def _report(p, e):
    detail = str(e).replace("\n", " ")[:300]
    if e.__cause__ is not None:      # la vraie cause technique (DNS, timeout...)
        detail += f" | cause : {e.__cause__!r}"[:200]
    print(f"[!] {p['name']} ({p['model']!r}) indisponible : {type(e).__name__}")
    print(f"    raison : {detail}")


def complete_from(messages, tools=None, temperature=0.2, start=0):
    """Appel brut : renvoie (message complet, fournisseur, tokens, index du fournisseur).
    start : index du premier fournisseur a essayer (pour rester sur le secours
    pendant toute une mission une fois qu'on y a bascule).
    Le message peut contenir du texte OU des demandes d'outils (tool_calls)."""
    last_error = None
    deadline = time.monotonic() + CALL_BUDGET
    for round_ in range(1, NETWORK_ROUNDS + 1):
        network_only = True
        for i in range(start, len(PROVIDERS)):
            p = PROVIDERS[i]
            prepared = _prepare(messages, p["name"])
            rate_waits = 0
            attempt = 0
            while attempt < MAX_ATTEMPTS:
                attempt += 1
                remaining = deadline - time.monotonic()
                if remaining < MIN_SLICE:
                    break
                # Partage equitable du temps restant entre ce fournisseur et les suivants,
                # puis entre l'essai et la tentative automatique du SDK.
                share = remaining / (len(PROVIDERS) - i)
                timeout = min(REQUEST_TIMEOUT, share / (1 + SDK_RETRIES))
                try:
                    kwargs = {"model": p["model"], "messages": prepared,
                              "temperature": temperature if attempt == 1 else min(temperature + 0.4, 1.0)}
                    if tools:
                        kwargs["tools"] = tools
                    client = p["client"].with_options(timeout=timeout)
                    r = client.chat.completions.create(**kwargs)
                    return r.choices[0].message, p["name"], r.usage.total_tokens, i
                except BadRequestError as e:
                    last_error = e
                    network_only = False
                    if attempt < MAX_ATTEMPTS and any(s in str(e).lower() for s in FLAKY_400):
                        print(f"[~] {p['name']} : appel d'outil invalide, on reessaie (essai {attempt + 1})")
                        continue
                    _report(p, e)
                    break
                except RateLimitError as e:
                    last_error = e
                    network_only = False
                    wait = _retry_after(e)
                    left = deadline - time.monotonic()
                    if (wait is not None and wait <= RATE_WAIT_MAX and rate_waits < RATE_WAITS
                            and left - wait - 1 >= MIN_SLICE):
                        rate_waits += 1
                        attempt -= 1            # une attente de quota n'est pas un echec du modele
                        print(f"[~] {p['name']} : limite de debit atteinte, on attend {wait + 1:.1f} s")
                        time.sleep(wait + 1)
                        continue
                    _report(p, e)
                    break
                except (APIConnectionError, AuthenticationError, APIError) as e:
                    # APITimeoutError est une sous-classe de APIConnectionError
                    last_error = e
                    network_only = network_only and isinstance(e, APIConnectionError)
                    _report(p, e)
                    break
        remaining = deadline - time.monotonic()
        if not network_only or round_ == NETWORK_ROUNDS or remaining < NETWORK_WAIT + MIN_SLICE:
            break
        print(f"[!] Probleme reseau sur tous les fournisseurs : nouvel essai dans {NETWORK_WAIT} s "
              f"({round_}/{NETWORK_ROUNDS - 1})")
        time.sleep(NETWORK_WAIT)
    if last_error is None:
        last_error = TimeoutError(f"budget de {CALL_BUDGET} s epuise")
    raise RuntimeError(f"Aucun fournisseur disponible : {last_error}")


def complete(messages, tools=None, temperature=0.2):
    """Comme complete_from, en partant du 1er fournisseur : renvoie (message, fournisseur, tokens)."""
    message, provider, tokens, _ = complete_from(messages, tools, temperature)
    return message, provider, tokens


def chat(messages, temperature=0.3):
    """Version simple, pour du texte seulement."""
    message, provider, tokens = complete(messages, temperature=temperature)
    return message.content, provider, tokens
