# Frontend 구조 개요

## 상단 개요
- 루트 컴포넌트: `app/frontend/app.jsx`
- 상태: `selectedGroups`, `response`, `loading`, `error`
- 요청: `/search/multimodal` POST, `/goods/search` GET

## 주요 컴포넌트
### TrademarkSearchForm
- 상단 "상표 검색" 영역
- 입력: 상표명 텍스트, 이미지 업로드, 선택된 유사군/류 요약
- 제출 시 `k=20` 으로 고정하여 멀티모달 검색 요청
- 이미지 미리보기는 FileReader → Object URL 로 처리하며 컴포넌트 언마운트 시 정리

### GoodsSearchPanel
- 키워드 기반 상품/서비스류 추천 UI
- 입력: 검색어(예: "커피"), 최대 10개 류/유사군 블록 표시
- 각 블록: 접을 수 있는 `article`로 구성, `GoodsGroupList`가 체크박스·코드·설명을 수평 정렬
- 체크 상태는 상위 `selectedGroups` 객체에 `{ groupCode: { classCode, className, names } }` 형태로 저장

## 상태 흐름
1. `GoodsSearchPanel`에서 `/goods/search` 호출 → 필터링된 류(빈 그룹 제외)를 결과에 저장
2. 사용자가 체크 박스를 선택하면 `selectedGroups` 갱신, 이후 검색 요청 시 유사군/류 정보를 전송
3. `TrademarkSearchForm` 제출 → 중앙 상태에서 `/search/multimodal` 호출 → 응답을 `response` 로 보관
4. `ResultSection` 이 `response` 를 이미지/텍스트 유사 Top-K 로 나누어 카드 렌더링

## 스타일 가이드
- Pico.css 위에 `app/frontend/styles.css`로 커스텀
- `container` 폭을 `min(60vw, 960px)` 으로 제한하여 노션과 유사한 중앙 정렬 레이아웃 구성
- 검색 카드/드롭존/결과 그리드는 폭 축소에 맞춰 padding과 font-size 조정
- 유사군 리스트 항목은 CSS Grid (`grid-template-columns: auto max-content 1fr`) 로 정렬, `list-style` 제거

## 향후 작업 시 체크리스트
- 새 UI 추가 시 `markdown` 폴더 내 전용 문서 생성/업데이트
- `selectedGroups` 구조 또는 API 계약 변경 시 본 문서를 반드시 수정
- 새로운 검색 결과 뷰(예: 테이블, 비교차트)를 추가하면 레이아웃과 상태 흐름을 문서화
