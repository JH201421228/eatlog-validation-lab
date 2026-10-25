# Nutrition5k 사진 평가 사전 고정 계획

작성일: 2026-10-25. 이 디렉터리는 팀 서비스와 분리한 개인 실험이다.

## 목적과 분리

1. 실제 사진 한 장으로 추정한 접시 전체 영양·중량의 오차를 측정한다.
2. 동일한 모델 원본 응답을 수정 전/후 AI 정규화 및 BE 영양 산식에 각각 재생하여 후처리의 영향을 분리한다. 모델을 두 번 호출하여 생기는 변동을 개선 효과로 세지 않는다. 코드/파일의 `blind_test`는 기존 split 식별자이며 보고서에서는 **고정 평가 세트**로 부른다. 사전학습 미노출을 뜻하는 엄격한 blind test라는 주장은 하지 않는다.
3. 실험 집합은 pilot 20개와 고정 평가 세트 1000개를 목표로 한다. 시간과 재료 중량의 계승을 사용한 보수적 추정 증분 그룹을 분리하고, 고정 manifest의 실패 사례도 분모에 남긴다. 공식 물리적 접시 식별자가 없어 1020개의 실제 물리적 독립성을 확정할 수는 없다. 공식 train 출신을 포함할 수 있으므로 공개 데이터에 대한 모델의 학습 노출이 없다고 주장하지 않는다. QC 완료 v2의 평가 1000개는 official train 852/test 148, overhead 836개와 camera A 영상 첫 프레임 164개이다.

사진 정확도, 합성 계약 회귀 통과율, 운영 API 성공률은 서로 다른 지표다. 이 평가만으로 한국 음식·포장 라벨 정확도, 추천 성능, 운영 리텐션 개선을 주장하지 않는다.

## 모델과 입력

- 로컬 설정을 확인한 평가 모델: `gemini-2.5-flash`. 운영 서버 환경의 현재 모델을 확인했다는 뜻은 아니다.
- 팀 AI의 고정 프롬프트와 JSON schema를 사용한다. 최대 음식 5개, 음식별 후보 3개. 이미지 한 장, 원본 크기, 추가 사용자 설명 없음. Ground truth는 프롬프트에 포함하지 않는다.
- temperature 0, seed 20260722, thinking_budget 0, max_output_tokens 4096, SDK attempts 1(원요청만), 자동 재시도 없음, 요청 timeout 90초.
- Google Search/grounding, 사용자 식습관 보정, 사용자 기록, 서비스 쓰기 경로는 사용하지 않는다.
- 기본 평가는 nutrition DB 매칭을 비활성화한다. 실제 식품 기준표 snapshot을 확보하면 동일 snapshot을 두 버전에 적용한 추가 평가를 별도로 기록한다. 40개 목업 seed를 실측 영양 DB로 취급하지 않는다.
- pilot은 전송·JSON 완결성·비용·실행경로 점검용이다. pilot 정답에 맞추어 후처리 규칙이나 모델 프롬프트를 튜닝하지 않는다. blind_test 결과를 본 뒤 바뀐 규칙은 새로운 검증 집합이 필요하다.
- 요청 직전 별도의 검증된 다운로드 manifest에서 status=ok와 image_path 일치를 확인하고, 실제 파일 SHA256을 그 manifest의 검증값과 대조한다. 파일이 존재한다는 이유만으로 요청하지 않는다. 완료 후 실제 모든 요청 이미지 hash를 최종 다운로드 manifest와 다시 대조한다.

## 고정과 재현

### 정답 메타데이터 QC에 따른 v2 수정

v1 선정 SHA256 `2f6df93c563bc014029aa4a518bbecddc3c0098774684efe0f38a5eacbc5b942`를 보존한다. pilot 20건 호출 중 수집 담당자가 공식 cafe2의 dish-level 열량·영양값이 0 placeholder임을 발견했다. 이 시점에 영양 점수는 계산하지 않았다. 이후 모델 출력과 무관한 원본 메타데이터 품질 기준으로 cafe2 238개, cafe1 합계 불일치 37개, 빈 접시 2개를 제외했다. 원래 음식별 정답은 수정하지 않았다.

