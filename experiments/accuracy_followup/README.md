# 실제 정확도 후속 실험

이 폴더는 기존 Nutrition5k 평가에서 발견한 오차 원인을 탐색하고, 고정한 후보를 남은 155개 추정 그룹에서 한 번 확인하기 위한 실험 기록이다. **실험은 진행 중이다.** 최종 확인이나 배포 성공을 아직 주장하지 않는다. 최종 결정은 `final_decision.json`에 기록하며, 파일이 생성되기 전에는 미완료다.

## 데이터 구분과 해석

- 이전 본평가 1,000개는 이미 결과를 확인했다. 전부 탐색·개발 자료이며 독립 확인 세트나 새 성공 판정으로 다시 세지 않는다. `dev100_manifest.jsonl`은 그 중 고정된 100개이고, `dev1000_manifest.jsonl`은 전체 1,000개다. `neutral_full`은 이전 응답을 재사용하지 않고 1,000개에 새 중립 요청을 한 별도 개발 실험이지만, 정답은 여전히 같은 과거 평가에서 왔으므로 탐색 결과다.
- 개발 단계는 기준선과 `neutral_portion`, `volume_consistency`, `baseline_thinking1024`를 비교한다. 추가 모델 비교 `model_comparison/flash35_minimal`도 개발 자료 전용이다.
- 질량 보정은 과거 1,000개에서 그룹 분리 교차검증으로 세 가지 사전 기록된 계열(`log_mass`, `linear_mass`, `weighted_log_mass`)을 비교한다. MFDS 실험은 같은 과거 예측을 공개 원재료 부분 DB로 재생한다. 둘 다 탐색이며 운영 성능 또는 배포 승인으로 해석하지 않는다.
- 새 155개는 이전 선정과 추정 그룹 교집합이 없는 확인 세트다. 모두 측면 촬영이며, 원본이 없는 2개도 분모에 남긴다. 코드·모델·프롬프트·DB/정책·입력 manifest의 해시를 동결한 뒤, 채점 담당이 `data/nutrition5k_followup/gold_labels.jsonl`을 한 번만 열어 채점한다. 가설 탐색이나 요청 입력에 새 정답·재료·중량을 사용하지 않는다.
- 새 155개 확인 기준은 유효 paired 100개 이상, 기준 대비 열량 MAE 10% 이상 감소(전체 유효 예측과 같은 paired 표본 모두), 후보−기준 paired 오차 bootstrap 95% 구간 상한 <0, 전체 155개 기준 ±15% 이내 건수와 유효 영양 예측 건수 비악화다. 기준을 못 채우거나 실패하면 불충분/불채택으로 남기고 이 확인 세트에 맞춰 재튜닝하지 않는다.

## 예산과 실패 기록

- `cost_ledger.json`은 최초 평가 비용/예약액을 포함한 누적 원장을 상속한다. 과거 비용을 후속 실험 비용과 중복 합산하지 않는다. 전체 승인 상한은 과거분을 포함해 **US$30**이며, 호출 전후 비용은 같은 원장으로 확인한다.
- 자동 생성 재시도는 금지한다. API 오류, JSON 오류, 음식 후보 없음, 원본 누락, 미시도 상태를 각각 보존한다. 실패 표본을 분모에서 빼거나 표본을 임의 교체·재요청해 결과를 좋게 보이지 않는다. 유료 실행은 이 문서의 재현 예시를 그대로 실행하기 전에 누적 예약액과 잔여 상한을 확인한다.

## 재현 순서

명령은 저장소 루트에서 PowerShell로 실행한다. `run_model.py`와 `run_model_compare.py`는 Google SDK가 설치된 `../AI/ai-server/venv/Scripts/python.exe`를 사용한다. 질량 보정과 collector의 기본 도구는 시스템 `python`을 사용하며, 보정에는 NumPy가 필요하다. MFDS grounding은 `../BE/venv/Scripts/python.exe`를 사용한다. 수집·평가 단계는 파일을 쓰고, 모델 실행은 유료 API를 호출할 수 있다. 동결 파일을 확인하고 현재 작업 상태와 예산을 검토한 뒤 필요한 단계만 수행한다. 이미 동결된 입력은 다시 만들거나 덮어쓰지 않는다.

### 1. 이전 결과를 탐색용으로 고정하고 새 데이터 준비

```powershell
python experiments/accuracy_followup/prepare_followup.py
python experiments/accuracy_followup/prepare_dev1000.py
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py prepare
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py resolve
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py download --workers 8
python experiments/accuracy_followup/protocol_audit/audit_and_collect.py validate
```

