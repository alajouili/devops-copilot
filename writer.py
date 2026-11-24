
"""Agent Writer : ecrit un manifest Kubernetes, le fait verifier et le corrige seul."""
import asyncio
import pathlib
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent import run_agent

_BASE = """Tu es l'agent Writer de DevOps Copilot, expert Kubernetes. Reponds en francais.
Ta mission : ecrire un manifest Kubernetes YAML qui repond exactement a la demande.

Regles de travail :
0. AVANT d'ecrire, utilise search_k8s_docs pour verifier comment faire avec la version actuelle de Kubernetes.
   Ne recommande jamais une fonctionnalite sans l'avoir verifiee dans la documentation.
@VERIFICATION@

Regles d'expertise :
- Jamais de tag :latest ; toujours une version precise.
- Pour nginx, utilise l'image nginxinc/nginx-unprivileged (elle tourne sans root, sur le port 8080).
- Si tu mets readOnlyRootFilesystem: true, monte un volume emptyDir sur /tmp.
- Toujours des requests et limits de ressources.

@FORMAT@"""

_FORMAT_FULL = """Format OBLIGATOIRE de ta reponse finale :
- un seul bloc ```yaml contenant le manifest final complet ;
- une section "Resultats des outils" : UNIQUEMENT ce que les outils ont reellement renvoye ;
- une section "Mes recommandations" : tes conseils personnels, clairement separes des resultats.
- une section "Sources consultees" : les fichiers de documentation que tu as utilises (noms des sources)."""

# Dans l'equipe, le manifest est repris AUTOMATIQUEMENT depuis le dernier appel VALIDE a
# validate_k8s_yaml : le recopier doublerait les tokens (limite Groq : 8000 par minute).
_FORMAT_TEAM = """Format OBLIGATOIRE de ta reponse finale (courte, 10 lignes maximum) :
- NE recopie PAS le manifest : il est repris automatiquement depuis ton dernier appel a
  validate_k8s_yaml. Ce dernier appel doit donc contenir le manifest COMPLET et avoir renvoye VALIDE.
- une section "Mes recommandations" : 3 conseils maximum ;
- une section "Sources consultees" : les noms des sources de documentation utilisees."""

# Writer seul : il verifie lui-meme la syntaxe ET la securite.
SYSTEM = _BASE.replace("@FORMAT@", _FORMAT_FULL).replace("@VERIFICATION@", """1. Ecris le YAML, puis verifie-le TOUJOURS avec validate_k8s_yaml ET scan_k8s_security.
2. Si un outil signale un probleme, corrige le YAML et reverifie avec les deux outils.
   Recommence jusqu'a ce que les deux soient OK.""")

# Writer dans l'equipe : la securite est le travail de l'agent Security.
# On ne nomme pas son outil, sinon le modele essaie de l'appeler.
TEAM_SYSTEM = _BASE.replace("@FORMAT@", _FORMAT_TEAM).replace("@VERIFICATION@", """1. Ecris le YAML, puis verifie-le TOUJOURS avec validate_k8s_yaml.
2. Si validate_k8s_yaml signale un probleme, corrige le YAML et reverifie.
   La securite est auditee ensuite par un autre agent : utilise uniquement tes propres outils.""")

DEFAULT_REQUEST = ("Un Deployment nginx securise avec 3 replicas, "
                   "et un Service ClusterIP qui expose le port 80 vers le port 8080 des pods.")


def extract_yaml(text: str) -> str | None:
    """Recupere le contenu du bloc ```yaml de la reponse."""
    match = re.search(r"```ya?ml\s*\n(.*?)```", text or "", re.DOTALL)
    return match.group(1).strip() if match else None


async def main():
    request = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REQUEST
    print(f" Demande : {request}\n")

    server = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            
            answer, tours, tokens = await run_agent(session, SYSTEM, request)
            print(f"\n Reponse de l'agent ({tours} tours, {tokens} tokens au total) :\n\n{answer}")

            
            yaml_text = extract_yaml(answer)
            if not yaml_text:
                print("\nAucun bloc ```yaml trouve dans la reponse.")
                return
            output = pathlib.Path("output/manifest.yaml")
            output.parent.mkdir(exist_ok=True)
            output.write_text(yaml_text + "\n")
            print(f"\n Manifest enregistre dans {output}")

            # Faire confiance, mais verifier" : NOTRE code reverifie le resultat final
            print("\n Verification independante du manifest final :")
            for tool in ("validate_k8s_yaml", "scan_k8s_security"):
                result = await session.call_tool(tool, {"yaml_text": yaml_text})
                text = "\n".join(c.text for c in result.content if hasattr(c, "text"))
                ok = text.startswith(("VALIDE", "SECURISE"))
                print(f"   {'bien' if ok else 'pas bien'} {tool}")

if __name__ == "__main__":
    asyncio.run(main())
