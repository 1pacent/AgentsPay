"""
Standalone eco-only Flask server for local testing.
Boots only the eco blueprint — no Neo4j or Ollama required.

Usage:
  cd agent-eco-simulator/backend
  python run_eco.py
"""

import importlib.util
import os
import sys

_BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BACKEND)

# Load simulation_eco directly to avoid triggering app/__init__.py
# (which pulls in openai/neo4j/oasis dependencies not needed here)
_spec = importlib.util.spec_from_file_location(
    "simulation_eco",
    os.path.join(_BACKEND, "app", "api", "simulation_eco.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
eco_bp = _mod.eco_bp

from flask import Flask
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

app.register_blueprint(eco_bp)

@app.route("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print(f"Eco server starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
