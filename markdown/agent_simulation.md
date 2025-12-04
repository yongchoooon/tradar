# AI Agent 기반 상표 등록 시뮬레이션 구상

## 1. 시스템 개요 / 목표
- 기존 **T-RADAR** 검색 파이프라인(이미지/텍스트 유사검색, FastAPI + React, pgvector + OpenSearch)을 그대로 활용해 사용자 입력 상표의 Top-K 선행상표, 상태, 지정상품, 이미지·텍스트 유사도 등을 LLM Agent에게 컨텍스트로 제공한다.
- LangGraph 기반 멀티-Agent 워크플로를 구축해 "심사관 → 출원인 → 심사관(재응답) → 리포터 → 채점자" 대화 시뮬레이션을 자동화하고, 웹 UI에서 검색 결과와 함께 의견 교환 및 점수 요약을 노출한다.
- 검색 직후에는 이미지 검색 상위 5개, 텍스트 검색 상위 5개(총 10개)를 자동으로 "가장 위험한 선행상표" 영역에 표시만 하고, 사용자가 `시뮬레이션 실행` 버튼을 누르면 이 10개를 기본 값으로 일괄 시뮬레이션한다. 사용자가 필요 시 후보 목록을 편집해 최대 40개까지 선택할 수 있도록 하여 비용을 통제하면서도 추가 비교를 지원한다.
- 산출물: (1) LangGraph 플로우 정의 및 백엔드 서비스, (2) LLM 프롬프트·Agent 역할 정의, (3) 의견/거절 사유 요약 UI, (4) 채점 결과(등록 가능성, 침해 가능성 점수)를 반환하는 JSON API, (5) README 및 `markdown/agent_simulation.md` 등 운영 문서.

## 2. 에이전트 설계
- **심사관 Agent**: 입력 상표 + 유사 Top-K + 의견제출통지서/거절결정서 코퍼스에서 추출한 법조문·사례·문구를 참고해 거절 사유(외관/호칭/관념, 절대적/상대적)와 근거를 생성.
- **출원인 Agent**: 심사관 사유를 반박하거나 보정 제안(지정상품 축소, 사용 표장 설명 등)을 생성.
- **심사관 재응답 Agent**: 출원인 의견을 수용/반박으로 정리하고 최종 입장을 도출.
- **리포터 Agent**: 전체 대화를 항목화(쟁점, 법조항, 양측 주장, 수용 여부, 향후 조치)하고 사용자 친화적 텍스트/테이블로 요약.
- **채점자 Agent**: 리포터 요약 + 초기 데이터를 바탕으로 충돌 위험도(`conflict_score`), 등록 가능성(`register_score`), 참고 요인(`factors[]`)을 0~100점 범위로 산출하고 간단 코멘트를 제공합니다.

## 3. 파이프라인 / 프레임워크
- **LangGraph 추천**: `app/services/langgraph_orchestrator.py`에서 StateGraph를 정의해 `examiner → applicant → examiner_reply → reporter → scorer` 순서로 실행하며, 각 노드가 동일한 `AgentState` 딕셔너리를 공유합니다. 조건부 분기는 현재 사용하지 않지만, 필요 시 노드를 추가해 확장할 수 있습니다. CrewAI, AutoGen, Semantic Kernel 등의 대안도 있으나 Python 생태계 및 LangChain 호환성을 고려하면 LangGraph가 적합합니다.
- **실행 순서**
  1. 검색 API 호출
  2. 상위 N개 결과/메타데이터를 LangGraph 입력으로 전달
  3. 각 Agent가 LLM(GPT-4o-mini, Claude 등)을 호출해 응답 생성
  4. 결과 JSON/텍스트를 FastAPI 응답 및 프론트엔드 UI에 전달
- **메모리**: LangGraph Memory 노드 또는 외부 벡터 스토어에 심사관/출원인 발언을 저장하고, 리포터·채점자에게 전체 컨텍스트 제공.
- **프롬프트 구조**: 시스템 프롬프트에 법조항, 의견서 템플릿 구조, 의견제출통지서/거절결정서 API 응답에서 추출한 필드를 포함하며 사용자 입력/검색 결과를 템플릿화해 전달한다. 현재 구현은 LangGraph로 `심사관 → 출원인 → 심사관 재응답 → 리포터 → 채점자` 노드를 거쳐 대화/요약/위험 평가를 생성한다.

