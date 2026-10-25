# 정확도 후속 실험 판정 기준과 데이터 감사

작성일: 2026-10-25. 이 문서는 초기 계약 수정과 별도로 **실제 열량 오차를 줄이는 후속 가설**을 판정하기 위한 기준이다. 기존 평가 1,000개는 이미 결과를 확인했으므로 탐색·개발 자료로만 사용한다. 그 자료에 맞춘 가설을 같은 자료로 다시 성공 판정하지 않는다.

## 검증 세트 결론

기존 `ingredient_mass_time_v1` 추정 그룹과 원천 QC를 그대로 재계산했다. 적격 그룹 1,175개 중 기존 pilot 20개와 평가 1,000개가 1,020개를 사용했다. **미사용 적격 그룹은 155개**다. 기존 v1 탈락 pilot까지 포함한 이전 1,023개 그룹과 새 목록의 dish/group 교집합은 0이다. 현재 자료에서 신규 1,000개의 비중복 그룹은 확보할 수 없다.

새 155개는 모두 측면 촬영이며 공식 train 136개/test 19개다. 원본 카메라는 A→B→C→D 중 공식 객체가 존재하는 첫 번째를 선택하고 항상 프레임 0을 사용한다. 원본 존재 153개, 전체 카메라 누락 2개다. 누락도 선정 분모 155에 남긴다. 153개 원본 중 A 150개/B 3개다. 영상·이미지 해시, 디코딩 및 중복 검사는 수집 완료 시 `data/nutrition5k_followup/integrity_audit.json`에 기록한다.

추정 그룹은 공식 물리 접시 ID가 아니므로 완전한 독립성은 보장하지 않는다. 기존 평가의 대부분이 상부 촬영인 데 비해 새 평가는 측면뿐이므로, 새 결과를 한국 음식·포장 제품·일반 스마트폰 사진의 성능으로 일반화하지 않는다. 파일 디코딩 성공은 음식 내용과 영양 라벨의 시각적 정합성을 보장하지 않는다.

## 사전 판정 기준 8개

아래 숫자는 리뷰에서 지정한 목표값이 아니라 **이번 후속 실험에서 부모 조정자가 결과를 열람하기 전에 승인한 판정 규칙**이다. 중간 리뷰 원문의 관련 위치는 `report/review_20260824.md` 27–49행이며 원문 전체를 이 저장소에 복제하지 않는다.

| ID | 리뷰 요구와 후속 판정 기준 | 확인 근거 |
|---|---|---|
| AC01 | 사진만으로 신뢰도를 높이고 실제 데이터로 검증한다. 기존 1,000개에서 가설·파라미터를 탐색한 뒤 단일 최종 후보의 코드·프롬프트·모델·DB snapshot·설정을 고정한다. 새 155개 정답은 그 뒤 **한 번만** 개봉한다. 이미지/추정 그룹 교집합은 0이어야 한다. | 후보 동결 hash, 이전/새 manifest hash, source/QC 감사, 정답 개봉 시각 |
| AC02 | 실제 열량 정확도 개선의 주 판정: 같은 새 이미지의 기준·후보를 비교하여 **열량 MAE 10% 이상 감소**, `후보 절대오차 − 기준 절대오차`의 paired bootstrap 95% 구간 상한 <0을 모두 만족해야 한다. **유효 paired 100개 미만이면 불충분**이다. 고정 seed와 반복 수를 결과 전 명시한다. | 사례별 두 예측과 원천 정답, paired delta와 구간, 코드/설정 hash |
| AC03 | 실패를 제외해 좋아 보이게 하지 않는다. 전체 선정 155개 분모의 열량 ±15% 이내 비율과 유효 영양 예측 수가 기준보다 악화되지 않아야 한다. 원본 누락/API 오류/JSON 오류/음식 없음/정상 영양을 분리하고 모두 보존한다. 임의 재시도·교체는 하지 않는다. | 전체 155개 상태표, 응답/유효/paired 수, 실패 사유별 건수 |
| AC04 | 메뉴·양·영양 분석을 구분한다. 중량 g와 탄수화물·단백질·지방 g의 MAE/MAPE/WAPE/편향, 열량 중앙 APE와 높은 오차 사례를 함께 보고한다. 중량 개선 가설은 중량 오차도 따로 판정한다. 검증된 메뉴 정답 매핑이 없으면 Top-1/Top-3 정확도를 만들어 쓰지 않는다. | 모든 지표의 분모·단위·0 정답 처리, 원본 사진과 예측 연결 |
| AC05 | DB 근거와 미매칭 대안을 검증한다. DB/RAG 후보는 두 버전이 같은 고정 snapshot을 사용하고 매칭 항목·출처·기준량·fallback을 남긴다. **새 검증 세트의 재료·중량·영양 정답을 DB 검색, 프롬프트, 보정식 입력으로 사용하지 않는다.** 정답 중량 oracle 결과는 탐색 진단으로만 표시한다. | DB snapshot hash, 검색 로그, 출처별 적용률·오차, 입력 allowlist |
| AC06 | 사용자 보정 부담 요구를 분리한다. 음식명 confidence를 열량 정답 확률로 가정하지 않는다. 선택적 보정은 개발 자료에서 고정한 정책으로 coverage와 오차를 보고하며 유효 출력 감소를 성공으로 바꾸지 않는다. 실제 수정 횟수·보정시간·리텐션은 사용자 실험 없이 개선했다고 쓰지 않는다. | 고정 정책, 자동/보정 구간별 n·오차·coverage, 미측정 항목 표시 |
| AC07 | 측정 조건과 범위를 공개한다. 같은 원본 이미지·입력 해상도·공통 설정에서 기준과 후보를 실행하고 의도한 변경만 명시한다. 원본 측면 A/B, 공식 train/test를 나누고 API 지연·usage 비용·예약 비용도 기록한다. 호출 예산은 기존 $30 누적 장부를 포함한다. | 요청 config/prompt/model_version, strata, 비용 장부, latency |
| AC08 | 성과와 미해결을 모두 남긴다. 탐색에서 악화·무효·채택 보류된 가설도 기록하고, 새 확인 세트가 실패하면 그 결과를 보고한 뒤 같은 세트에 재튜닝해서 성공 주장하지 않는다. 배포는 정확도 판정과 기존 계약·회귀 테스트를 모두 통과한 BE/AI 변경만 대상으로 하며 FE와 읽기 전용 운영 사이트는 수정하지 않는다. | 모든 가설 로그, 판정표, 회귀 결과, PR/배포 SHA, 보고서 변경 이력 |

