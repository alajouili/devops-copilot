
import os
import shutil
import subprocess
import yaml
import tempfile
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
from rag import search
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


# Schemas des CRD courants (ServiceMonitor, PrometheusRule, Certificate, ...) :
# catalogue communautaire datreeio/CRDs-catalog, en plus des schemas Kubernetes officiels.
CRD_CATALOG = ("https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/"
               "{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json")
KUBECONFORM_CACHE = os.path.join(tempfile.gettempdir(), "kubeconform-cache")


@mcp.tool(description="Valide la SYNTAXE d'un manifest Kubernetes YAML avec kubeconform "
                      "(champs inconnus, mauvais types), y compris les CRD courants "
                      "(ServiceMonitor, PrometheusRule, Certificate...). "
                      "A utiliser pour verifier qu'un YAML est correct.")
def validate_k8s_yaml(yaml_text: str) -> str:
    os.makedirs(KUBECONFORM_CACHE, exist_ok=True)
    # 1) schemas officiels, 2) catalogue CRD, 3) sinon on saute la ressource
    #    (-ignore-missing-schemas) mais on le SIGNALE dans la sortie.
    code, output = _run(["kubeconform", "-strict", "-summary", "-verbose",
                         "-cache", KUBECONFORM_CACHE,
                         "-schema-location", "default", "-schema-location", CRD_CATALOG,
                         "-ignore-missing-schemas"], yaml_text)
    if code == 127:
        return output                       # kubeconform n'est pas installe
    lines, skipped = [], []
    for line in output.splitlines():
        line = line.split("manifest.yaml - ", 1)[-1]   # retire le chemin du fichier temporaire
        if line.endswith(" is valid"):
            continue                        # on ne garde que l'utile : erreurs et resume
        if line.endswith(" skipped"):
            name, _, kind = line.removesuffix(" skipped").rpartition(" ")
            skipped.append(f"{kind} {name}".strip())
            continue
        lines.append(line)
    if skipped:
        lines.insert(0, "ATTENTION : aucun schema trouve (ni officiel ni dans le catalogue CRD) pour : "
                        + ", ".join(skipped) + ". Ces ressources n'ont PAS ete verifiees "
                        "(-ignore-missing-schemas).")
    return ("VALIDE\n" if code == 0 else "INVALIDE\n") + "\n".join(lines)


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

@mcp.tool(description="Cherche dans la documentation OFFICIELLE et A JOUR de Kubernetes. "
                      "A utiliser AVANT d'ecrire un manifest ou de recommander une fonctionnalite, "
                      "pour verifier qu'elle existe encore et comment l'utiliser aujourd'hui.")
def search_k8s_docs(question: str) -> str:
    results = search(question, k=3)
    if not results:
        return "Aucun document trouve."
    return "\n\n".join(f"[Source : {source} | distance {distance:.2f}]\n{content}"
                       for source, content, distance in results)

# Hypotheses de prix (ordre de grandeur AWS on-demand, a adapter)
PRICE_VCPU_HOUR = 0.04      # $ par vCPU et par heure
PRICE_GB_HOUR = 0.005       # $ par Go de RAM et par heure
HOURS_PER_MONTH = 730


def _cpu(value) -> float:
    """'250m'  0.25 ; '1'  1.0"""
    value = str(value)
    return float(value[:-1]) / 1000 if value.endswith("m") else float(value)


def _memory_gb(value) -> float:
    """'256Mi'  0.25 ; '1Gi'  1.0 ; '512M'  0.5"""
    value = str(value)
    units = {"Ki": 1 / 1024 ** 2, "Mi": 1 / 1024, "Gi": 1, "K": 1e-6, "M": 1e-3, "G": 1}
    for unit, factor in units.items():
        if value.endswith(unit):
            return float(value[: -len(unit)]) * factor
    return float(value) / 1024 ** 3


@mcp.tool(description="Calcule les ressources demandees (CPU, memoire) d'un manifest Kubernetes "
                      "et estime son cout mensuel. A utiliser pour toute question de cout.")
def estimate_k8s_cost(yaml_text: str) -> str:
    total_cpu = total_mem = 0.0
    lines = []
    for doc in yaml.safe_load_all(yaml_text):
        if not doc or doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        replicas = doc.get("spec", {}).get("replicas", 1)
        containers = doc["spec"]["template"]["spec"].get("containers", [])
        cpu = sum(_cpu(c.get("resources", {}).get("requests", {}).get("cpu", 0)) for c in containers)
        mem = sum(_memory_gb(c.get("resources", {}).get("requests", {}).get("memory", 0)) for c in containers)
        total_cpu += cpu * replicas
        total_mem += mem * replicas
        lines.append(f"- {doc['kind']} {doc['metadata']['name']} : {replicas} replica(s)  "
                     f"{cpu:.2f} vCPU / {mem:.2f} Go")
    monthly = (total_cpu * PRICE_VCPU_HOUR + total_mem * PRICE_GB_HOUR) * HOURS_PER_MONTH
    lines.append(f"TOTAL demande : {total_cpu:.2f} vCPU, {total_mem:.2f} Go de RAM")
    lines.append(f"CoUt estime : {monthly:.2f} $ par mois "
                 f"(hypotheses : {PRICE_VCPU_HOUR} $/vCPU-h, {PRICE_GB_HOUR} $/Go-h, {HOURS_PER_MONTH} h/mois)")
    return "\n".join(lines)
if __name__ == "__main__":
    mcp.run()   # transport "stdio" : le client lance ce programme et lui parle par l'entree/sortie standard