## 4. 필요 데이터 / 입력 요건
- **T-RADAR 검색 결과**: `application_number`, `title_korean/english`, `status`, `service_classes`, `goods_services`, `image_sim`, `text_sim`, `thumb_url`.
- **사용자 지정상품 선택**: 웹 UI에서 체크한 유사군 코드와 해당 그룹의 지정상품 이름 목록(최대 20개)을 그대로 전달해, LLM이 단순 코드가 아니라 실제 지정상품 설명을 참고할 수 있게 한다.
- **사용자 이미지/지정상품 상세 문자열**: `SimulationRequest`에는 Base64 인코딩한 사용자 업로드 이미지(`user_image_b64` + `user_image_mime`)와 선택한 지정상품 이름 모음(`user_goods_names`, SimulationEngine에서 최대 30개까지 사용)이 함께 전달되어 LangGraph 프롬프트에 그대로 녹아든다.
- **의견제출통지서 REST API**
  - 엔드포인트에서 송달정보(송달번호, 송달일, 제출기한), 서지정보(출원번호, 지정류, 출원인, 담당 심사관), 거절사유별 블록(법조항, 사유 요약, 적용 지정상품, 선행사례/표장)과 최소한의 안내 문구를 JSON으로 받는다.
- **거절결정서 REST API**
  - 송달/문서 정보, 결정 요약(거절 유지 여부, 적용 조항, 사유), 심판 안내, 문의처 정보를 JSON으로 제공한다.
- **추가 API/데이터 소스**
  - 선행사례 상세(예: 조항별 판례 요약) 호출용 API가 있다면 연동해 법조문 근거를 강화한다.
  - 지정상품 코드 ↔ 유사군 매핑은 기존 TSV 데이터를 사용하거나 별도 서비스가 있으면 그 API를 호출한다.
  - 상표 상태/심결 이력은 KIPRIS 등 외부 API를 통해 필요 시 가져온다.
- **LLM 컨텍스트용 구조화 예시**
  - `CaseEvidence`: `{조항, 근거문단, 선행상표 리스트(번호, 이미지 링크, 이유)}`
  - `ApplicantCounter`: `{주장 요지, 반박 포인트, 보정 제안}`
  - `ReporterSummary`: `{쟁점, 근거, 채점자 참고 메모}`
  - `Scores`: `{registrability_score, infringement_risk, reasoning}`
- **전처리**: REST API 응답을 캐싱/정규화하는 어댑터를 만들고, 송달정보/법조항/거절사유/선행사례 필드를 공통 스키마로 변환해 Agent 프롬프트에 일관되게 공급한다.
  - **필수 호출 세트 정리**
    - 의견제출통지서(OP): `rejectDecisionInfo`, `additionRejectInfo`, `examinationResultInfo`, `imageInfo`, `lastTransferDateInfo`. (없으면 빈 구조)
    - 거절결정서(RE): `rejectDecisionInfo`, `additionRejectInfo`, `examinationResultInfo`, `imageInfo`, `lastTransferDateInfo`.
    - 기타 메타 API(심사관/인명/서지/안내 등)는 시뮬레이션에는 사용하지 않으며 UI에서 원문 확인용으로만 유지한다.

