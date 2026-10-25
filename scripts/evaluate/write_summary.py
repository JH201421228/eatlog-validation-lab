"""Render an evidence-linked Korean summary from final computed metrics."""
from __future__ import annotations

from common import EVAL, read_json


def fmt(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


def main():
    summary = read_json(EVAL / "results/blind_test_no_db_summary.json")
    before = summary["versions"]["baseline"]
    after = summary["versions"]["improved"]
    cost = summary["cost_all_splits"]
    paired = summary["paired_calories"]
    transition = paired["transition_counts"]
    lines = [
        "# Nutrition5k 실제 사진 고정 평가 결과",
        "", "## 범위와 실행", "",
        f"- 평가 선정: {summary['selected_dishes']:,}개. 실제 이미지 {summary['locally_present_images']:,}개, 모델 요청 {summary['attempted_generations']:,}회, 응답 {summary['responses_received']:,}회.",
        f"- 원본 이미지 누락 {summary['source_images_unavailable_count']}개와 API 실패 {summary['api_generation_failed_count']}회를 구분하고, 모두 전체 1,000개 성능 분모에 남겼다. 자동 재시도는 없다.",
        "- 응답 중 빈 candidates 2건은 원본을 시각 점검하니 스마트폰 촬영장치/그릇 바닥으로 음식이 보이지 않거나 내용을 식별하기 어려웠다. 모델 오거부로 단정하지 않으며 입력 가시성과 이미지-영양 라벨 정합의 한계로 기록한다. 유효 영양 예측은 994개다.",
        "- 모델: Gemini 2.5 Flash, 원본 사진 한 장, temperature 0, seed 20260722, thinking 0, 출력 상한 4096. 메뉴 정답 Top-1은 측정하지 않았다.",
        "- 같은 원본 모델 응답을 수정 전/후 AI 정규화와 BE 영양 산식에 재생했다. 검색 grounding·영양 DB·식습관 보정은 비활성화했다. 서비스 전체 운영 정확도 평가가 아니다.",
        "- 유효 pilot 20개와 QC에서 제외한 pilot 호출 3개는 본평가 성능 집계와 분리했다. 이 3회도 총 비용에서 빼지 않았다.",
        "", "## 영양 및 중량 오차", "",
        "| 항목 | 유효 예측 | 수정 전 MAE | 수정 후 MAE | 수정 후 MAPE | 수정 후 WAPE |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {"calories": "열량 (kcal)", "mass_g": "중량 (g)", "carbs": "탄수화물 (g)", "protein": "단백질 (g)", "fat": "지방 (g)"}
    for key, label in labels.items():
        old, new = before["nutrients"][key], after["nutrients"][key]
        lines.append(f"| {label} | {new['valid_prediction_count']} | {fmt(old['mae'])} | {fmt(new['mae'])} | {fmt(new['mape_percent'])}% | {fmt(new['wape_percent_mae_over_mean_truth'])}% |")
    kcal = after["nutrients"]["calories"]
    lines += [
        "",
        f"칼로리 ±15% 이내는 전체 선정 1,000개 기준 **{fmt(kcal['within_15_percent_of_all_selected'])}%** ({kcal['within_15_percent_count']}개), 유효 예측 기준 {fmt(kcal['within_15_percent_of_valid_predictions'])}%다.",
        "",
        "MAPE는 사례별 상대오차의 평균이며, WAPE는 MAE/평균 정답값과 같다. 과거 프로젝트의 29.4% 수치나 논문 수치와 데이터·분할·정의가 다르므로 직접 개선율로 비교하지 않는다.",
        "", "## 동일 응답 후처리 비교", "",
        f"- 유효 대응 사례 {paired['valid_pair_count']}개: 절대오차 감소 {transition.get('improved', 0)}개, 증가 {transition.get('worsened', 0)}개, 동일 {transition.get('same_error', 0)}개.",
        f"- 영양/선택 결과 변경 사례 {paired['changed_prediction_cases']}개. 유효→누락 전환 {transition.get('valid_to_missing', 0)}개.",
        f"- 평균 칼로리 절대오차 차이(수정 후−전): {fmt(paired['mean_absolute_error_delta_improved_minus_baseline'], 6)} kcal. 사례 단위 bootstrap 95% 구간: {paired['bootstrap_95_percent_ci']}.",
        f"- 선택된 음식 그룹 {after['selected_food_groups']}개 중 package 있음 {after['selected_packaged_foods']}개, printed_kcal 있음 {after['selected_foods_with_printed_kcal']}개. 일반 접시 데이터가 포장 산식 개선의 성능 증거를 제공한다고 가정하지 않는다.",
        "",
    ]
    if paired["mean_absolute_error_delta_improved_minus_baseline"] == 0:
        lines.append("**이번 실제 사진 평가에서 후처리로 평균 칼로리 오차가 줄어든 효과는 관측되지 않았다.** 합성 회귀 통과는 방어 규칙의 계약 검증이며 사진 인식·중량 추정 정확도 개선의 증거로 대체하지 않는다.")
    raw = summary["versions"]["raw_model"]["nutrients"]["calories"]
    lines += ["", f"정규화 전 모델 수치의 직접 합산 MAE는 {fmt(raw['mae'], 4)} kcal, 수정 전/후 BE 계산은 각각 {fmt(before['nutrients']['calories']['mae'], 4)}/{fmt(kcal['mae'], 4)} kcal다. 미세한 반올림 차이를 인식 개선으로 해석하지 않는다."]
    oracle_path = EVAL / "results/oracle_mass_diagnostic.json"
    if oracle_path.exists():
        oracle = read_json(oracle_path)["oracle_mass_calorie_metrics"]
        lines += ["", "## 정답 중량을 넣는 가상 진단", "",
                  "평가 완료 후 탐색적으로 `예측 열량 × 정답 총중량 / 예측 총중량`을 계산했다. 모델에 없었던 정답 중량을 사후 제공하는 oracle 진단이며 실제 기능·새 모델 호출·검증된 성능 개선이 아니다. 추정 영양밀도와 음식 구성의 오차는 남는다.", "",
                  f"같은 유효 {oracle['valid_prediction_count']}개에서 가상 열량 MAE {fmt(oracle['mae'])} kcal, MAPE {fmt(oracle['mape_percent'])}%, WAPE {fmt(oracle['wape_percent_mae_over_mean_truth'])}%, 전체1,000개 ±15%율 {fmt(oracle['within_15_percent_of_all_selected'])}%다. 중량 오차를 없애도 열량이 정답이 된다는 뜻이 아니다."]
    lines += ["", "## Confidence 탐색 분석", "",
              "접시의 음식 그룹별 최상위 후보 confidence 중 최소값으로 구간을 나눴다. 음식명 confidence는 칼로리 정확 확률이 아니다. 구간은 점수 열람 전에 고정했으며 threshold 튜닝이나 자동 보정에 사용하지 않았다.", "",
              "| 최소 confidence | n | 유효 영양 예측 | 전체 구간 기준 ±15% | MAE (kcal) | MAPE |", "|---|---:|---:|---:|---:|---:|"]
    for label, metric in summary["exploratory_confidence_vs_calorie_error"]["bins"].items():
        lines.append(f"| {label} | {metric['selected_count']} | {metric['valid_prediction_count']} | {fmt(metric['within_15_percent_of_all_selected'])}% | {fmt(metric['mae'])} | {fmt(metric['mape_percent'])}% |")
    lines += [
        "", "## 지연과 비용", "",
        f"- 생성 호출 지연 p50 {fmt(summary['latency_ms']['p50'])} ms / p95 {fmt(summary['latency_ms']['p95'])} ms. 평가 timeout은90초이며 운영 성공률로 해석하지 않는다.",
        f"- pilot 및 QC 제외 호출 포함 총 {cost['attempted_generations']}회. usage 확인분 단가 추정 **US${cost['usage_estimated_usd']:.7f}**, 미확인 요청 {cost['unknown_reserved_requests']}회 선예약까지 포함한 보수적 장부 **US${cost['charged_or_reserved_usd']:.7f}**. US$30 상한을 지켰다.",
        "- 이는 실제 청구서 확인액이 아니다. 2026-10-25 확인한 [공식 표준 단가](https://ai.google.dev/gemini-api/docs/pricing), 입력 $0.30/M·출력 $2.50/M을 사용했다. 사용량이 없는 timeout은 요청당 $0.50을 계속 예약한다.",
        "", "## 재현 자료와 한계", "",
        "- [사전 계획과 QC/source 수정 이력](PROTOCOL.md), [v3 고정 해시](manifest_freeze_v3.json), [코드 commit/hash](source_index.json), [요청 설정](request_config.json)",
        "- [전체 요약 JSON](results/blind_test_no_db_summary.json), [1,000개 사례 CSV](results/blind_test_no_db_case_metrics.csv), [변경 사례](results/blind_test_no_db_changed_cases.jsonl)",
        "- [수정 전 결과](results/blind_test_baseline_no_db.jsonl), [수정 후 결과](results/blind_test_improved_no_db.jsonl), [재현용 모델 원본 응답](evidence/model_responses.jsonl)",
        "- [요청 이미지 SHA 전수 감사](evidence/image_request_audit.json), [source 변경 독립 감사](evidence/source_amendment_audit.json), [비용 장부](cost_ledger.json), [오프라인 테스트](verification.txt)",
        "- [음식 비가시성 기권 2건 시각 점검](results/abstention_visual_review.json), [정답 중량 가상 진단](results/oracle_mass_diagnostic.json)",
        "- 데이터는 공개 구내식당 음식이다. 한국 음식·포장 제품·실제 사용자 리텐션·추천 성능으로 일반화할 수 없다. 원본 공식 train 출신을 포함하고 모델의 사전학습 노출은 알 수 없다.",
        "- 증분 촬영은 시간·재료 중량으로 보수적으로 묶었으나 공식 물리 접시 ID가 없어 독립성을 확정하지 못한다. 사례 단위 bootstrap은 잔여 상관성을 반영하지 않는다.",
        "- 후속 한국 음식/소형 포장/실측 중량 검증 및 실제 저장·수정률 추적: **결과 확인후 추가 혹은 수정필요**.",
        "",
    ]
    (EVAL / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print({"written": "evaluation/RESULTS.md"})


if __name__ == "__main__":
    main()