v2는 `data/nutrition5k/selection_manifest_v2.jsonl`, SHA256 `9000890d37127b639684662b63e719b8d2b31e1439ad465057ca5b249fafde1d`이다. `manifest_freeze.json`은 v1 감사 기록으로 유지하고, `manifest_freeze_v2.json`을 실제 최종 평가에 사용한다. v1 파일은 수집 담당자가 `data/nutrition5k/archive/v1_before_quality_audit/`에 보존했다.

pilot은 기존 유효 17개와 신규 3개로 20개를 채운다. 이미 호출한 제외 3개 응답·usage·비용은 모두 보존하고 성능 분모에서만 제외한다. 최초 pilot 20개의 모든 추정 증분 그룹은 평가 1000개에서 제외한다. 따라서 전체 유료 호출 목표는 1023건이고, 평가 대상은 pilot 20개 + 평가 1000개다. 기존 프롬프트·정규화 규칙·모델 설정은 바꾸지 않았다. 1023건 기준 설정상 계획 최대 비용은 $16.61352이며, 별도 $30 하드 장부 제한은 동일하다.

### 원본 영상 존재 여부에 따른 v3 수정

v2의 side camera A 원본 7개가 없음을 확인했다. 모델 출력과 무관하게 공식 객체 존재 여부만으로 A→B→C→D 중 첫 존재 camera의 0번 프레임을 사용하는 source-resolution 수정이 승인되었다. 6개는 B 영상으로 해결했고, `dish_1564415499`는 모든 camera 원본이 없어서 교체하지 않고 평가 1000개 분모에 실패로 남긴다. 따라서 본평가는 1000개 선정 / 999개 사진 및 모델 요청 가능 / 원본 누락 1개이며, 유효 pilot 20개 및 QC 제외 pilot 호출 3개를 더하면 최대 실제 호출은 1022개다.

최종 v3 SHA256은 `c7ab766b7ed73c4e9b7fc04fabf95d8a6298bd31d631f34faf130596eb80da22`이다. sample ID·split·group·정답은 변하지 않았고, 실제 source/view가 바뀐 6개는 모두 변경 전에 미호출임을 독립 감사했다. 모든 행의 selection_version과 side 원본의 MD5/generation 보강은 bookkeeping으로 별도 기록한다. 변경 전 검증된 파일만 읽는 진행 중 v2 pass는 그대로 완료하고, 이후 미시도 사례만 v3 freeze로 요청한다. 모든 요청은 최종 이미지 SHA와 다시 대조한다.

`source_index.json`에 AI/BE 각각 수정 전·후 4개 commit과 파일 hash를 기록한다. 원본 추출은 git archive의 tracked app 경로만 사용하며 .env는 복사하지 않는다. `request_config.json`, `prompt.txt`, `response_schema.json`, `manifest_freeze.json`이 요청과 샘플 선택을 고정한다.

후처리는 실제 pinned AI `vision.analyze`의 모델·이미지 전송과 검색 호출만 mock하여 원본 응답을 재생한다. BE는 실제 `resolve_nutrition`을 실행한다. FE의 초기선택 계약을 따라 food_index별 보존 후보 중 신뢰도가 가장 높은 1개만 고르고, 서로 다른 음식 그룹을 합산한다. 대체 후보를 여러 음식처럼 중복 합산하지 않는다. 신규 FE 코드를 수정하지 않는다.

DB 없는 기본 평가에서는 검색 label, 식품 DB 정확 매칭, 식습관 보정, 사용자 저장 경로, 실제 FE 표시 효과가 평가되지 않는다. 패키지 없는 일반 접시에서 포장 열량 수정의 효과가 0인 결과도 그대로 보고한다. 정상 응답을 새 코드가 실패로 바꾸거나 영양을 잃는 사례는 별도 목록으로 남기며, 정답 판별이 필요한 경우 수동 검토 미완료라고 표시한다.

## 지표와 실패 처리

