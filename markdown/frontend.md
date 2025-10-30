# Frontend 구조 개요

## 엔드포인트 요약
- 멀티모달 검색: `POST /search/multimodal`
- 상품/서비스류 추천: `GET /goods/search`
- 이미지 프록시: `GET /media?path=...`

## 루트 컴포넌트
- 파일: `app/frontend/app.jsx`
- 전역 상태: `selectedGroups`, `response`, `loading`, `error`
- 검색 요청 시 `k=20`으로 고정해 Top-K를 요청합니다.

## 주요 컴포넌트

### TrademarkSearchForm
- 상표명 텍스트와 이미지 업로드 입력 제공
- 선택된 유사군/류 요약을 보여 주지만 검색 점수에는 사용하지 않습니다.
- 제출 시 이미지 파일을 Base64 로 읽어 `/search/multimodal`에 전송

### GoodsSearchPanel
- 키워드로 유사군을 찾는 보조 UI
- 체크된 유사군은 `selectedGroups`에 저장되어 검색 요청에 포함됩니다 (응답 그룹핑에 사용)

### ResultSection / ResultCard
- `response.image_top`, `response.text_top`을 Top-10 카드 그리드로 렌더링하고, 상태가 `등록`/`공고`가 아닌 후보는 `image_misc`, `text_misc` 섹션에 노출
- 카드에는 출원번호, 상태 배지, 분류, DOI 링크(있는 경우), 이미지/텍스트 점수를 보여 주며 썸네일이 상단에 표시됩니다.

## 상태 흐름

1. 사용자가 유사군을 선택하면 `selectedGroups`가 갱신됩니다.
2. 상표명/이미지를 입력 후 검색하면 `loading` 상태로 전환 → 응답을 `response`에 저장
3. `ResultSection`은 이미지/텍스트 Top-10과 "기타"(등록/공고 외) 섹션을 렌더링합니다.
4. 오류 발생 시 `error` 메시지를 상단에 노출합니다.

## 스타일 가이드
- 기본 스타일은 Pico.css, 세부 커스터마이징은 `app/frontend/styles.css`
- 검색 폼, 드롭존, 결과 카드 모두 동일한 박스 그림자를 사용해 레이아웃 일관성 유지
- 반응형: 768px 이하에서는 결과 카드를 한 줄에 하나만 표시하도록 그리드 조정

## 변경 시 체크리스트
- `SearchResult` 필드가 바뀌면 이 문서와 `ResultCard` 렌더링 코드를 함께 수정합니다.
- 새로운 필터/옵션을 추가할 경우 `selectedGroups` 구조와 API 계약을 문서화합니다.
- 이미지 업로드 방식이나 미리보기 로직을 변경하면 메모리 관리(Blob URL 해제 등)도 검토하세요.
