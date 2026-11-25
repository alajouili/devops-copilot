"""Ingestion : lit la documentation, la decoupe, calcule les embeddings et remplit pgvector."""
import pathlib

from copilot.rag import chunk, clean_markdown, connect, embed, init_db, to_pgvector

DOCS = pathlib.Path("docs/k8s")
BATCH = 20

pieces = []
for path in sorted(DOCS.glob("*.md")):
    for part in chunk(clean_markdown(path.read_text())):
        pieces.append((path.name, part))

print(f" {len(list(DOCS.glob('*.md')))} documents  {len(pieces)} morceaux")

first = embed([pieces[0][1]])[0]

print(f" Chaque embedding contient {len(first)} nombres")
init_db(len(first))

with connect() as conn:
    conn.execute("TRUNCATE chunks")
    for i in range(0, len(pieces), BATCH):
        batch = pieces[i:i + BATCH]
        vectors = embed([text for _, text in batch])
        for (source, text), vector in zip(batch, vectors):
            conn.execute("INSERT INTO chunks (source, content, embedding) VALUES (%s, %s, %s::vector)",
                         (source, text, to_pgvector(vector)))
        print(f"    {min(i + BATCH, len(pieces))}/{len(pieces)}")
print(" Base de connaissances prete.")