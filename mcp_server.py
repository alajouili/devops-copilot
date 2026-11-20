"""Serveur MCP "devops-tools" : expose des outils DevOps à n'importe quel agent compatible MCP."""
import shutil
import subprocess
import tempfile

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("devops-tools")


def _run(command: list[str], yaml_text: str) -> tuple[int, str]:
    """Écrit le YAML dans un fichier temporaire et lance une commande FIXE dessus."""
    if shutil.which(command[0]) is None:
        return 127, f"Outil '{command[0]}' non installé sur le serveur."
    with tempfile.TemporaryDirectory() as folder:
        path = f"{folder}/manifest.yaml"
        with open(path, "w") as f:
            f.write(yaml_text)
        result = subprocess.run(command + [path], capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr


@mcp.tool(description="Valide la SYNTAXE d'un manifest Kubernetes YAML avec kubeconform "
                      "(champs inconnus, mauvais types). À utiliser pour vérifier qu'un YAML est correct.")
def validate_k8s_yaml(yaml_text: str) -> str:
    code, output = _run(["kubeconform", "-strict", "-summary"], yaml_text)
    return ("VALIDE\n" if code == 0 else "INVALIDE\n") + output


@mcp.tool(description="Analyse la SÉCURITÉ d'un manifest Kubernetes avec Trivy (mauvaises configurations : "
                      "conteneur root, privilèges, pas de limites de ressources). À utiliser pour un audit de sécurité.")
def scan_k8s_security(yaml_text: str) -> str:
    code, output = _run(["trivy", "config", "--quiet", "--severity", "HIGH,CRITICAL"], yaml_text)
    return output or "Aucun problème HIGH ou CRITICAL trouvé."
@mcp.tool()
def count_k8s_resources(yaml_text: str) -> str:
    """Compte le nombre de ressources Kubernetes (documents séparés par ---) dans un YAML."""
    return f"{len([d for d in yaml_text.split('---') if d.strip()])} ressource(s)"


if __name__ == "__main__":
    mcp.run()   # transport "stdio" : le client lance ce programme et lui parle par l'entrée/sortie standard