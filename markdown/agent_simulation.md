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
- **채점자 Agent**: 리포터 요약 + 초기 데이터를 바탕으로 등록 가능성, 침해 리스크, 대응 난이도 등을 100점 만점으로 점수화하고 간단 코멘트를 제공.

## 3. 파이프라인 / 프레임워크
- **LangGraph 추천**: 그래프 구조로 각 Agent 노드, 세션 메모리, 조건부 분기(예: 추가 라운드 필요 여부)를 유연하게 구성 가능. 필요한 경우 채점자 전에 "전략가" 등 보정 제안 전용 Agent를 끼워 넣거나 특정 조항 전담 Agent를 추가하는 식으로 그래프를 동적으로 확장할 수 있다. CrewAI, AutoGen, Semantic Kernel 등의 대안도 있으나 Python 생태계 및 LangChain 호환성을 고려하면 LangGraph가 적합.
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
1. **Preprocessor Node**: 사용자 상표 + 검색 결과 + (선택) API로 가져온 문서 스니펫을 LangGraph state에 저장.
2. **Examiner Agent**: 다음 요소를 프롬프트에 포함
   - 사용자 상표 이미지/설명
   - 상위 유사 상표 메타정보(비교표)
   - 의견제출통지서 API에서 받은 거절사유 블록(법조항별 예시)
   - 출력: 조항별 이슈, 심사관 코멘트, 선행상표 매핑
3. **Applicant Agent**: Examiner 출력에 기반하여 지정상품/서비스 차이, 발음/관념 비교, 선행사례와 차별성을 강조.
4. **Examiner Rebuttal Agent**: Applicant 응답을 평가, 수용/반박 구분 및 필요 시 보정 조건 제안.
5. **Reporter Agent**: 앞선 3턴을 요약하고 `issues: [{name, examiner, applicant, decision}]` 형태의 요약을 JSON/텍스트로 생성하며, 각 주장에 인용된 선행상표 ID·문서 출처 링크(API 원문 URL)를 명시해 Explainability를 유지한다.
6. **Scorer Agent**: Reporter 요약과 검색 점수, 사용자 상표 vs 선행상표 비교 컨텍스트, 선행상표 현재 상태를 기반으로 충돌 위험/등록 가능성 점수를 0~100 사이로 JSON으로 산출하고, 근거(`rationale`)와 참고 항목(`factors`)을 함께 반환한다. 휴리스틱 점수와 LLM 점수는 최종 점수 산출에 모두 사용되며 UI에도 노출된다.

## 6. 필요한 작업 / 산출물
- LangGraph 프로젝트: `app/agents/simulation.py` 등 Python 모듈과 설정 파일.
- 데이터 연동: 의견제출통지서/거절결정서 REST API 클라이언트를 구현해 필요한 시점에 데이터를 조회·캐싱하고, 필요 시 사례 검색용 벡터 인덱스를 구성.
- 프롬프트 템플릿 및 법령 지식 베이스(`markdown/agent-prompts.md` 등).
- FastAPI 엔드포인트 `/simulation/run`: LangGraph 실행을 트리거하는 비동기 작업을 생성해 `job_id`를 반환하고, `/simulation/stream/{job_id}`(SSE) 또는 `/simulation/status/{job_id}`로 작업 상태/결과를 조회한다. 진행 상황은 `simulation` 로거로도 확인할 수 있다.
- 프론트엔드 UI: 심사관 vs 출원인 대화, 리포터 요약, 채점 카드 등을 표시하며 각 주장 하단에 인용된 선행상표/문서 링크를 노출해 Explainability를 유지. 모든 후보 정보를 모아 추가 LLM이 최종 Markdown 요약(전체 한 줄 결론/평균 점수/후속 권고/선행상표별 한 줄 요약)을 생성하고, UI 상단에 고정된 형식으로 노출합니다.
- 테스트: mock 상표 입력, deterministic LLM stub을 활용한 CI 검증.
- 문서: README 업데이트 및 워크플로/데이터 요구사항 설명.
- 디버그 모드: `시뮬레이션 실행(디버그)` 버튼을 누르면 후보별 `logs/simulation_debug/<timestamp>_<app_no>_context.json`(KIPRIS 정리)과 `..._llm.txt`(LLM 프롬프트/응답)가 생성된다.

## 7. 문서 유지
- README 및 `markdown/agent_simulation.md`를 최신 상태로 유지하고, Agent 그래프/데이터 스키마 변경 시 즉시 업데이트한다.
