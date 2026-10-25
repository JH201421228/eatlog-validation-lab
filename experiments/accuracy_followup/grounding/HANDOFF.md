# Grounding 작업 인계

완료: 공개 MFDS 원재료 snapshot 구축, 3개 정책 구현, 기존 1,000개 무과금 재생·채점,
9개 회귀 검증. 생산 app/FE/DB/공용 평가·비용 원장 수정 0. Git 작업은 부모 담당이다.

## 바로 읽을 파일

- `README.md`: 해석·한계·전체 명령
- `results/score_summary.json`: 전체/촬영각도/공식 train/test 결과, 짝지은 비교
- `results/coverage.json`: 매칭·fallback 사유
- `results/prediction_freeze.json`: 채점 전 입력/코드/예측 해시
- `reference_audit.json`: 실제 출처·중복/제외·importer 버전 해시
- `results/exact_name_ambiguity.json`: 총칭 이름 충돌 감사

## 판단

994/1,000 유효. MAE: no-DB107.42 → 현재 exact공개부분DB110.81 → 품질gate110.81 →
조리상태107.87kcal. 상태 방식은 현재 exact보다 −2.94kcal(177개 개선/133개 악화),
그러나 no-DB보다 +0.45kcal다. **정확도 개선으로 승인할 근거 부족. 배포하지 않음.**
양·음식 선택 불일치 0. 후보 대안이 있던 144개 그룹도 기존 confidence 선택을 유지했다.

현재 운영 DB dump가 아닌 공개 부분 DB이며 mock40개는 제외했다. 동명총칭 274개,
이번 선택 58음식에 모호성이 있다. 특히 양파41.4/354, 메밀24/363kcal 등 실제로 다른
식품이 정규화 이름만 같을 수 있다. 현코드는 id순이라 운영 삽입순서가 다르면 달라진다.
새 후속 분석·production 수정은 시작하지 않았다.

## 재생

루트에서 BE `5b77e1d` virtualenv로 실행:

```powershell
../BE/venv/Scripts/python experiments/accuracy_followup/grounding/run_experiment.py --input experiments/accuracy_followup/grounding/model_candidates.jsonl
../BE/venv/Scripts/python experiments/accuracy_followup/grounding/score_experiment.py
```

예측 재생은 정답을 읽지 않는다. 입력 보관본은 원래 tmp 입력과 동일 해시다.
결과는 이 디렉터리 `results/`에만 쓴다. reference를 새로 만들 필요는 없으며 원본과
importer가 그대로일 때 `prepare_reference.py`로 재생성할 수 있다.