## 정답 분리와 실행 범위

- 모델 입력/수집 목록: `data/nutrition5k_followup/selection_manifest.jsonl` 및 `manifest.jsonl`. `truth`, `ingredients`, 메뉴 정답이 없다.
- 정답: `data/nutrition5k_followup/gold_labels.jsonl`. 채점 담당이 최종 후보 동결 뒤에만 사용한다. 가설을 작성하는 AI/BE 담당에게 전달하지 않는다.
- 목록·원천 출처 동결: `data/nutrition5k_followup/freeze.json`.
- 이번 데이터 감사/수집 과정의 모델 API 호출: **0회**.
- 이 감사는 리뷰 요구의 충족 기준을 정한 것이며 정확도 개선이 이미 달성됐다는 뜻이 아니다.

## 추가 공개 정답 자료의 현실성

1. **한식 후보 — AI Hub 「음식 이미지 및 영양정보 텍스트」**: 공식 소개는 400종 이상의 음식, 일반/정밀 촬영, 어노테이션과 영양 메타데이터를 설명한다. 한식 메뉴 인식과 양 시나리오에 더 가깝지만, 이 작업에서는 신청·로그인·다운로드를 하지 않았다. 이미지별 실제 중량인지 표준 1인분 영양인지, 동일 접시의 여러 각도 그룹, 외부 모델 전송·재배포 조건을 원문 가이드와 샘플로 먼저 검증해야 한다. 현재 확보한 실제 중량 정답으로 취급하지 않는다. [AI Hub 공식 데이터 페이지](https://www.aihub.or.kr/aihubdata/data/view.do?aihubDataSe=data&currMenu=120&dataSetSn=74&topMenu=100).
2. **포장 후보 — Open Food Facts**: 공식 API는 제품·표시 영양 데이터와 front/nutrition 이미지를 제공하며, 제품 DB와 사진 라이선스가 다르다. 실제 사진의 제품·변형·기준량을 영양표 이미지와 독립 대조하면 포장 OCR/제품 검색/0 kcal/100g·100ml·1회분 검증에 적합한 별도 세트를 만들 수 있다. 자발적 제출 자료의 정확성을 보장하지 않으므로 구조화 값만 정답으로 사용하지 않는다. 섭취 비율이나 접시 실제 질량은 이 자료가 보장하지 않는다. 제품 barcode와 변형 계열을 그룹으로 분리하고 한국 유통 표본 수는 수집 전에 확인해야 한다. [공식 API와 이용 조건](https://openfoodfacts.github.io/openfoodfacts-server/api/), [공식 이미지 구성](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/docs/api/how-to-download-images.md), [공식 영양 필드 정의](https://github.com/openfoodfacts/openfoodfacts-server/blob/main/html/data-fields.txt).

두 외부 후보는 공식 문서만 읽었다. 대규모 수집·계정 신청·유료 호출은 하지 않았다. 현재 확인 실험은 Nutrition5k 잔여 그룹만 사용한다.

## 재현

기존 데이터와 collector를 읽기 전용으로 사용하고, 아래 새 경로에만 쓴다. 원래 고정 평가 파일을 덮어쓰지 않는다.

```text
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py prepare
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py resolve
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py download --workers 8
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py validate
```

이미 동결한 prepare/resolve는 덮어쓰기를 거부한다. download는 실패 또는 없는 파일만 같은 출처에서 복구한다. 데이터셋 출처는 Google Research Nutrition5k, Thames et al. (2021), CC BY 4.0이다. 영양 정답은 재료 실측 질량과 레시피/영양 DB로 계산된 값이며 열량계 실측이 아니다. [공식 저장소](https://github.com/google-research-datasets/Nutrition5k), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
