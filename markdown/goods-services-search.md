# 상품/서비스류 검색 문서

## 데이터 소스
- `app/data/goods_services/ko_goods_services.tsv`: 30만여 행, 컬럼 `nc_class`, `name_ko`, `similar_group_code`
- `app/data/goods_services/nice_classes_ko_compact.tsv`: 류 번호 ↔ 설명 매핑

## 서비스 구조 (`app/services/goods_search.py`)
1. TSV 로딩 시 `nc_class` → `ClassEntry` 매핑 생성
   - `ClassEntry` 는 류 이름, 토큰 세트, 유사군(`GroupEntry`) 집합을 보관
2. 각 `GroupEntry`
   - 동일 유사군/키워드 조합의 name 목록을 수집
   - 검색어 토큰과 부분 문자열 매칭된 이름만 결과에 포함
   - 최대 20개의 이름을 유지해 응답을 간결화
3. 검색 흐름
   - 입력 문자열을 토큰화한 뒤 해시 임베딩으로 쿼리 벡터를 구성합니다.
   - **유사군(group)**: 후보 이름을 토큰/부분 문자열로 필터링하고, 남은 토큰 집합으로 점수 `0.7 × overlap + 0.3 × cosine` 을 계산합니다. 이름은 최대 20개까지 유지합니다.
   - **류(class)**: 클래스 설명과 쿼리 일부를 결합해 점수 `0.6 × overlap + 0.4 × cosine` 을 계산하고, 클래스 이름에 쿼리 토큰이 직접 포함돼 있으면 추가 보너스 `+0.1`을 적용합니다.
   - **최종 종합**: 각 클래스는 최고 group 점수와 `0.3 × class + 0.7 × best_group` 가중 평균으로 정렬되며 최대 10개까지 반환합니다.

## API (`/goods/search`)
- FastAPI 라우터: `app/api/routes_goods.py`
- 쿼리 파라미터 `q` (필수) → `GoodsSearchResponse`
- 응답 필드
  - `query`: 검색어 문자열
  - `results`: `GoodsClassItem` 배열
    - `nc_class`, `class_name`, `score`
    - `groups`: `GoodsGroupItem` 배열 (코드, 이름 목록, 점수)
- 프론트엔드에서는 빈 `groups` 를 가진 류는 렌더링하지 않음

## 프론트엔드 연동
- `/goods/search` 호출 후 결과를 `GoodsGroupList` 컴포넌트로 표시
- 사용자 선택은 `selectedGroups` 객체에 저장
- 체크박스 상태만 저장하며 별도 요약 UI 없음 (2024-xx-xx 업데이트)

## 유지보수 노트
- TSV 구조 변경 시 `GroupEntry.add_name` 로직과 이름 슬라이싱을 조정
- 점수 가중치(류 vs 유사군)는 실제 데이터 품질에 맞게 조정 가능
- 대용량 최적화가 필요하면 캐싱 또는 비동기 로딩을 고려하고 문서화할 것
