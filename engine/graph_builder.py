"""
engine/graph_builder.py
------------------------
분석된 엔티티와 관계를 NetworkX 지식 그래프로 구축합니다.
그래프는 메모리에 유지되며 Streamlit 시각화에 활용됩니다.
"""
import logging
from collections import defaultdict
from typing import Any, Optional

import networkx as nx

logger = logging.getLogger(__name__)

# ---- 전역 그래프 인스턴스 -----------------------------------
# 도메인별 격리 메모리 지식 그래프 관리
_knowledge_graphs: dict[str, nx.DiGraph] = {}


def get_graph(domain_key: str = "home_robot") -> nx.DiGraph:
    """특정 도메인의 DiGraph 인스턴스를 반환합니다."""
    if domain_key not in _knowledge_graphs:
        _knowledge_graphs[domain_key] = nx.DiGraph()
    return _knowledge_graphs[domain_key]


def add_analysis_to_graph(
    article_id: str,
    entities: list[dict],
    relations: list[dict],
    domain_key: str = "home_robot",
) -> None:
    """
    단일 기사의 분석 결과를 특정 도메인의 지식 그래프에 추가합니다.

    Args:
        article_id: 기사 고유 ID
        entities: [{"name": ..., "type": ...}, ...]
        relations: [{"subject": ..., "predicate": ..., "object": ...}, ...]
        domain_key: 도메인 식별 키
    """
    G = get_graph(domain_key)

    # 엔티티 노드 추가
    for entity in entities:
        name = entity.get("name", "").strip()
        if not name:
            continue
        if not G.has_node(name):
            G.add_node(name, type=entity.get("type", "unknown"), mention_count=0, articles=[])
        G.nodes[name]["mention_count"] += 1
        if article_id not in G.nodes[name]["articles"]:
            G.nodes[name]["articles"].append(article_id)

    # 관계 엣지 추가
    for rel in relations:
        subj = rel.get("subject", "").strip()
        pred = rel.get("predicate", "").strip()
        obj = rel.get("object", "").strip()
        if not (subj and pred and obj):
            continue

        # 노드가 없으면 자동 생성
        for node in [subj, obj]:
            if not G.has_node(node):
                G.add_node(node, type="unknown", mention_count=1, articles=[article_id])

        if G.has_edge(subj, obj):
            G[subj][obj]["weight"] += 1
            if pred not in G[subj][obj]["predicates"]:
                G[subj][obj]["predicates"].append(pred)
        else:
            G.add_edge(subj, obj, weight=1, predicates=[pred], articles=[article_id])

    logger.debug(f"[{domain_key}] 그래프 업데이트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")


def get_entity_stats(domain_key: str = "home_robot") -> list[dict]:
    """해당 도메인의 언급 횟수 기준 상위 엔티티 목록을 반환합니다."""
    G = get_graph(domain_key)
    stats = []
    for node, attrs in G.nodes(data=True):
        stats.append({
            "name": node,
            "type": attrs.get("type", "unknown"),
            "mention_count": attrs.get("mention_count", 0),
            "connection_count": G.degree(node),
        })
    return sorted(stats, key=lambda x: x["mention_count"], reverse=True)


def get_related_entities(entity_name: str, depth: int = 2, domain_key: str = "home_robot") -> dict:
    """특정 도메인의 특정 엔티티와 연결된 이웃 노드와 엣지를 반환합니다 (RAG 지원)."""
    G = get_graph(domain_key)
    if not G.has_node(entity_name):
        return {"nodes": [], "edges": []}

    # BFS로 depth 단계까지 탐색
    subgraph_nodes = set()
    queue = [(entity_name, 0)]
    while queue:
        node, d = queue.pop(0)
        if d > depth or node in subgraph_nodes:
            continue
        subgraph_nodes.add(node)
        for neighbor in list(G.successors(node)) + list(G.predecessors(node)):
            queue.append((neighbor, d + 1))

    sub = G.subgraph(subgraph_nodes)
    nodes = [{"id": n, **sub.nodes[n]} for n in sub.nodes]
    edges = [{"from": u, "to": v, **d} for u, v, d in sub.edges(data=True)]
    return {"nodes": nodes, "edges": edges}


def rebuild_from_db(db_relations: list[dict], domain_key: str = "home_robot") -> None:
    """
    애플리케이션 재시작 시 DB에 저장된 관계 데이터로 특정 도메인의 그래프를 재구성합니다.
    db_relations: [{"subject": ..., "predicate": ..., "object": ..., "article_id": ...}]
    """
    global _knowledge_graphs
    _knowledge_graphs[domain_key] = nx.DiGraph()
    for row in db_relations:
        add_analysis_to_graph(
            article_id=str(row.get("article_id", "")),
            entities=[
                {"name": row["subject"], "type": row.get("subj_type", "unknown")},
                {"name": row["object"], "type": row.get("obj_type", "unknown")},
            ],
            relations=[row],
            domain_key=domain_key,
        )
    logger.info(f"[{domain_key}] 그래프 재구성 완료: 노드 {_knowledge_graphs[domain_key].number_of_nodes()}개")
