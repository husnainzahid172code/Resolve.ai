"""Run the Agent vs Traditional comparison from the terminal with live progress.

Usage (from backend/):  py -m scripts.run_comparison
Results are saved and appear on the admin "Agent vs Traditional" page.
With a free LLM tier this takes several minutes (it paces requests on purpose).
"""
from app.agents.planner import get_planner
from app.baseline.comparison import run_comparison
from app.database.db import init_db
from app.services import case_repository as repo


def main():
    init_db()
    planner = get_planner()
    print(f"Planner: {planner.name}. Running 9 scenarios...")
    results = run_comparison(planner, progress=lambda r: print(f"  {r['scenario_id']} {r['scenario']}: {r['result']}"))
    repo.save_comparison(planner.name, results)
    print("Saved. Open Admin -> Agent vs Traditional to see the table.")


if __name__ == "__main__":
    main()
