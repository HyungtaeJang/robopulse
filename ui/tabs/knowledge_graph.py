import streamlit as st
import networkx as nx
import plotly.graph_objects as go

def render_tab_graph(is_live, get_graph_func):
    st.info("추출 단계: 뉴스 본문에서 기업, 기술, 관계를 추출하여 산업 지형도를 시각화합니다.")
    
    col_g1, col_g2 = st.columns([3, 1])
    
    with col_g1:
        G_full = get_graph_func(domain_key=st.session_state.selected_domain_key) if is_live else nx.DiGraph()
        
    with col_g2:
        st.markdown("### 그래프 필터")
        top_n = st.slider("최대 표시 노드 수", 10, 100, 30)
        
        node_options = ["전체 보기"] + (sorted(list(G_full.nodes())) if G_full else [])
        focus_node = st.selectbox("특정 노드 집중 보기", options=node_options, 
                                  help="선택한 노드와 직접 연결된 이웃들만 시각화합니다.")
        st.markdown("---")
        st.markdown("**범례 (Legend)**")
        st.markdown("🔵 기업 (Company)")
        st.markdown("🟠 기술 (Technology)")
        st.markdown("🟢 제품 (Product)")
        st.markdown("🔴 기관 (Institution)")

    with col_g1:
        if G_full.number_of_nodes() == 0:
            st.info("그래프 데이터가 없습니다.")
        else:
            # 상위 노드 또는 특정 노드 필터링
            if focus_node and focus_node != "전체 보기":
                neighbors = list(G_full.neighbors(focus_node)) + list(G_full.predecessors(focus_node))
                sub_nodes = set(neighbors + [focus_node])
                subG = G_full.subgraph(sub_nodes)
            else:
                nodes_sorted = sorted(G_full.nodes(data=True), key=lambda x: x[1].get("mention_count", 0), reverse=True)[:top_n]
                subG = G_full.subgraph([n[0] for n in nodes_sorted])

            pos = nx.spring_layout(subG, k=1.0, seed=42)
            color_map = {"company": "#4338ca", "technology": "#f97316", "product": "#22c55e", "institution": "#ef4444", "unknown": "#94a3b8"}
            translate_type = {"company": "기업", "technology": "기술", "product": "제품", "institution": "기관", "unknown": "기타"}

            # 엣지(관계선) 생성 및 툴팁을 위한 마커 추적
            edge_traces = []
            mid_x, mid_y, edge_hover_texts = [], [], []
            
            for edge in subG.edges(data=True):
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                weight = edge[2].get("weight", 1)
                preds = ", ".join(edge[2].get("predicates", []))
                
                # 가중치에 비례하여 두께(Width)를 다르게 선을 그림 (최대 5)
                lw = min(5.0, max(1.0, weight))
                edge_traces.append(go.Scatter(
                    x=[x0, x1, None], y=[y0, y1, None],
                    line=dict(width=lw, color='#CBD5E1' if weight == 1 else '#94A3B8'),
                    hoverinfo='none', mode='lines'
                ))
                
                # 정중앙 좌표 및 툴팁 텍스트 세팅
                mid_x.append((x0 + x1) / 2)
                mid_y.append((y0 + y1) / 2)
                edge_hover_texts.append(f"<b>{edge[0]} ↔ {edge[1]}</b><br>관계: {preds}<br>빈도: {weight}")

            # 엣지용 투명 툴팁 마커
            edge_tooltip_trace = go.Scatter(
                x=mid_x, y=mid_y,
                mode='markers',
                hoverinfo='text',
                hovertext=edge_hover_texts,
                marker=dict(size=12, color='rgba(0,0,0,0)'),
                showlegend=False
            )

            # 노드 생성
            node_x, node_y, node_colors, node_sizes, node_texts = [], [], [], [], []
            for node in subG.nodes():
                x, y = pos[node]
                node_x.append(x)
                node_y.append(y)
                attrs = subG.nodes[node]
                
                # LLM이 간혹 대문자(Company)로 출력할 경우를 대비해 소문자화
                ntype = str(attrs.get("type", "unknown")).strip().lower()
                
                mcount = attrs.get("mention_count", 1)
                kor_type = translate_type.get(ntype, "기타")
                degree = subG.degree(node)
                
                node_colors.append(color_map.get(ntype, color_map["unknown"]))
                node_sizes.append(max(15, min(65, 15 + mcount * 8)))
                node_texts.append(f"<b>{node}</b><br>분류: {kor_type}<br>연결 수: {degree}<br>언급 수: {mcount}")

            node_trace = go.Scatter(x=node_x, y=node_y, mode='markers+text', text=list(subG.nodes()), 
                                    textfont=dict(size=11, color='#1e293b'),
                                    textposition="top center", hoverinfo='text', hovertext=node_texts,
                                    marker=dict(color=node_colors, size=node_sizes, line_width=2, line_color='white'))

            fig = go.Figure(data=edge_traces + [edge_tooltip_trace, node_trace],
                         layout=go.Layout(showlegend=False, hovermode='closest', margin=dict(b=0, l=0, r=0, t=0),
                                          xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          height=600, plot_bgcolor='white'))
            st.plotly_chart(fig, use_container_width=True)
