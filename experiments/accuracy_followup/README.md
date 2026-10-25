# 실제 정확도 후속 실험

이 폴더는 Nutrition5k 정확도 후속 실험의 완료 기록이다. 모든 성능 실험과 사전 동결한 155개 확인을 마쳤다. `flash35_minimal` 후보의 열량 MAE는 기준보다 31.8% 낮았지만 유효 예측 수가 153개에서 151개로, 전체 155개 중 ±15% 이내 예측 수가 30개에서 29개로 줄어 사전 기준을 통과하지 못했다. 최종 결정은 **기각**이며 정확도 후보는 배포하지 않는다. 결과와 판정 근거는 [`final_decision.json`](final_decision.json) 및 [`results/confirm/summary.json`](results/confirm/summary.json)에 있다. 확인 세트에 대한 추가 호출·재시도·재개·재튜닝은 하지 않는다.

## 데이터 구분과 해석

- 이전 본평가 1,000개는 이미 결과를 확인했다. 전부 탐색·개발 자료이며 독립 확인 세트나 새 성공 판정으로 다시 세지 않는다. `dev100_manifest.jsonl`은 그 중 고정된 100개이고, `dev1000_manifest.jsonl`은 전체 1,000개다. `neutral_full`은 이전 응답을 재사용하지 않고 1,000개에 새 중립 요청을 한 별도 개발 실험이지만, 정답은 여전히 같은 과거 평가에서 왔으므로 탐색 결과다.
- 개발 단계는 기준선과 `neutral_portion`, `volume_consistency`, `baseline_thinking1024`를 비교한다. 추가 모델 비교 `model_comparison/flash35_minimal`도 개발 자료 전용이다.
- 질량 보정은 과거 1,000개에서 그룹 분리 교차검증으로 세 가지 사전 기록된 계열(`log_mass`, `linear_mass`, `weighted_log_mass`)을 비교한다. MFDS 실험은 같은 과거 예측을 공개 원재료 부분 DB로 재생한다. 둘 다 탐색이며 운영 성능 또는 배포 승인으로 해석하지 않는다.
- 새 155개는 이전 선정과 추정 그룹 교집합이 없는 확인 세트다. 모두 측면 촬영이며, 원본이 없는 2개도 분모에 남겼다. 코드·모델·프롬프트·DB/정책·입력 manifest의 해시를 동결한 뒤 scorer가 gold를 한 번 열어 채점했다. 가설 탐색이나 요청 입력에 새 정답·재료·중량을 사용하지 않았다.
- 새 155개 확인 기준은 유효 paired 100개 이상, 기준 대비 열량 MAE 10% 이상 감소(전체 유효 예측과 같은 paired 표본 모두), 후보−기준 paired 오차 bootstrap 95% 구간 상한 <0, 전체 155개 기준 ±15% 이내 건수와 유효 영양 예측 건수 비악화다. 기준을 못 채우거나 실패하면 불충분/불채택으로 남기고 이 확인 세트에 맞춰 재튜닝하지 않는다.

## 예산과 실패 기록

- `cost_ledger.json`은 최초 평가 비용/예약액을 포함한 누적 원장을 상속한다. 과거 비용을 후속 실험 비용과 중복 합산하지 않는다. 전체 승인 상한은 과거분을 포함해 **US$30**이며, 호출 전후 비용은 같은 원장으로 확인한다.
- 자동 생성 재시도는 금지한다. API 오류, JSON 오류, 음식 후보 없음, 원본 누락, 미시도 상태를 각각 보존한다. 실패 표본을 분모에서 빼거나 표본을 임의 교체·재요청해 결과를 좋게 보이지 않는다. 유료 실행은 이 문서의 재현 예시를 그대로 실행하기 전에 누적 예약액과 잔여 상한을 확인한다.

## 실험 실행 기록과 재현 자료

아래 명령은 완료된 탐색·개발 단계의 실행 기록이다. 후속 성능 실험은 모두 끝났으므로 재현 목적으로도 유료 모델 명령을 다시 실행하지 않는다. 확인 세트는 단 한 번 실행했고 재시도·재개·재튜닝하지 않는다. 명령을 참고할 때 `run_model.py`와 `run_model_compare.py`는 Google SDK가 설치된 `../AI/ai-server/venv/Scripts/python.exe`를, MFDS grounding은 `../BE/venv/Scripts/python.exe`를 사용한다.

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

### 4. 동결된 최종 확인 실행 기록