## 5. Agent 워크플로 세부 단계
1. **Context Builder (SimulationEngine)**: 선택한 각 선행상표마다 사용자 상표명, 이미지/텍스트 중 어떤 후보인지, 선택한 상품류·유사군·지정상품 목록, KIPRIS 의견제출통지서/거절결정서 요약을 한 덩어리의 Markdown 텍스트로 정리해 LangGraph state의 `context` 필드에 넣습니다. 디버그 모드에서는 이 컨텍스트가 `logs/simulation_debug/<tag>_<app_no>_context.json`에 기록됩니다.
2. **Examiner Agent (`examiner`)**: 사용자 이미지/선행상표 이미지를 함께 주입하고, 거절사유 블록을 참고해 Markdown 형식으로 잠재적 충돌 이슈를 작성합니다. 외관/호칭/관념 및 지정상품 차이를 모두 언급하도록 프롬프트를 구성했습니다.
3. **Applicant Agent (`applicant`)**: 심사관의 주장에 대해 반박 논리·보정 전략을 Markdown으로 응답하며, 실제 거래 실정·지정상품 범위를 근거로 등록 가능성을 강조합니다.
4. **Examiner Rebuttal Agent (`examiner_reply`)**: 출원인의 주장 중 수용 가능한 부분과 추가 보정이 필요한 부분을 구분해 최종 입장을 제시합니다.
5. **Reporter Agent (`reporter`)**: 앞선 대화를 `# 한 줄 요약` + `## 주요 쟁점` 형식으로 정리합니다. 쟁점 목록은 항상 `1.`부터 시작하는 번호 목록이며 굵은 제목(**쟁점명**)과 최소 두 문장 이상의 설명을 포함합니다. Reporter Markdown은 그대로 `SimulationCandidateResult.reporter_markdown`에 저장됩니다.
6. **Scorer Agent (`scorer`)**: Reporter Markdown만을 입력으로 받아 첫 줄에 JSON `{"conflict_score", "register_score", "rationale", "factors"}`를 출력한 뒤 `## 판단 요약`, `## 평가 근거`, `## 권장 대응` 세 섹션을 불릿 목록으로 채웁니다. JSON은 파싱되어 `SimulationCandidateResult`의 점수 및 근거 필드로 저장되고, 나머지 Markdown은 UI 카드에 그대로 노출됩니다.

모든 후보의 평가가 끝나면 `LangGraphOrchestrator.summarize_overall()`이 평균 점수와 각 후보의 요약을 모아 별도의 Markdown(전체 요약/선행상표별 핵심 위험/권고)을 생성하며, 이 결과가 `SimulationResponse.overall_report`로 전달됩니다.

## 6. 필요한 작업 / 산출물
- LangGraph 프로젝트: `app/services/langgraph_orchestrator.py`에서 에이전트 그래프를 정의합니다.
- 데이터 연동: 의견제출통지서/거절결정서 REST API 클라이언트를 구현해 필요한 시점에 데이터를 조회·캐싱하고, 필요 시 사례 검색용 벡터 인덱스를 구성.
- 프롬프트 템플릿 및 법령 지식 베이스(`markdown/agent-prompts.md` 등).
- FastAPI 엔드포인트 `/simulation/run`: LangGraph 실행을 트리거하는 비동기 작업을 생성해 `job_id`를 반환하고, `/simulation/stream/{job_id}`(SSE) 또는 `/simulation/status/{job_id}`로 작업 상태/결과를 조회한다. 진행 상황은 `simulation` 로거로도 확인할 수 있다.
- 프론트엔드 UI: 심사관 vs 출원인 대화, 리포터 요약, 채점 카드 등을 표시하며 각 주장 하단에 인용된 선행상표/문서 링크를 노출해 Explainability를 유지합니다. 모든 후보 정보를 기반으로 생성된 `overall_report` Markdown(전체 한 줄 결론/평균 점수/후속 권고/선행상표별 한 줄 요약)이 패널 상단에 고정됩니다.
- 테스트: mock 상표 입력, deterministic LLM stub을 활용한 CI 검증.
- 문서: README 업데이트 및 워크플로/데이터 요구사항 설명.
- 디버그 모드: `시뮬레이션 실행(디버그)` 버튼을 누르면 후보별 `logs/simulation_debug/<timestamp>_<app_no>_context.json`(KIPRIS 정리)과 `..._llm.txt`(LLM 프롬프트/응답)가 생성된다.

## 7. 문서 유지
- README 및 `markdown/agent_simulation.md`를 최신 상태로 유지하고, Agent 그래프/데이터 스키마 변경 시 즉시 업데이트한다.
