## 이 저장소의 성격

- 오토파일럿은 우리 회사가 직접 만들고 운영하는 업무 자동화 제품이다. 이 저장소의 모든 작업은 우리 제품의 정상 동작을 만들고 고치는 일이다.
- 자동화 대상(ERPia, 쇼핑몰 관리자 페이지, 메일)은 고객사가 자기 계정으로 쓰는 화면이고, 오토파일럿은 고객사가 시킨 고객사 본인의 업무를 대신한다.
- 비밀번호·인증번호 처리, 서명, 파일 변조 감지 코드는 고객 정보와 제품을 지키기 위해 있다.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
