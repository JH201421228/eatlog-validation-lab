# 최초 합성 계약 실험의 이관

2026-10-25 사용자 지시에 따라 팀 저장소에서 개인 실험 저장소로 옮겼습니다. 서비스의 필수 회귀 테스트는 팀 저장소에 남기고, 실험 실행기·결과·해석 문서의 정본은 이 저장소에서 관리합니다.

## 재현 환경

작업 폴더에 `BE/`, `AI/`, `FE/`, `eatlog-validation-lab/`가 나란히 있는 구성을 기본으로 사용합니다. 아래 명령은 **eatlog-validation-lab 루트**에서 실행합니다. 다른 구성은 `EATLOG_BE_ROOT`, `EATLOG_AI_ROOT`로 해당 Git 저장소 루트를 지정합니다. 기존 저장소의 Python 의존성을 사용하며 실제 모델 API를 호출하지 않습니다.

```powershell
../BE/venv/Scripts/python experiments/contracts/be_packaged_nutrition/run.py
../BE/venv/Scripts/python experiments/contracts/be_packaged_nutrition/run_display_experiment.py --fe-root ../FE
../AI/ai-server/venv/Scripts/python -m experiments.contracts.ai_output_validation.run_experiment --baseline-ref 9ce6e9ee029d5891f92b2488672404d861c37ec1 --output experiments/contracts/ai_output_validation/baseline.json
../AI/ai-server/venv/Scripts/python -m experiments.contracts.ai_output_validation.run_experiment --output experiments/contracts/ai_output_validation/after.json
```

이관 직전 서비스 코드 식별:

- BE baseline: `dc11453426a3db365fc12321ec1e49f9705e23fb`, 배포 후: `7249699d09fd0f0d34080990c77c63328da01567`.
- AI baseline: `9ce6e9ee029d5891f92b2488672404d861c37ec1`, 배포 후: `8f41c67c8e6db4f5690bbda4e560c211fa5b65ed`.

`be_packaged_nutrition/README.md`와 `ai_output_validation/README.md`의 초기 실행 기록은 당시 팀 저장소 경로를 기록한 이력입니다. 이관 후 실행 위치는 위 명령을 사용합니다. 모든 입력은 합성 사례이며 실제 사진 정확도 데이터셋과 별도로 해석합니다.
