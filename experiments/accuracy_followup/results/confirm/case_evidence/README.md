# Confirmation case illustrations

This is post-freeze, post-scoring report evidence. It does not tune predictions or change the rejected confirmation decision.

Run `python experiments/accuracy_followup/results/confirm/case_evidence/build_case_evidence.py` from this repository in the existing `soma_project` workspace. It uses Python and Pillow, existing local images, scored labels, and archived normalized responses. It makes no API calls.

The script writes two Korean-captioned PNGs and JSON into `report/final_report_work/final_confirmation_cases/` in the parent workspace, plus `../case_evidence.json` here. The JSON records deterministic selection rules, full source numbers, image/source hashes, generation-script hash, and figure hashes. Source photographs are referenced by local path and SHA-256; image payloads are not included in this folder.

Selection uses the minimum and maximum change in absolute calorie error and the case closest to the median change among all 151 jointly valid cases, with sample ID as the tie break. Both additional candidate invalids are also included. The overall evaluation denominator remains 155. Individual examples do not represent overall performance.

Photos: Nutrition5k, Google Research, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source project: https://github.com/google-research-datasets/Nutrition5k. Photographs retain their natural aspect ratio and content; only uniform resizing for layout is applied.