- 목표/선정/다운로드/요청/응답/유효 예측 수를 각각 기록한다. API 실패·미시도·영양 일부 누락을 조용히 제외하지 않는다.
- 칼로리 kcal, 중량 g, 탄수화물/단백질/지방 g: 유효 예측의 MAE, MAPE, 중앙 APE, 편향; 0인 정답은 MAPE 분모에서 제외하고 수를 명시한다.
- ±15% 칼로리 이내 비율은 유효 예측 분모와 전체 선정 분모를 함께 보고한다. 실패를 포함한 전체 분모가 주 지표다.
- 동일 사례의 수정 전/후 절대오차 차이와 변경/개선/악화/실패 전환 수를 보고한다. paired 차이의 bootstrap 95% 구간을 고정 seed로 계산한다.
- 단일 호출 latency p50/p95와 token usage 기반 추정 비용을 보고한다. 비용은 실제 청구서 검증액이 아니다.
- 원본 official split과 camera_view로 층화한다. 영어 재료명과 한국어 메뉴명 사이에 검증된 정답 매핑이 없으므로 메뉴 Top1 정확도를 임의로 계산하지 않는다.
- 본평가 수집 중, 정답 점수 열람 전에 추가한 탐색 분석: 접시의 각 음식 그룹 최상위 후보 confidence 중 최소값을 `[0,.5)`, `[.5,.75)`, `[.75,.9)`, `[.9,1]`로 나누고 n/전체대상 ±15%율/MAE/MAPE를 병기한다. confidence 없는 사례를 별도로 남긴다. 음식명에 대한 모델 confidence는 칼로리 정확 확률이 아니며, 이 분석으로 자동 보정 threshold를 튜닝하지 않는다.

## US$30 하드 예산

공식 Gemini 2.5 Flash 표준 단가: 입력(텍스트/이미지/영상) $0.30/백만 토큰, 출력(사고 포함) $2.50/백만 토큰. 요청 전 count_tokens에 JSON schema UTF-8 byte 수와 4096 여유 토큰을 더한 값이 20,000 이하일 때만 생성한다. 출력 한도 4096이면 1020건 계획 최대 비용은 $16.5648이다.

별도로 각 생성 직전에 $0.50을 영구 장부에 선예약한다. 문서상 모델 전체 최대 입력 1,048,576 및 출력 65,536을 모두 쓰더라도 $0.4784128로 예약액 이하다. 응답 usage를 확인한 경우만 실제 단가로 정산한다. timeout·usage 누락·실행 중단은 $0.50을 계속 차지하며 자동 재호출하지 않는다. 정산액과 미확인 예약액의 합이 $30을 넘는 요청은 실행하지 않는다. 프로세스 OS lock, sample ID 중복 차단, 재시작 복원, fsync 후 네트워크 호출을 사용한다. 3회 연속 API 오류 또는 설정 토큰 한도 초과 시 후속 생성을 중단한다.

### 공식 문서

- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) — 2026-10-25 확인.
- [Gemini 2.5 Flash model limits](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash)
- [Image understanding / token calculation](https://ai.google.dev/gemini-api/docs/image-understanding)
- [Count tokens](https://ai.google.dev/gemini-api/docs/tokens)

## 실행

Windows PowerShell, lab 루트에서 아래 명령을 각각 실행한다. 기존 AI/BE 가상환경을 읽기 전용 실행 런타임으로 사용한다. 이미지·원본 응답 폴더·임시 코드 snapshot은 .gitignore 대상이다. allowlist를 적용한 공개 음식 모델 응답은 `evaluation/evidence/model_responses.jsonl`로 저장하며 paid API를 다시 부르지 않고 replay할 수 있다.

```powershell
$evalManifest = 'C:/Users/741u7/Desktop/soma_project/eatlog-validation-lab/data/nutrition5k/selection_manifest_v3.jsonl'
$evalFreeze = 'C:/Users/741u7/Desktop/soma_project/eatlog-validation-lab/evaluation/manifest_freeze_v3.json'
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\prepare.py --manifest $evalManifest --freeze $evalFreeze
..\AI\ai-server\venv\Scripts\python.exe -m unittest discover -s scripts/evaluate -p test_evaluation.py -v
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\collect.py --split pilot --concurrency 2 --manifest $evalManifest --freeze $evalFreeze
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\collect.py --split blind_test --concurrency 4 --manifest $evalManifest --freeze $evalFreeze
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\export_evidence.py --manifest $evalManifest
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\audit_images.py --manifest $evalManifest
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\replay.py --split blind_test --manifest $evalManifest --freeze $evalFreeze
..\AI\ai-server\venv\Scripts\python.exe scripts\evaluate\metrics.py --split blind_test --manifest $evalManifest --freeze $evalFreeze
```

평가 결과와 보고서 결론은 실행 완료 후 추가한다. 결과 확인후 추가 혹은 수정필요.
