# 실제 공공 영양 DB 연결 실험

## 결론

**DB를 연결하는 것만으로 사진 열량 정확도가 높아지지는 않았다.** 기존
정확일치 방식의 원재료 연결은 오차가 늘었다. 조리 상태를 확인하고 불명확하면
AI 추정으로 돌아가는 방식은 그 악화를 줄였지만, DB 없는 기존 추정보다 좋아졌다는
근거는 얻지 못했다. 이 실험 코드는 운영에 배포하지 않는다.

기존에 결과를 확인한 Nutrition5k 1,000개를 재사용한 **탐색 실험**이다.
1,000개 분모를 유지했고 994개에서 영양 예측을 비교했다. 모델 유료 호출 0회,
추정 중량·음식 선택 변경 0건이다. 원천 정답의 재료명·영양표를 검색 DB나 질의로
사용하지 않았다. 예측 파일 해시를 고정한 뒤 별도 스크립트로 총열량만 채점했다.

## 방법과 결과

BE `5b77e1d59e320fd2c4f84650d103bd4b1c2c8ab0`의 실제 `resolve_nutrition`,
후보 그룹화, 정확일치 정규화 및 매칭 우선순위를 호출했다. 품질·상태 분기는
실험 파일에서만 수행했다. 아래 DB는 운영 전체 DB가 아니라 공개 원재료 부분 DB다.

| 방식 | 유효 예측 | MAE(kcal) | MAPE | WAPE | 오차 ±15% 이내¹ | DB 연결 음식/2,010 |
|---|---:|---:|---:|---:|---:|---:|
| 기존 no-DB 추정(비교 기준) | 994 | 107.42 | 63.74% | 46.00% | 19.11% | 0 |
| 현재 코드 정확일치 + 공개 부분 DB | 994 | 110.81 | 69.58% | 47.45% | 18.21% | 599 |
| 정확일치 + 영양값 품질 검사 | 994 | 110.81 | 69.58% | 47.45% | 18.21% | 599 |
| 조리 상태 일치 + 보수적 fallback | 994 | 107.87 | 64.06% | 46.19% | 19.52% | 421 |

¹ 유효 994개 기준. 전체 선정 1,000개를 분모로 하면 차례로 19.0%, 18.1%,
18.1%, 19.4%다. 실패/누락을 제거해 성공률을 부풀리지 않는다.

- **정확일치 DB vs no-DB:** 열량이 달라진 381개 중 오차 감소 164개, 증가
  217개. MAE +3.39kcal. 짝지은 bootstrap 95% 범위 +1.87~+5.15kcal.
- **품질 검사:** nonfinite·음수·100g 기준·macro 추정 여부·물리 범위 검사로
  reference 113행이 제외되지만 이 평가의 매칭 행에는 해당하지 않아 변화 0이다.
- **조리 상태 방식 vs 현재 정확일치:** 달라진 310개 중 감소 177개, 증가
  133개. MAE −2.94kcal, bootstrap 범위 −4.83~−1.22kcal.
- **조리 상태 방식 vs no-DB:** 달라진 271개 중 감소 132개, 증가 139개.
  MAE +0.45kcal, bootstrap 범위 −0.32~+1.28kcal. 새 정확도 개선으로 판정하지 않는다.

Bootstrap은 탐색적 접시 단위 2,000회 재표집이다. 이미 확인한 자료이며 추정 그룹의
물리적 독립성이 보장되지 않으므로 확증 통계검정으로 해석하지 않는다.

상태 방식의 421개 연결은 **명시적 조리 상태 일치 89개 + 일반 과일을 생것으로
가정한 332개**다. 나머지는 상태 불명 990개, 소스가 있는 음식 458개, 같은 상태
reference 없음 141개다. 실제 이미지로 조리법을 재판정하거나 숨은 기름을 추정하지
않았고, 모델이 낸 음식명만 질의로 썼다. `quality_exact`와 `state_aware`의 상세
규칙은 [PROTOCOL.md](PROTOCOL.md), 고정된 동의어는 [grounding.py](grounding.py)에 있다.

## 데이터 출처와 재현 범위