앞의 두 명령은 과거 100/1,000개 선택과 예산 상속을 동결한다. 새 데이터 준비 명령은 공식 출처의 잔여 155개를 고정하고 내려받은 원본의 해시·디코딩·중복을 검사한다. 준비 절차와 데이터 분리는 [`protocol_audit/README.md`](protocol_audit/README.md)에 있다.

### 2. 개발 요청과 비교

각 arm은 해당 디렉터리의 `prompt.txt`, `response_schema.json`, `request_config.json`을 그대로 쓴다. `baseline`은 sandbox 실패 보관 arm이다. 실제 기준 요청과 scorer의 기준 이름은 `baseline_v1`이다. 예를 들어 dev100의 fresh baseline 요청은 다음과 같다.

```powershell
& ..\AI\ai-server\venv\Scripts\python.exe experiments/accuracy_followup/run_model.py `
  --arm-dir experiments/accuracy_followup/baseline `
  --arm baseline_v1 --phase dev `
  --manifest experiments/accuracy_followup/dev100_manifest.jsonl `
  --freeze experiments/accuracy_followup/dev100_freeze.json `
  --download-manifest data/nutrition5k/manifest.jsonl
```

동일한 100개에서 `baseline_v1`, `neutral_portion`, `volume_consistency`, `baseline_thinking1024`를 비교한다. scorer에는 실제 기준 arm을 명시한다.

```powershell
python experiments/accuracy_followup/evaluate_followup.py `
  --phase dev --manifest experiments/accuracy_followup/dev100_manifest.jsonl `
  --freeze experiments/accuracy_followup/dev100_freeze.json `
  --arms baseline_v1 neutral_portion volume_consistency baseline_thinking1024 `
  --baseline baseline_v1
```

동결된 후보만 과거 1,000개 전체로 확장한다. `neutral_full`의 manifest/freeze는 `dev1000_manifest.jsonl`과 `dev1000_freeze.json`이다. 외부 모델 비교 준비는 시스템 Python으로 `python experiments/accuracy_followup/prepare_model_comparison.py`를 실행한 뒤, 비교 요청은 AI virtualenv를 사용한다. 모델 설정과 runner 해시는 `model_comparison/freeze.json`에 기록하지만, 입력 선택 freeze는 dev100에서는 `dev100_freeze.json`, 전체 개발이면 `dev1000_freeze.json`이다.

```powershell
& ..\AI\ai-server\venv\Scripts\python.exe experiments/accuracy_followup/run_model_compare.py `
  --arm-dir experiments/accuracy_followup/model_comparison/flash35_minimal `
  --arm flash35_minimal --phase dev `
  --manifest experiments/accuracy_followup/dev100_manifest.jsonl `
  --freeze experiments/accuracy_followup/dev100_freeze.json `
  --download-manifest data/nutrition5k/manifest.jsonl
```

모든 결과는 탐색 자료다. 평가 기준과 arm 선택 규칙은 [`protocol.json`](protocol.json)에 고정되어 있다.

응답이 이미 수집된 경우 dev 비교는 다음 scorer로 재현한다. `--arms`에는 비교할 모든 완료 arm을 적는다.

```powershell
python experiments/accuracy_followup/evaluate_followup.py `
  --phase dev --manifest experiments/accuracy_followup/dev100_manifest.jsonl `
  --freeze experiments/accuracy_followup/dev100_freeze.json `
  --arms baseline_v1 neutral_portion volume_consistency baseline_thinking1024 `
  --baseline baseline_v1
```

### 3. 보정·DB 가설의 탐색 재현

질량 보정의 세 계열 교차검증은 기존 평가의 예측·정답만 사용하며 추가 모델 호출은 하지 않는다.

```powershell
python experiments/accuracy_followup/calibration/train_evaluate.py
python -m unittest discover -s experiments/accuracy_followup/calibration -p test_calibrator.py -v
```

MFDS 공개 원재료 부분 DB 재생은 BE 코드와 고정 예측 입력을 사용한다. 운영 DB dump나 정답 재료 검색이 아니며 운영 DB 전체/seed의 일치도 대표하지 않는다.