후보 `flash35_minimal`과 실행 파일·입력·예산 freeze를 확인한 뒤 `run_confirmation.py`를 한 번 실행했다. 이 wrapper가 baseline과 후보 collector를 각각 concurrency 2로 동시에 실행해 최대 합산 concurrency 4를 사용하고, 두 arm은 같은 US$30 상한의 잠금 공유 ledger를 사용한다. 기존 arm별 runner를 단독 실행하거나 이 확인을 재실행·재개하지 않는다.

```powershell
& ..\AI\ai-server\venv\Scripts\python.exe experiments/accuracy_followup/run_confirmation.py
```

실제 출력은 `evaluation/tmp/followup-confirmation.log`에 저장했다. 확인 실행 시 `candidate_freeze.json`의 `prior_ledger_sha256`를 검사하고, 기존 ledger가 없거나 hash가 달라졌으면 API 수집을 거부한다. 동결된 wrapper SHA-256은 `82f30bb3d723b56f0fd798114cda33975b84cc618999e4172ea86a9dbd01e9c1`이다. 각 arm은 155행을 보존했고, 153개 원본에 응답을 받았으며, 원본이 없는 같은 2개 항목은 `not_attempted`로 남겼다. 완료 시 누적 원장에는 attempted 3826, settled 3816, unknown reserved 10, usage estimate US$7.3393675, charged/reserved US$12.3393675가 기록됐다. 정답 파일은 수집 wrapper가 열지 않는다.

Wrapper/예산 안전성에 대한 6개 오프라인 테스트가 통과했다. 테스트는 synthetic 입력·임시 ledger·대체 collector만 사용하며 API나 확인 정답을 읽지 않는다. 사전 기준 중 paired 유효 표본 100개 이상, 열량 MAE 10% 이상 감소, paired bootstrap 95% 구간 상한 음수는 통과했다. 다만 유효 열량 예측은 기준 153개에서 후보 151개로 줄었고, ±15% 이내 건수는 전체 155개 기준 30개에서 29개로 감소했다. 이 두 필수 기준 실패로 최종 판정은 **기각**이다. 판정은 [`final_decision.json`](final_decision.json), 지표는 [`results/confirm/summary.json`](results/confirm/summary.json)에 있다. 정확도 AI 후보는 배포하지 않으며 현재 AI robustness 버전 `a860b2fb3a2c53a4484ddc6673d86d938f039171`을 유지한다. frozen service prototype과 258개 mocked contract/regression 테스트 기록은 [`service_candidate/`](service_candidate/)에 보관했다. 별도의 BE retention-linkage 변경은 commit `c81ec8c4abfad226adf06698c2b42e05b1dd8f4d`로 배포됐고 GitHub Actions run `40176912543` 및 health 결과는 [`retention_linkage/deployment.json`](retention_linkage/deployment.json)에 기록돼 있다. 이 BE 변경은 과거 backfill이나 retention 개선 효과를 주장하지 않는다. 추가 수집, 재시도, 재개, 확인 세트에 맞춘 튜닝은 하지 않는다.

## 보관, 출처, 라이선스

- 추가 Nutrition5k 원본 이미지와 영상은 로컬 `data/nutrition5k_followup/images/`, `videos/`에 보관한다. 루트 `.gitignore`의 `*.png`, `*.h264` 규칙이 미디어 payload를 Git에서 제외한다. manifest, 출처, 해시, 무결성·디코딩 감사는 보존한다. 미디어가 Git에 포함되지 않았는지 추가 전 `git check-ignore`로 확인한다.
- Nutrition5k 출처는 Google Research, Thames et al. (2021)이며 데이터는 **CC BY 4.0**이다. 재배포 시 출처와 라이선스를 유지한다. 정답 영양은 재료 중량과 영양 자료를 바탕으로 계산된 값이며 열량계 직접 측정이 아니다.
- `grounding/`의 MFDS 자료는 공개 원재료 부분 데이터다. Nutrition5k 라이선스가 MFDS 원자료에 적용되는 것으로 표시하지 않으며, 공개 자료를 운영 DB dump와 혼동하지 않는다. 원자료별 출처와 제외 내역을 함께 유지한다.
- 데이터 동결·개봉 정책은 [`protocol_audit/README.md`](protocol_audit/README.md), 확인 기준과 새 그룹 한계는 [`protocol_audit/HANDOFF.md`](protocol_audit/HANDOFF.md)에 있다.
