# T-RADAR

T-RADAR는 이미지·텍스트를 동시에 분석해 잠재적으로 충돌할 수 있는 선행상표를 빠르게 찾고, LangGraph 기반 AI Agent가 KIPRIS 자료를 바탕으로 등록 가능성과 대응 전략까지 제안해 주는 멀티모달 상표 검색 레퍼런스입니다.

## 주요 특징
- **멀티모달 검색**: MetaCLIP2/DINOv2 임베딩과 OpenSearch BM25를 결합해 이미지와 텍스트 모두에서 유사 선행상표를 탐색합니다.
- **프롬프트 보조**: LLM이 생성한 유사어·프롬프트 해석을 통해 검색 의도를 정교하게 반영할 수 있습니다.
- **상품/서비스류 탐색**: 30만여 개 지정상품을 빠르게 찾아 체계적으로 선택할 수 있는 보조 패널을 제공합니다.
- **AI Agent 시뮬레이션**: KIPRIS 의견제출통지서·거절결정서를 자동 수집하고, `심사관 → 출원인 → 리포터 → 채점자` 에이전트가 충돌 위험도·보정 전략을 Markdown/JSON으로 요약합니다.
- **실시간 모니터링**: 시뮬레이션 단계(데이터 수집/분석)와 경과 시간을 UI에서 즉시 확인하고, 필요 시 작업을 취소할 수 있습니다.

## 제품 한눈에 살펴보기
```
사용자 입력 (이미지, 상표명)
        │
        ▼
  FastAPI /search           ── 멀티모달 검색 결과
        │
        └─ /simulation       ── AI Agent 기반 위험 평가
```
- 검색 카드에서 상표를 선택하면 우측 패널에서 AI Agent가 해당 선행상표와의 충돌 가능성을 요약해 보여 줍니다.
- 모든 후보를 합산한 "전체 요약 / 선행상표별 핵심 위험 / 권고" 섹션과, 후보별 세부 대화·점수를 동시에 확인할 수 있습니다.

## 빠르게 시작하기
프로젝트 구성, 의존성 설치, 데이터 시딩, Docker 사용법 등 개발 관련 내용은 [`README_dev.md`](README_dev.md)에서 단계별로 안내합니다. 아래는 가장 기본적인 실행 순서입니다.

1. 저장소를 클론하고 `README_dev.md`에 따라 데이터베이스 및 OpenSearch를 초기화합니다.
2. `frontend/`에서 `npm install && npm run build`로 정적 자산을 만든 뒤, `bash scripts/run_api.sh`로 FastAPI 서버를 실행합니다.
3. 브라우저에서 `http://localhost:8000`을 열면 검색 + 시뮬레이션 UI를 바로 체험할 수 있습니다.

## 문서 / 더 알아보기
- [`README_dev.md`](README_dev.md) — 전체 아키텍처, 배포, 데이터 시딩, 환경 변수 정리
- [`markdown/search-pipeline.md`](markdown/search-pipeline.md) — 검색 파이프라인 상세와 응답 스키마
- [`markdown/agent_simulation.md`](markdown/agent_simulation.md) — LangGraph 에이전트 설계 및 시뮬레이션 흐름
- [`markdown/frontend.md`](markdown/frontend.md) — 프런트엔드 구조 및 API 연동 가이드

## 라이선스
별도 고지가 없는 한 회사 내부 용도로만 사용됩니다.
