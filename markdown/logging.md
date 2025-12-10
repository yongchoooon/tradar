# Logging & Debug Artifacts

이 문서는 AI Agent 시뮬레이션에서 생성되는 모든 로그/디버그 파일을 정리합니다. 각 로그는 `logs/` 디렉터리 하위에 저장되며, 운영 중 문제 분석이나 비용 모니터링에 사용됩니다.

## 1. LangGraph AI Agent 사용량 로그
- **경로**: `logs/openai_ai_agent_usage.csv`
- **기능**: `LangGraphOrchestrator._log_usage` (app/services/langgraph_orchestrator.py)
  - LLM 호출 시 토큰 사용량을 `usage_metadata`에서 추출하고, 모델별 요금표(`app/services/model_pricing.py`)를 이용해 비용을 계산합니다.
  - CSV 헤더: `timestamp, model, role, input_tokens, output_tokens, total_tokens, call_cost_usd, total_cost_usd`.
  - `_running_total`은 총 누적 비용이며 파일에도 함께 기록됩니다.

## 2. 시뮬레이션 디버그 아티팩트
`SimulationEngine`(app/services/simulation_engine.py)이 디버그 모드(`request.debug=True`)로 실행될 때 생성됩니다.

| 파일 | 생성 함수 | 설명 |
| --- | --- | --- |
| `logs/simulation_debug/<run_tag>/<run_tag>_<app_no>_context.json` | `_log_debug_context` | LLM에 전달된 컨텍스트(사용자 상표, 문서 등)와 KIPRIS 원문 요약을 저장합니다. |
| `logs/simulation_debug/<run_tag>/<run_tag>_<app_no>_llm.txt` | `_log_debug_llm` | LangGraph 노드의 전체 Prompt/Response 로그. `[role]`, `Prompt`, `Response` 블록으로 구성됩니다. |
| `logs/simulation_timeline/<run_tag>/<run_tag>_<app_no>_timeline.json` | `_log_timeline` | LangGraph 이벤트 타임라인(`start_time`, `end_time`, 토큰 사용 등)을 JSON 배열로 기록합니다. `_timeline_enabled`가 `True`일 때만 생성됩니다. |

> `run_tag`는 `SimulationEngine.run()` 호출 시 타임스탬프로 생성됩니다. `overall` 요약에도 동일한 로그 파일이 만들어집니다.

## 3. OpenAI Synonym Service 사용량 로그
- **경로**: `logs/openai_usage.csv`
- **기능**: `TrademarkLLMSynonymService._log_usage` (app/services/synonym_service.py)
  - 상표명 유사어를 생성할 때 OpenAI ChatCompletion 응답의 `usage` 필드에서 토큰 사용량을 읽어 CSV로 기록합니다.
  - CSV 헤더: `timestamp, model, input_tokens, output_tokens, total_tokens, input_cost_usd, output_cost_usd, total_cost_usd`.
  - 비용 계산 역시 `app/services/model_pricing.py`에 정의된 모델 요금표를 사용합니다.

## 4. 모델 요금표 (`app/services/model_pricing.py`)
- OpenAI 모델별 1M 토큰당 요금(입력·캐시된 입력·출력)을 정의한 딕셔너리입니다.
- `get_model_pricing(model_name)`를 호출하면 해당 모델의 요금이 반환되며, 위의 사용량 로그에서 사용됩니다.
- 미등록 모델은 `gpt-4o-mini` 요금을 기본값으로 사용합니다.

## 5. 기타 참고 사항
- 모든 로그 디렉터리는 코드에서 자동으로 생성합니다. 운영 환경에서 별도 설정 없이 사용 가능합니다.
- 로그 파일은 민감한 정보를 포함할 수 있으므로 접근 권한을 제한하고, 필요 시 회수/보관 정책을 적용하세요.
