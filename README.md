# T-RADAR

T-RADAR는 상표 이미지와 명칭을 동시에 해석해 유사 선행상표를 탐색하고, KIPRIS 문서를 바탕으로 AI Agent가 충돌 가능성과 대응 방향을 요약하는 통합 상표 검색 시스템입니다. 단순 유사도 조회를 넘어, 검색 → 재검색 → 검토 → 시뮬레이션 → 리포트까지 한 화면에서 이어지는 흐름을 제공하며, 데이터 준비부터 운영 배포까지의 전체 설계를 포함합니다.

![메인 화면 스크린샷](figs/main.png)
<p align="center"><sub>메인 화면 스크린샷</sub></p>

## 시스템 한눈에
- **멀티모달 검색**: 이미지 임베딩(MetaCLIP2, DINOv2)과 텍스트 임베딩 + BM25를 결합해 유사 선행상표를 탐색합니다.
- **오프로딩 아키텍처**: ECS 백엔드는 `/ws/worker`로 데스크톱 GPU 워커에 검색 작업을 위임하고, 워커가 로컬 Postgres/OpenSearch에서 결과를 반환합니다.
- **의도 보정**: 프롬프트 재검색과 LLM 기반 유사어 확장으로 검색 의도를 더 정확히 반영합니다.
- **AI Agent 시뮬레이션**: KIPRIS 의견제출통지서/거절결정서를 바탕으로 다중 에이전트가 충돌 위험과 등록 가능성을 평가합니다.
- **상품/서비스류 탐색**: 대규모 지정상품 분류 데이터를 검색해 실제 출원 맥락을 반영합니다.
- **실행/운영 단위 구성**: 로컬 개발, Docker 실행, AWS 배포까지 전체 흐름을 문서화했습니다.

![시스템 파이프라인](figs/pipeline.png)
<p align="center"><sub>시스템 파이프라인 (생성: Gemini 3)</sub></p>

## 기술 스택
- **Backend**: FastAPI(Python 3.11), Uvicorn, httpx
- **AI Orchestration**: LangGraph + LangChain, OpenAI SDK
- **LLM**: gpt-4o-mini(유사어/프롬프트), gpt-5-nano(시뮬레이션)
- **Embedding**: MetaCLIP2, DINOv2 (Torch 기반 추론)
- **Vector/DB**: PostgreSQL + pgvector (임베딩/메타데이터 저장)
- **Search**: OpenSearch(BM25) + pgvector ANN
- **Frontend**: Vite + React SPA
- **Infra**: Docker/Docker Compose, AWS ECS/Fargate + ALB/CloudFront, S3, Desktop GPU Worker(WebSocket). (선택) 검색 인프라를 클라우드로 옮길 경우 RDS/OpenSearch Service 사용
- **Data Sources**: KIPRIS REST API, 상품/서비스류 TSV 데이터

## 사용 흐름
1. 상표 이미지와 명칭을 입력하고, 상품/서비스류와 유사군을 선택합니다.
2. 이미지 기반 결과와 텍스트 기반 결과가 동시에 제공되며, 상태/분류/유사도 정보를 카드로 확인합니다.
3. 검색 의도가 충분히 반영되지 않을 경우, 프롬프트를 추가해 재검색하거나 유사어 확장을 켜서 후보 폭을 조정합니다.
4. 우려되는 선행상표를 선택하고 시뮬레이션을 실행하면, KIPRIS 문서 수집 → 분석 → 요약 단계가 순차적으로 진행됩니다.
5. 전체 요약 리포트에서 평균 점수/핵심 위험/권고를 먼저 확인한 뒤, 개별 후보의 근거와 점수 세부를 검토합니다.
6. 필요 시 후보를 다시 조정해 재시뮬레이션하거나, 검색 결과로 돌아가 비교 대상을 확장합니다.

## 기능 동작 과정

