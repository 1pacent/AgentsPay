"""AgentPays Track C — Capability Index + A2A Crawler.

Usage:
  python main.py seed         # Initialize DB with 10 seed agents
  python main.py server       # Start HTTP API server
  python main.py query <cat>  # Quick CLI query
  python main.py crawl        # Live crawl from known endpoints
"""

import argparse
import logging
import sys

from capability_index import init_db, seed_database, query_by_category, CAPABILITY_CATEGORIES
from crawler import crawl_seed
from query_api import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("agentpays.cli")


def main():
    parser = argparse.ArgumentParser(description="Capability Index — AgentPays Track C")
    parser.add_argument("command", nargs="?", default="server",
                        choices=["seed", "server", "query", "crawl"])
    parser.add_argument("args", nargs="*", help="Additional arguments")
    parser.add_argument("--port", type=int, default=8080, help="Server port")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")

    args = parser.parse_args()

    if args.command == "seed":
        init_db()
        count = seed_database()
        print(f"Database seeded with {count} agents across {len(CAPABILITY_CATEGORIES)} categories")
        print(f"DB location: data/capability_index.db")
        return 0

    elif args.command == "server":
        init_db()
        print(f"Starting Capability Index API on {args.host}:{args.port}")
        print(f"Categories: {', '.join(CAPABILITY_CATEGORIES)}")
        serve(host=args.host, port=args.port)
        return 0

    elif args.command == "query":
        if not args.args:
            print("Usage: python main.py query <category> [max_price] [min_trust]")
            print(f"Categories: {', '.join(CAPABILITY_CATEGORIES)}")
            return 1

        category = args.args[0]
        max_price = float(args.args[1]) if len(args.args) > 1 else None
        min_trust = float(args.args[2]) if len(args.args) > 2 else None

        init_db()
        results = query_by_category(category, max_price=max_price, min_trust=min_trust)

        if not results:
            print(f"No agents found for category '{category}'")
            return 0

        print(f"Found {len(results)} agent(s) in category '{category}':")
        print()
        for i, agent in enumerate(results, 1):
            print(f"  {i}. {agent['name']} (${agent['price_min']:.4f}/call, trust: {agent['trust_score']:.2f})")
            print(f"     ID: {agent['agent_id']}")
            print(f"     Endpoint: {agent['endpoint_url']}")
            print()
        return 0

    elif args.command == "crawl":
        init_db()
        count = crawl_seed()
        print(f"Crawl complete. Database has {count}+ agents registered.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