```powershell
& ..\BE\venv\Scripts\python.exe experiments/accuracy_followup/grounding/prepare_reference.py
& ..\BE\venv\Scripts\python.exe experiments/accuracy_followup/grounding/run_experiment.py --input experiments/accuracy_followup/grounding/model_candidates.jsonl
& ..\BE\venv\Scripts\python.exe -m unittest discover -s experiments/accuracy_followup/grounding -p test_grounding.py -v
& ..\BE\venv\Scripts\python.exe experiments/accuracy_followup/grounding/score_experiment.py
```

해석, 공개 자료 출처, 적용 한계 및 확인된 부정 결과는 [`grounding/README.md`](grounding/README.md)에 보존한다. 여기의 MFDS 공개 부분 DB 결과를 현재 운영 DB 또는 서비스 정확도로 표현하지 않는다.

### 4. 후보 동결 후 새 155개 확인

채점 전에 단일 최종 정책의 코드·모델·프롬프트·설정·DB snapshot과 `selection_manifest.jsonl` 및 다운로드 무결성 기록을 동결하고 hash를 대조한다. 아래 요청 명령은 그 검토가 끝난 뒤에만 사용한다. 기준선과 단일 후보 모두 같은 새 입력, 같은 설정 범위로 실행하며 manifest에 포함된 원본 누락도 분모에 남긴다.

```powershell
& ..\AI\ai-server\venv\Scripts\python.exe experiments/accuracy_followup/run_model.py `
  --arm-dir experiments/accuracy_followup/baseline `
  --arm baseline_v1 --phase confirm `
  --manifest data/nutrition5k_followup/selection_manifest.jsonl `
  --freeze experiments/accuracy_followup/confirmation_input_freeze.json `
  --download-manifest data/nutrition5k_followup/manifest.jsonl
```

최종 후보에도 동결된 모델 설정에 맞는 runner(`run_model.py` 또는 `run_model_compare.py`)로 한 번 실행한다. 확인 요청에서 두 runner는 `confirmation_input_freeze.json`을 사용한다. 원본 `data/nutrition5k_followup/freeze.json`은 `selection_manifest_sha256` 키를 사용하므로 `run_model.py`의 `manifest_sha256` 필드 참조와 맞지 않는다. 이는 라우팅 호환 alias이며 선택 목록 자체를 바꾸지 않는다. scorer에는 원본 freeze 파일을 전달한다. 두 arm의 모든 응답과 입력·코드·정책 hash를 검토하고 비용 원장을 확인하기 전에는 아래 정답 채점 명령을 실행하지 않는다. 이 명령은 gold를 실제로 읽는다.

```powershell
python experiments/accuracy_followup/evaluate_followup.py `
  --phase confirm --manifest data/nutrition5k_followup/selection_manifest.jsonl `
  --freeze data/nutrition5k_followup/freeze.json `
  --arms baseline CANDIDATE_ARM --gold data/nutrition5k_followup/gold_labels.jsonl
```

`CANDIDATE_ARM`은 실제 동결 arm 이름으로 바꾼다. 최종 scorer만 이 정답 파일을 연다.

모든 실패를 포함해 결과와 판정 근거를 `final_decision.json`에 기록한다. 판정·해시·실패 분모가 확정되기 전에는 결과를 미완료로 표시하며, 이후 동일 확인 세트에 다시 맞추지 않는다.

## 보관, 출처, 라이선스

- 추가 Nutrition5k 원본 이미지와 영상은 로컬 `data/nutrition5k_followup/images/`, `videos/`에 보관한다. 루트 `.gitignore`의 `*.png`, `*.h264` 규칙이 미디어 payload를 Git에서 제외한다. manifest, 출처, 해시, 무결성·디코딩 감사는 보존한다. 미디어가 Git에 포함되지 않았는지 추가 전 `git check-ignore`로 확인한다.
- Nutrition5k 출처는 Google Research, Thames et al. (2021)이며 데이터는 **CC BY 4.0**이다. 재배포 시 출처와 라이선스를 유지한다. 정답 영양은 재료 중량과 영양 자료를 바탕으로 계산된 값이며 열량계 직접 측정이 아니다.
- `grounding/`의 MFDS 자료는 공개 원재료 부분 데이터다. Nutrition5k 라이선스가 MFDS 원자료에 적용되는 것으로 표시하지 않으며, 공개 자료를 운영 DB dump와 혼동하지 않는다. 원자료별 출처와 제외 내역을 함께 유지한다.
- 데이터 동결·개봉 정책은 [`protocol_audit/README.md`](protocol_audit/README.md), 확인 기준과 새 그룹 한계는 [`protocol_audit/HANDOFF.md`](protocol_audit/HANDOFF.md)에 있다.