### 검색 파이프라인
1. 사용자가 이미지/텍스트를 입력하면 각각 임베딩을 생성합니다.
2. 이미지 임베딩은 pgvector ANN으로 Top-N 후보를 찾고, 두 임베딩 공간의 유사도를 보정해 스코어를 통합합니다.
3. 텍스트는 유사어 확장(옵션)과 프롬프트 해석을 거쳐 임베딩을 만들고, pgvector와 OpenSearch BM25 결과를 합쳐 재정렬합니다.
4. 최종 Top-K를 반환하고, UI는 이미지/텍스트 결과를 별도 그리드로 보여줍니다.

### 시뮬레이션 파이프라인
1. 사용자가 선택한 후보 목록을 기준으로 백엔드가 시뮬레이션 작업을 생성합니다.
2. 각 후보에 대해 KIPRIS 의견제출통지서/거절결정서를 수집하고 요약 컨텍스트를 구성합니다.
3. LangGraph 기반 에이전트가 심사관↔출원인 대화를 시뮬레이션하고, 리포터/채점자가 요약과 점수를 생성합니다.
4. 후보별 결과를 집계해 전체 요약 리포트를 생성하고, UI에 실시간으로 전달합니다.

### UI 상호작용
1. 검색 결과는 카드와 페이지네이션으로 제공되며, 프롬프트 재검색으로 즉시 갱신됩니다.
2. 시뮬레이션 패널은 진행 단계와 경과 시간을 표시하고, 필요 시 실행을 중단할 수 있습니다.
3. 최종 리포트와 후보별 상세 근거를 한 화면에서 비교할 수 있습니다.

### 배포/운영 흐름
1. 백엔드는 컨테이너 이미지로 빌드해 ECS/Fargate에 배포합니다.
2. 프런트엔드는 정적 빌드 산출물을 S3에 업로드하고 CloudFront로 배포합니다.
3. **검색은 데스크톱 GPU 워커로 오프로딩**하며, 워커가 로컬 Postgres(pgvector) + OpenSearch 컨테이너에 연결해 결과를 생성합니다.
4. 이미지는 `/media/presign`으로 S3 presigned URL을 발급받아 업로드하고, `/search/multimodal`에는 `image_ref`만 전달합니다.
5. 환경 변수/시크릿은 외부 스토리지에서 주입하고, 로그로 비용과 품질을 추적합니다.

## 구성 요소

