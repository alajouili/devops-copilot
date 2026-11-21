"""RAG : decouper des documents, les transformer en vecteurs, et chercher par le sens."""
import os
import re
import time

import psycopg
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
EMBEDDING_MODEL = os.getenv("EMBEDDING", "gemini-embedding-001")
embedder = OpenAI(api_key=os.getenv("GEMINI_API_KEY"),
                  base_url="https://generativelanguage.googleapis.com/v1beta/openai/")


def embed(texts: list[str]) -> list[list[float]]:
    for attempt in range(5):
        try:
            response = embedder.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            return [item.embedding for item in response.data]
        except RateLimitError:
            print("    Quota d'embeddings atteint, pause de 30 s")
            time.sleep(30)
    raise RuntimeError("Impossible de calculer les embeddings (quota).")
 

def to_pgvector(vector: list[float]) -> str:
    return "[" + ",".join(str(x) for x in vector) + "]"

def clean_markdown(text: str) -> str:
    """Retire l'en-tete et les balises du site Kubernetes (Hugo), inutiles pour le sens."""
    text = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)      # en-tete YAML
    text = re.sub(r"\{\{[<%].*?[%>]\}\}", "", text)                  # balises {{< ... >}}
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)           # commentaires HTML
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Decoupe un texte en morceaux d'environ `size` caracteres, qui se chevauchent un peu."""
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):                       # couper de preference a la fin d'un paragraphe
            cut = text.rfind("\n\n", start + size // 2, end)
            if cut != -1:
                end = cut
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return [c for c in chunks if len(c) > 50]


def connect():
    return psycopg.connect(DATABASE_URL, autocommit=True)


def init_db(dimensions: int):
    with connect() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id        SERIAL PRIMARY KEY,
                source    TEXT NOT NULL,
                content   TEXT NOT NULL,
                embedding vector({dimensions}) NOT NULL
            )""")


def search(question: str, k: int = 4) -> list[tuple[str, str, float]]:
    """Renvoie les k morceaux les plus proches PAR LE SENS : (source, contenu, distance)."""
    query_vector = to_pgvector(embed([question])[0])
    with connect() as conn:
        rows = conn.execute(
            """SELECT source, content, embedding <=> %s::vector AS distance
               FROM chunks ORDER BY distance LIMIT %s""",
            (query_vector, k),
        ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


