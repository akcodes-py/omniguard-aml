"""NetworkX graph analytics per alert (Graph1 Node 1 output). In-process, no Neo4j.

Builds a directed multigraph of (src -> dst) edges from the alert-window
transactions and returns PRD Sec 4 core.graph_features row fields:
pagerank, betweenness, in/out degree of the alert account, is_in_cycle,
community_id, shortest_path_hr (hops to nearest high-risk node).
"""
from __future__ import annotations

import logging

import networkx as nx

_log = logging.getLogger(__name__)


def compute_graph_features(txs: list[dict], account_id: str, high_risk_accounts: set[str] | None = None) -> dict:
    high_risk_accounts = set(high_risk_accounts or set())
    g = nx.DiGraph()
    for r in txs:
        s, d = r.get("src_account"), r.get("dst_account")
        if s and d:
            g.add_edge(s, d)
    if account_id not in g:
        g.add_node(account_id)

    try:
        pr = nx.pagerank(g, max_iter=200)
    except Exception as exc:  # noqa: BLE001
        _log.debug("pagerank failed: %s", exc)
        pr = {n: 0.0 for n in g.nodes}
    try:
        bw = nx.betweenness_centrality(g)
    except Exception as exc:  # noqa: BLE001
        _log.debug("betweenness failed: %s", exc)
        bw = {n: 0.0 for n in g.nodes}
    try:
        cycles = list(nx.simple_cycles(g))
        in_cycle = any(account_id in c for c in cycles)
    except Exception as exc:  # noqa: BLE001
        _log.debug("simple_cycles failed: %s", exc)
        in_cycle = False
    try:
        comms = list(nx.weakly_connected_components(g.to_undirected())) if len(g) else []
        community_id = next((i for i, c in enumerate(comms) if account_id in c), 0)
    except Exception as exc:  # noqa: BLE001
        _log.debug("weakly_connected_components failed: %s", exc)
        community_id = 0
    # hops to nearest high-risk node (undirected distance)
    shortest = -1
    if high_risk_accounts:
        try:
            ug = g.to_undirected()
            dists = nx.single_source_shortest_path_length(ug, account_id)
            hits = [d for n, d in dists.items() if n in high_risk_accounts]
            shortest = min(hits) if hits else -1
        except Exception as exc:  # noqa: BLE001
            _log.debug("shortest_path failed: %s", exc)
            shortest = -1

    return {
        "pagerank": round(float(pr.get(account_id, 0.0)), 6),
        "betweenness": round(float(bw.get(account_id, 0.0)), 6),
        "in_degree": int(g.in_degree(account_id)),
        "out_degree": int(g.out_degree(account_id)),
        "is_in_cycle": bool(in_cycle),
        "community_id": int(community_id),
        "shortest_path_hr": int(shortest),
    }
