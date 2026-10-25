# 후속 데이터와 최종보고서 인계

## 후속 검증 데이터

- 소유/신규 경로: `experiments/accuracy_followup/protocol_audit/`, `data/nutrition5k_followup/`.
- 기존 Nutrition5k 원본과 고정 평가 manifest는 수정하지 않았다. 기존 DOCX/PDF 보고서도 이번 단계에서 수정하지 않았다.
- 원천 QC 적격 1,175추정그룹 중 기존 1,020선정과 겹치지 않는 잔여 **155그룹 전부**를 새 검증으로 동결했다. 기존 v1 탈락 pilot을 포함한 이전1,023그룹과 교집합0. 공식 train136/test19이며 모두 측면이다.
- 공식원본153개 존재, 카메라A150/B3; 모든카메라가없는2개는 고정분모155에 유지. 생성모델호출0. 원본카메라A→B→C→D firstavailable/frame0 규칙이며 유리한 프레임을 선택하지 않았다.
- 입력용 `selection_manifest.jsonl` / 실제다운로드용 `manifest.jsonl`에는 **truth/ingredients 없음**. `gold_labels.jsonl`은 최종후보 동결후 채점담당만 사용. 가설작성 AI/BE agent에게 전달하지 말 것.
- 고정 입력 목록 SHA256: `750dbf9756ba6485ef129c56d7bb3b58d54e18ed9e72c4f1daef097051099018`.
- 결과 QA와 실제 manifest hash는 `data/nutrition5k_followup/integrity_audit.json` / `freeze.json`이 정본이다. `decode_audit.jsonl`에 각 파일 SHA/픽셀 SHA 기록. 구조/디코딩 확인은 전수 의미적 음식-정답 일치 검토가 아니다.
- 기존 1,000개는 탐색용으로만 재사용. 후보 코드·모델·프롬프트·DB snapshot·보정식 동결 뒤 새155정답을한번만개봉. 선정전후/가설별판정은 유지한다.

### 부모가 승인한 확인 판정

유효 paired 최소100개, 열량MAE 상대10%이상감소, paired오차차이(후보−기준)bootstrap95%CI상한<0, 전체155분모의±15%율및유효영양예측수악화없음. 이는리뷰원문이지정한숫자가아닌이번후속연구의사전기준이다. 표본수가부족하거나실패하면불충분/불채택으로기록하고새155에재튜닝해서성공을주장하지않는다. 상세8항목은이폴더README.md.

추정그룹독립성/공개벤치마크노출/측면-only분포/한식·포장비대표성한계를유지한다. 새1,000개독립그룹을맞추려고기존접시증분촬영을분리하지않았다.

## 최종보고서 현황

기존확정본(현재변경하지않음):

- `C:/Users/741u7/Desktop/soma_project/report/Eat로그_EBD_최종보고서_20261025.docx`
- 동일이름 `.pdf` (754,503bytes)
- DOCX SHA256 `3ea648e7fae85d741c33c534dba4afe7626c3e3eb0e914d73f70f2bdbc0cebcb`
- 26쪽(요약1+목차1+본문24); 원본양식본문50쪽이내, 25필수제목순서유지. 최초제공8파일해시보존.
- 최종PNG: `report/final_report_work/render_final_real/page-1.png` … `page-26.png`
- `report/final_report_work/qa_summary.json`: 26쪽시각검수완료, 구조·목차·원본해시통과. 12/13/15쪽하단여백이비교적좁지만겹침/잘림없음.
- 현재8쪽이전평가,9쪽합성,10–13쪽기존실사진평가,19–20쪽운영지표,21쪽Meta증빙,22쪽배포,25–26쪽리뷰/리텐션.
- 상세18항목: `report/리뷰_반영_리텐션_검증_매핑_20261025.html`.

## 보고서 개정 절차

**26쪽확정본을새checkpoint폴더에복사한뒤**개정한다. 기존 `checkpoint_01_contracts_deployed`는 더 오래된21쪽합성단계로, 이번26쪽보존본을대신하지않는다.

작업폴더: `C:/Users/741u7/Desktop/soma_project/report/final_report_work`.

- `build_report.py`: 원본양식OOXML 복사기반생성. 원본파일덮어쓰기금지. 신규media파일명은 반드시ASCII(`report_image_108.jpg`형태). 한글media파일명은Word열기오류의원인이었다.
- `real_evaluation_section.py`: 기존1,000개실사진평가본문. 새결과는기존결론을소급변경하지않고 별도후속평가절로추가한다.
- `prepare_real_evaluation_report.py`: 기존평가근거복사/차트. 유료API없음. 새로운평가를반영하려면 별도데이터파일/함수로추가한다.
- `build_review_mapping.py`, `build_source_ledger.py`: 리뷰18개와근거16종. 신규가설·결과·배포를근거ID로추가한다.
- `render_with_word.py`, `word_export_pdf.ps1`: Word읽기전용COM PDF변환→공식render_docx.py/Poppler PNG. 변환은`require_escalated`가필요했다. DOCX를Word에서저장하지않는다.
- `update_toc.py <PDF>`: 실제페이지로목차캐시갱신→다시렌더.
- `verify_report.py <PDF>`: 구조/25제목/원본8해시/목차/정확문구검사.
- `finalize_report.py <최종렌더폴더> --all-pages-visually-verified`: **최종모든PNG를직접본후에만**실행. 루트PDF복사+QA26(또는새쪽수)PNGhash/시각검수기록.
- Python: `C:/Users/741u7/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
- documents render skill: `C:/Users/741u7/.codex/plugins/cache/openai-primary-runtime/documents/26.1020.11618/skills/documents/`.
- Matplotlib 임시deps는 `report/final_report_work/plot_deps`이며실행시읽기ACL때문에escalation이필요했음. 기본구조도/퍼널은PIL.

### 이번에 반드시 추가할 내용

새가설별문제/구현/탐색결과/새155확인결과/회귀/배포판정, 실패·악화·채택보류도포함. 기존필터의1,000개일반접시평가개선0사실은보존한다. 새기준모델과후보의상이한입력·DB·추가호출·비용조건을명시한다. 기존평가를튜닝에사용했다는것과새155측면만의제한도명시한다. 운영유지율개선/사용자보정시간은실험없이만들지않는다. 미완료항목문구는정확히 **결과 확인후 추가 혹은 수정필요**.

Meta추가조회는사용자가중단요청했다. `report/Meta_조회제한_증빙_20261025/02_보고서용_권한영역.jpg`만보고서/최종응답에사용하고이메일포함01원본은로컬내부보관. 후속권한질문/사이트수정금지. FE수정금지.

## 재실행주의

`audit_and_collect.py prepare/resolve`는이미동결된목록덮어쓰기를거부한다. `download`는같은출처복구용, `validate`는전수해시/디코딩/기존집합픽셀중복검사와freeze상태갱신용이다. 둘다생성모델호출없음. 대용량이미지/영상은루트.gitignore에서제외한다.