- 출처: [공공데이터포털 전국통합식품영양성분정보(원재료성식품)](https://www.data.go.kr/data/15100065/standard.do).
  [식약처 공식 DB 설명·다운로드](https://various.foodsafetykorea.go.kr/nutrient/general/down/list.do)는
  식약처·농진청·국립수산과학원의 자료를 표준화한 통합 DB임을 설명한다.
- 기존 BE의 `scripts/data/mfds_material.jsonl` 3,704행, 고유 식품코드 3,701개,
  원본 SHA256 `5161faa96a5250b2465188f377ddf3021a5dd15a39127ba6ba524ba9b86652c5`.
  기준일은 2025-12-23/2026-01-13이다. 원래 수집 시각을 새로 만들어 기록하지 않았다.
- 현재 importer를 그대로 적용하면 원본 변형 3,671개 + 총칭 평균 2,805개가 된다.
  중복 코드 3개와 importer가 거절한 30개는 `reference_exclusions.jsonl`에 기록했다.
- 채택 원본의 출처는 농진청 1,861행, 국립수산과학원 1,740행, 식약처 70행이다.
  생성 방법은 분석 3,329행/수집 335행/산출 7행이다. **전부 실측값이라고 부르지 않는다.**
- `reference.jsonl`은 공개 영양값·식품명·분류·출처를 allowlist로 정규화한 자료다.
  원본 API JSON 전체, 인증키 및 요청 파라미터를 복사하지 않았다. 공공데이터의 원출처를
  위와 같이 표시하며 별도 CC 라이선스로 재지정하지 않는다. Nutrition5k의 CC BY 4.0은
  이 MFDS 자료에 자동 적용되지 않는다.
- `model_candidates.jsonl`은 기존 평가의 AI 정상화 출력과 byte-for-byte 동일한 보관본이다.
  `results/prediction_freeze.json`의 `input_sha256`과 같다. 원본 freeze에 남은 `evaluation/tmp/`
  경로 대신 이 보관본을 아래 명령의 입력으로 사용하면 된다.

## 남은 위험과 실제 제품 적용 조건

1. 원재료 DB는 한국 식품이고 평가 사진은 미국 구내식당 중심이다. 혼합 요리·브랜드
   상품·조리유·소스·품종 차이를 해결하지 않는다. 음식 인식과 중량 오차도 그대로다.
2. **운영 DB 전체 dump를 사용하지 않았다.** 운영에는 음식편/가공식품편/seed가 있을 수
   있으며 현재 우선순위는 seed > 음식(D) > 원재료(R) > 가공(P)이다. 목업 seed는 이번
   실험에서 제외했다. 따라서 위 표를 현재 운영 앱 정확도라고 표시하면 안 된다.
3. 총칭의 정규화 이름 충돌이 reference에 274개 있고 이번 선택 58개 음식에 걸렸다.
   옥수수 135.6/40, 고구마 136.5/29.33, 양파 41.4/354, 메밀 24/363 kcal/100g처럼
   동명이지만 서로 다른 자료가 존재한다. 현 코드는 id가 작은 행을 선택하며 이번 id는
   importer 순서로 부여했다. 운영 삽입 순서는 확인하지 않았다.
   [이름 충돌 감사](results/exact_name_ambiguity.json)에 원코드와 값이 있다.
4. 상태 방식도 분류명 평균과 과일 raw 가정을 사용한다. 후보 대안이 있는 그룹 144개는
   기존 confidence 최대 후보를 그대로 사용했다. 후보 선택 개선은 이번 범위가 아니다.
5. 운영 적용은 공개 자료의 식품 정체성·조리 상태·단위가 정확히 매핑되는 DB snapshot과
   새 검증 세트에서 확인한 뒤 판단해야 한다. 이번 결과만으로 새 모델 호출이나 배포를
   시작하지 않았다.

## 실행

저장소 루트에서 기존 BE virtualenv를 사용한다. 기본 sibling `../BE`는 위 커밋이어야
원래 결과가 재현된다. `--be`로 별도 고정 checkout 경로를 줄 수 있다. DB 연결은
`sqlite://`로 강제하고 DB session을 열지 않는다.

```powershell
../BE/venv/Scripts/python experiments/accuracy_followup/grounding/prepare_reference.py
../BE/venv/Scripts/python experiments/accuracy_followup/grounding/run_experiment.py --input experiments/accuracy_followup/grounding/model_candidates.jsonl
../BE/venv/Scripts/python -m unittest discover -s experiments/accuracy_followup/grounding -p test_grounding.py -v
../BE/venv/Scripts/python experiments/accuracy_followup/grounding/score_experiment.py
```

2026-10-25 실행 결과: 회귀 테스트 9개 통과, 모든 arm 1,000행, no-DB 원래
계산값과 불일치 0, 음식 선택/중량 불일치 0. 숫자/단위/조리 상태·부위·혼합식 fallback과
전체 1,000개 양 불변을 검사했다. 원래 코드·DB·FE·공용 평가 및 비용 원장을 수정하지 않았다.

주요 파일: `prepare_reference.py`(공개 reference), `grounding.py`(3개 정책),
`run_experiment.py`(정답 비접근 예측), `score_experiment.py`(동결 후 채점),
`test_grounding.py`(회귀 검증), `reference_audit.json`, `results/coverage.json`,
`results/prediction_freeze.json`, `results/score_summary.json` 및 arm별 예측/채점 JSONL.
