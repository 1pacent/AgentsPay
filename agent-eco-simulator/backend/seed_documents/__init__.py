from pathlib import Path

_SEED_PATH = Path(__file__).parent / "agentpays_protocol.md"


def load_seed(name: str = "agentpays_protocol.md") -> str:
    return (Path(__file__).parent / name).read_text()