### 데이터
- 상표 메타데이터 JSON과 이미지 경로를 기준으로 검색 데이터베이스를 구축합니다.
- 2021년부터 2025년 10월까지의 상표 공보/거절 데이터를 수집했으며, KIPRIS Plus에서 구매하여 확보했습니다. (https://plus.kipris.or.kr/portal/main.do)
- 상품/서비스류 분류(약 30만 항목) TSV를 기반으로 검색 보조 패널을 구성합니다 (`app/data/goods_services/`).

### 검색
- 이미지 검색은 **DINOv2 + MetaCLIP2** 두 임베딩을 모두 생성해 pgvector ANN으로 Top‑N 후보를 찾고, 두 점수를 보정해 하나의 스코어로 통합합니다.
- 기본 가중치는 **DINO:MetaCLIP = 0.5:0.5**로 고정되며, 이미지 프롬프트 재검색 시 MetaCLIP 쿼리 벡터만 90/10 · 70/30 · 50/50 · 30/70 · 10/90 프리셋으로 가중치가 조정됩니다.
- 텍스트 검색은 **MetaCLIP2 임베딩 + OpenSearch BM25**를 함께 사용합니다. 임베딩 기반 ANN 후보와 BM25 후보를 합쳐 재정렬하고, 최종 Top‑K를 선정합니다.
- 텍스트 프롬프트 재검색은 LLM이 해석한 추가 키워드/필터를 적용해 재정렬하며, 유사어 확장은 후보 범위를 넓힐 때 사용합니다.
- 이미지/텍스트 결과는 별도 리스트로 제공되며, 상태(등록/공고/기타), 분류, 유사도, 썸네일 정보를 카드 형태로 보여 빠른 비교를 돕습니다.

### 시뮬레이션
- 심사관 → 출원인 → 심사관 재응답 → 리포터 → 채점자 흐름으로 평가를 진행해 실제 심사 흐름에 가까운 논리를 구성합니다.
- KIPRIS 의견제출통지서/거절결정서를 요약한 컨텍스트를 기반으로 충돌 위험도와 등록 가능성을 점수화합니다.
- 후보별 대화 요약과 점수 근거를 제공하고, 전체 후보를 종합한 리포트로 최종 판단에 필요한 핵심만 정리합니다.
- 진행 단계는 실시간으로 표시되며, 필요 시 실행을 중단하고 후보를 다시 선택할 수 있습니다.

### UI
- Vite + React 기반 단일 화면에서 검색과 시뮬레이션이 자연스럽게 이어지도록 구성했습니다.
- 검색 폼(이미지/텍스트), 상품·서비스류 탐색 패널, 결과 카드 그리드, 시뮬레이션 패널이 한 흐름으로 연결됩니다.
- 이미지/텍스트 결과를 동시에 비교하고, 프롬프트 재검색으로 즉시 결과를 갱신할 수 있습니다.
- 시뮬레이션 패널에서는 전체 요약과 후보별 세부 근거를 접기/펼치기 형태로 확인할 수 있습니다.

<table>
  <tr>
    <td align="center">
      <img src="figs/image_search_results.png" alt="이미지 검색 결과" width="100%">
      <br>
      <sub>이미지 검색 결과</sub>
    </td>
    <td align="center">
      <img src="figs/text_search_results.png" alt="텍스트 검색 결과" width="100%">
      <br>
      <sub>텍스트 검색 결과</sub>
    </td>
  </tr>
</table>

<table>
  <tr>
    <td align="center">
      <img src="figs/simulation_results.png" alt="시뮬레이션 결과" width="100%">
      <br>
      <sub>시뮬레이션 결과</sub>
    </td>
    <td align="center">
      <img src="figs/simulation_scores.png" alt="시뮬레이션 점수" width="100%">
      <br>
      <sub>시뮬레이션 점수</sub>
    </td>
  </tr>
</table>

### 배포/운영
- FastAPI 백엔드는 컨테이너로 배포하고, 프런트는 정적 빌드로 분리 배포합니다.
- 로컬에서는 Docker/Docker Compose로 DB·검색엔진·API·UI를 한 번에 구동할 수 있습니다.
- 운영 환경에서는 ECS/Fargate + S3/CloudFront + **데스크톱 GPU 워커(WebSocket)** 구성을 기준으로 설계되어 있습니다.
- 검색 인프라를 클라우드로 옮기고 싶다면 RDS/OpenSearch Service로 대체할 수 있습니다.
- 환경 변수와 시크릿은 외부 스토리지(예: Parameter Store)로 관리하며, 운영 환경에서는 필수 키가 없으면 서버가 기동되지 않습니다.
- LLM 사용량과 시뮬레이션 디버그 로그를 누적 기록해 비용과 품질을 추적할 수 있습니다.

### 로그/관측
- LLM 사용량 로그, 시뮬레이션 디버그 아티팩트, 타임라인 로그가 `logs/`에 저장됩니다.
- 운영 중 이슈 분석과 비용 추적을 위한 기본 관측 지표를 제공합니다.

## 문서
- `README_dev.md` — 개발/운영용 상세 가이드
- `markdown/search-pipeline.md` — 검색 파이프라인 상세
- `markdown/agent_simulation.md` — AI Agent 시뮬레이션 설계
- `markdown/frontend.md` — 프런트엔드 구조
- `markdown/tradar_setup_guide.md` — 로컬~AWS 배포 전체 가이드
- `markdown/tradar_cicd_guideline_by_chatgpt.md` — 인프라/CI-CD 개요

## 라이선스
별도 고지가 없는 한 국립부경대학교 산업AI연구실 내부 용도로만 사용됩니다.
