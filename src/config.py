import os


NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

IFC_FILE_PATH = os.getenv("IFC_FILE_PATH", "")
EMBEDDINGS_MODEL_PATH = os.getenv("EMBEDDINGS_MODEL_PATH", "")


def validate_config() -> None:
    """Validate required runtime configuration before execution."""
    required = {
        "NEO4J_PASSWORD": NEO4J_PASSWORD,
        "IFC_FILE_PATH": IFC_FILE_PATH,
        "EMBEDDINGS_MODEL_PATH": EMBEDDINGS_MODEL_PATH,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            "Missing required configuration values: "
            + ", ".join(missing)
        )
