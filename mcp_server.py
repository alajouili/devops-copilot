
import shutil
import subprocess
import tempfile

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("devops-tools")


def _run(command: list[str], yaml_text: str) -> tuple[int, str]:
    """Ecrit le YAML dans un fichier temporaire et lance une commande FIXE dessus."""
    if shutil.which(command[0]) is None:
        return 127, f"Outil '{command[0]}' non installe sur le serveur."
    with tempfile.TemporaryDirectory() as folder:
        path = f"{folder}/manifest.yaml"
        with open(path, "w") as f:
            f.write(yaml_text)
        result = subprocess.run(command + [path], capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr


@mcp.tool(description="Valide la SYNTAXE d'un manifest Kubernetes YAML avec kubeconform "
                      "(champs inconnus, mauvais types). A utiliser pour verifier qu'un YAML est correct.")
def validate_k8s_yaml(yaml_text: str) -> str:
    code, output = _run(["kubeconform", "-strict", "-summary"], yaml_text)
    return ("VALIDE\n" if code == 0 else "INVALIDE\n") + output


@mcp.tool(description="Analyse la SECURITE d'un manifest Kubernetes avec Trivy (mauvaises configurations : "
                      "conteneur root, privileges, pas de limites de ressources). A utiliser pour un audit de securite.")
def scan_k8s_security(yaml_text: str) -> str:
    code, output = _run(["trivy", "config", "--quiet", "--exit-code", "1", "--severity", "HIGH,CRITICAL"], yaml_text)
    if code == 0:
        return "SECURISE\nAucun probleme HIGH ou CRITICAL trouve."
    if code == 127:
        return output                       # Trivy n'est pas installe
    return "PROBLEMES DETECTES\n" + output

@mcp.tool()
def count_k8s_resources(yaml_text: str) -> str:
    """Compte le nombre de ressources Kubernetes (documents separes par ---) dans un YAML."""
    return f"{len([d for d in yaml_text.split('---') if d.strip()])} ressource(s)"


if __name__ == "__main__":
    mcp.run()   # transport "stdio" : le client lance ce programme et lui parle par l'entree/sortie standard