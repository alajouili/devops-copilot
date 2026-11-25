import sys

from copilot.rag import search

question = sys.argv[1] if len(sys.argv) > 1 else "Coment remplacer PodSecurityPolicy ?"

print(f"{question}\n")
for source, content, distance in search(question):
    print(f" {source}  (distance {distance:.3f})")
    print("   " + content[:250].replace("\n", " ") + "\n")