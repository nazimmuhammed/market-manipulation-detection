from collections import defaultdict
from neo4j import GraphDatabase
from app.core.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

USE_MEMORY_GRAPH = False
driver = None

try:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
except Exception as e:
    print(f"Neo4j unavailable ({e}) — falling back to in-memory trader graph for this session.")
    USE_MEMORY_GRAPH = True
    driver = None

_mem_edges = defaultdict(float)


def init_constraints():
    if USE_MEMORY_GRAPH:
        print("In-memory graph fallback active (no Docker needed).")
        return
    with driver.session() as session:
        session.run("CREATE CONSTRAINT trader_id_unique IF NOT EXISTS FOR (t:Trader) REQUIRE t.trader_id IS UNIQUE")
    print("Neo4j constraint initialized.")


def write_trade_edges(trades):
    if len(trades) < 2:
        return
    if USE_MEMORY_GRAPH:
        for i in range(len(trades)):
            for j in range(i + 1, len(trades)):
                a, b = sorted((trades[i]["trader"], trades[j]["trader"]))
                _mem_edges[(a, b)] += 1
        return
    with driver.session() as session:
        for i in range(len(trades)):
            for j in range(i + 1, len(trades)):
                a, b = sorted((trades[i]["trader"], trades[j]["trader"]))
                session.run("""
                    MERGE (x:Trader {trader_id: $a})
                    MERGE (y:Trader {trader_id: $b})
                    MERGE (x)-[r:TRADED_WITH]->(y)
                    ON CREATE SET r.weight = 1
                    ON MATCH SET r.weight = r.weight + 1
                """, a=a, b=b)


def network_score_for_traders(trader_ids):
    if len(trader_ids) < 2:
        return 0.0
    if USE_MEMORY_GRAPH:
        trader_set = set(trader_ids)
        edge_count = sum(1 for (a, b) in _mem_edges if a in trader_set and b in trader_set)
        n = len(trader_ids)
        max_edges = n * (n - 1) / 2
        density = edge_count / max_edges if max_edges > 0 else 0.0
        return round(min(100.0, density * 100 * 1.5), 2)
    with driver.session() as session:
        result = session.run("""
            MATCH (a:Trader)-[r:TRADED_WITH]->(b:Trader)
            WHERE a.trader_id IN $traders AND b.trader_id IN $traders
            RETURN count(r) AS edge_count
        """, traders=list(trader_ids))
        edge_count = result.single()["edge_count"]
    n = len(trader_ids)
    max_edges = n * (n - 1) / 2
    density = edge_count / max_edges if max_edges > 0 else 0.0
    return round(min(100.0, density * 100 * 1.5), 2)


def get_all_trader_edges():
    if USE_MEMORY_GRAPH:
        return [{"source": a, "target": b, "weight": w} for (a, b), w in _mem_edges.items()]
    with driver.session() as session:
        result = session.run("MATCH (a:Trader)-[r:TRADED_WITH]->(b:Trader) RETURN a.trader_id AS source, b.trader_id AS target, r.weight AS weight LIMIT 200")
        return [dict(r) for r in result]


def detect_wash_trading(min_trades=3):
    if USE_MEMORY_GRAPH:
        degree = defaultdict(int)
        for (a, b) in _mem_edges:
            degree[a] += 1
            degree[b] += 1
        results = [
            {"trader_a": a, "trader_b": b, "pair_weight": w}
            for (a, b), w in _mem_edges.items()
            if w >= min_trades and degree[a] <= 2 and degree[b] <= 2
        ]
        return sorted(results, key=lambda x: -x["pair_weight"])
    with driver.session() as session:
        result = session.run("""
            MATCH (a:Trader)-[r:TRADED_WITH]->(b:Trader)
            WHERE r.weight >= $min_trades
            WITH a, b, r.weight AS pair_weight
            MATCH (a)-[r2:TRADED_WITH]-()
            WITH a, b, pair_weight, count(r2) AS a_edges
            MATCH (b)-[r3:TRADED_WITH]-()
            WITH a, b, pair_weight, a_edges, count(r3) AS b_edges
            WHERE a_edges <= 2 AND b_edges <= 2
            RETURN a.trader_id AS trader_a, b.trader_id AS trader_b, pair_weight
            ORDER BY pair_weight DESC
        """, min_trades=min_trades)
        return [dict(r) for r in result]