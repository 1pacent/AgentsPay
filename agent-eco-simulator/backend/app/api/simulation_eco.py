"""
Flask API routes for the Phase 2 economic simulation.

Runs alongside the existing MiroFish simulation routes (simulation.py).
All economic simulation endpoints are prefixed /api/eco/.
"""

import threading
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

from ...engine.ledger import Ledger
from ...metrics.collector import MetricsCollector
from ...metrics.report import ReportGenerator, compare_scenarios
from ...simulation.runner import ScenarioComparison, SimulationRunner

eco_bp = Blueprint("eco", __name__, url_prefix="/api/eco")

# In-memory run registry (keyed by run_id)
_runs: dict[str, dict] = {}
_RESULTS_DIR = Path(__file__).parent.parent.parent / "simulation" / "results"
_RESULTS_DIR.mkdir(exist_ok=True)


@eco_bp.route("/scenarios", methods=["GET"])
def list_scenarios():
    scenarios_dir = Path(__file__).parent.parent.parent / "simulation" / "scenarios"
    scenarios = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        scenarios.append({
            "id": data.get("id"),
            "name": data.get("name"),
            "phase": data.get("phase"),
            "description": data.get("description", "").strip(),
            "test_question": data.get("test_question", "").strip(),
        })
    return jsonify({"scenarios": scenarios})


@eco_bp.route("/run", methods=["POST"])
def start_run():
    body = request.get_json() or {}
    scenario_id = body.get("scenario_id")
    if not scenario_id:
        return jsonify({"error": "scenario_id required"}), 400

    run_id = f"run_{uuid.uuid4().hex[:8]}"
    _runs[run_id] = {"status": "starting", "run_id": run_id, "scenario_id": scenario_id}

    def _run_bg():
        try:
            _runs[run_id]["status"] = "running"
            runner = SimulationRunner.from_scenario(
                scenario_id,
                agentpays_fee_pct=body.get("fee_pct", 0.005),
                reputation_algorithm=body.get("reputation_algorithm", "time_decayed"),
                validator_name=body.get("validator", "deterministic"),
            )
            result = runner.run(
                ticks=body.get("ticks"),
                verbose=False,
            )
            runner.close()
            _runs[run_id]["status"] = "complete"
            _runs[run_id]["result"] = {
                "metrics": result["metrics"],
                "agents": result["agents"],
                "ticks_run": result["ticks_run"],
                "elapsed_seconds": result["elapsed_seconds"],
            }
        except Exception as e:
            _runs[run_id]["status"] = "error"
            _runs[run_id]["error"] = str(e)

    thread = threading.Thread(target=_run_bg, daemon=True)
    thread.start()

    return jsonify({"run_id": run_id, "status": "starting"})


@eco_bp.route("/run/<run_id>", methods=["GET"])
def get_run_status(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return jsonify({"error": "run not found"}), 404
    return jsonify(run)


@eco_bp.route("/runs", methods=["GET"])
def list_runs():
    summary = [
        {
            "run_id": r["run_id"],
            "scenario_id": r["scenario_id"],
            "status": r["status"],
            "aehs": r.get("result", {}).get("metrics", {}).get("aehs"),
            "completion_rate": r.get("result", {}).get("metrics", {}).get("completion_rate"),
        }
        for r in _runs.values()
    ]
    return jsonify({"runs": summary})


@eco_bp.route("/metrics/<run_id>", methods=["GET"])
def get_metrics(run_id: str):
    run = _runs.get(run_id)
    if not run or run["status"] != "complete":
        return jsonify({"error": "run not complete"}), 404
    return jsonify(run["result"]["metrics"])


@eco_bp.route("/report/<run_id>", methods=["GET"])
def get_report(run_id: str):
    run = _runs.get(run_id)
    if not run or run["status"] != "complete":
        return jsonify({"error": "run not complete"}), 404
    # Find the result file
    result_files = sorted(_RESULTS_DIR.glob(f"{run['scenario_id']}_*.json"), reverse=True)
    if not result_files:
        return jsonify({"error": "result file not found"}), 404

    import json
    with open(result_files[0]) as f:
        full_result = json.load(f)

    # Load the ledger to generate report
    # Note: in production this would reference a persisted DB; for now use in-memory metrics
    report_md = f"# Report for run {run_id}\n\nMetrics: {json.dumps(run['result']['metrics'], indent=2)}"
    return jsonify({"run_id": run_id, "report_markdown": report_md, "metrics": run["result"]["metrics"]})


@eco_bp.route("/compare", methods=["POST"])
def compare_runs():
    body = request.get_json() or {}
    run_ids = body.get("run_ids", [])
    if len(run_ids) < 2:
        return jsonify({"error": "provide at least 2 run_ids to compare"}), 400

    results = []
    for rid in run_ids:
        run = _runs.get(rid)
        if run and run["status"] == "complete":
            results.append({
                "scenario_name": f"{run['scenario_id']} ({rid})",
                "metrics": run["result"]["metrics"],
            })

    if len(results) < 2:
        return jsonify({"error": "not enough completed runs to compare"}), 400

    table = compare_scenarios(results)
    return jsonify({"comparison_table": table, "runs_compared": len(results)})


@eco_bp.route("/personas", methods=["GET"])
def list_personas():
    personas_dir = Path(__file__).parent.parent.parent / "simulation" / "personas"
    result: dict[str, list] = {}
    for agent_type_dir in sorted(personas_dir.iterdir()):
        if agent_type_dir.is_dir():
            import yaml
            agents = []
            for path in sorted(agent_type_dir.glob("*.yaml")):
                with open(path) as f:
                    data = yaml.safe_load(f)
                agents.append({
                    "id": data.get("id"),
                    "display_name": data.get("display_name"),
                    "description": data.get("description", "").strip(),
                })
            result[agent_type_dir.name] = agents
    return jsonify({"personas": result})


@eco_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "agent-eco-simulator", "phase": 2})
