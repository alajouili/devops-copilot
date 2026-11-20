import subprocess
import tempfile

def validate_k8s_yaml(yaml_text: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(yaml_text)
        path = f.name
    result = subprocess.run(
        ["kubeconform", "-strict", "-summary", path],
        capture_output=True, text=True, timeout=60,
    )
    status = "VALIDE" if result.returncode == 0 else "INVALIDE"
    return f"{status}\n{result.stdout}{result.stderr}"

TOOLS = [{
    "type": "function",
    "function": {
        "name": "validate_k8s_yaml",
        "description": "Valide un manifest Kubernetes YAML avec kubeconform. "
                       "Utilise-le dès qu'on te demande de vérifier du YAML Kubernetes.",
        "parameters": {
            "type": "object",
            "properties": {
                "yaml_text": {"type": "string", "description": "Le contenu YAML complet à valider"}
            },
            "required": ["yaml_text"],
        },
    },
}]

AVAILABLE = {"validate_k8s_yaml": validate_k8s_yaml}