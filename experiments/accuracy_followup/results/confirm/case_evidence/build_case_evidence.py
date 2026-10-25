"""Offline, deterministic post-freeze case illustrations; never edits predictions."""
import csv, hashlib, json, statistics
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'eatlog-validation-lab').is_dir())
LAB = ROOT / 'eatlog-validation-lab'
OUT = ROOT / 'report/final_report_work/final_confirmation_cases'
OUT.mkdir(parents=True, exist_ok=True)
CONF = LAB / 'experiments/accuracy_followup/results/confirm'
def read(p): return [json.loads(s) for s in p.read_text(encoding='utf-8-sig').splitlines()]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def index(p): return {r['sample_id']:r for r in read(p)}
b = index(CONF/'baseline/normalized.jsonl')
c = index(CONF/'flash35_minimal/normalized.jsonl')
m = index(LAB/'data/nutrition5k_followup/manifest.jsonl')
g = index(LAB/'data/nutrition5k_followup/gold_labels.jsonl')
raw = index(CONF/'flash35_minimal/raw.jsonl')
ai = index(CONF/'flash35_minimal/ai.jsonl')
rows = list(csv.DictReader((CONF/'cases.csv').open(encoding='utf-8-sig')))
csvrows = {(r['sample_id'],r['arm']):r for r in rows}
pairs=[]
for sid in sorted(b):
    if b[sid]['status'] == c[sid]['status'] == 'success':
        truth=g[sid]['truth']['calories_kcal']
        eb=abs(b[sid]['totals']['calories']-truth)
        ec=abs(c[sid]['totals']['calories']-truth)
        assert abs(eb-float(csvrows[sid,'baseline']['absolute_error_calories'])) < 1e-8
        assert abs(ec-float(csvrows[sid,'flash35_minimal']['absolute_error_calories'])) < 1e-8
        pairs.append((ec-eb,sid))
median=statistics.median(d for d,s in pairs)
selected=[('best_improved',min(pairs,key=lambda x:(x[0],x[1]))),
          ('worst_worsened',min(pairs,key=lambda x:(-x[0],x[1]))),
          ('median_delta',min(pairs,key=lambda x:(abs(x[0]-median),x[1])))]
def facts(sid):
    image=LAB/m[sid]['image_path']
    assert sha(image)==m[sid]['image_sha256']
    return {'sample_id':sid,'image_path':str(image.relative_to(ROOT)).replace('\\','/'),
            'image_sha256':sha(image),'source_url':m[sid]['source_url'],
            'camera_view':m[sid]['camera_view'],'image_dimensions':list(Image.open(image).size),
            'truth':g[sid]['truth'],'gold_ingredients':g[sid]['ingredients'],
            'baseline_normalized':b[sid],'candidate_normalized':c[sid],
            'baseline_csv':csvrows[sid,'baseline'],'candidate_csv':csvrows[sid,'flash35_minimal']}
cases=[]
for role,(delta,sid) in selected:
    item=facts(sid); item.update(selection_role=role,absolute_calorie_error_delta_kcal=delta)
    cases.append(item)
invalid=[]
for sid in sorted(c):
    if b[sid]['status']=='success' and c[sid]['status']!='success':
        item=facts(sid)
        item['candidate_ai_normalized']=ai[sid]
        item['candidate_raw_candidates']=json.loads(raw[sid]['raw_text'])['candidates']
        item['visual_inspection_ko']='원본 사진을 직접 확인했으며 베리류와 블루베리로 보이는 작은 열매 1개가 보인다. 사진만으로 실제 질량·정확한 영양값은 검증하지 않았다.'
        item['failure_explanation_ko']='모델 원문은 블루베리 질량을 5 g 미만으로 추정했다. 고정 AI 정규화의 5–3000 g 허용 범위에서 질량이 null이 되고 영양량도 null이 되었다. BE는 선택 음식 중 영양량이 없는 항목 때문에 전체 합계를 incomplete_nutrition으로 처리했다. 이는 음식 미검출이나 원문 JSON 오류로 단정할 사례가 아니다.'
        invalid.append(item)
assert len(pairs)==151 and len(invalid)==2
sources=[CONF/'summary.json',CONF/'cases.csv',CONF/'baseline/normalized.jsonl',CONF/'flash35_minimal/normalized.jsonl',CONF/'flash35_minimal/ai.jsonl',CONF/'flash35_minimal/raw.jsonl',LAB/'data/nutrition5k_followup/manifest.jsonl',LAB/'data/nutrition5k_followup/selection_manifest.jsonl',LAB/'data/nutrition5k_followup/gold_labels.jsonl',LAB/'scripts/evaluate/replay_worker.py',LAB/'evaluation/tmp/code/improved_ai/ai-server/app/services/vision.py']
doc={'scope':'Post-freeze, post-scoring illustrative confirmation cases. Candidate remains rejected.',
 'selection_rule':{'population':'151 images where both normalized arms have status=success; all 155 selected remain the overall evaluation denominator',
 'delta_definition':'abs(candidate normalized calorie prediction - truth) - abs(baseline normalized calorie prediction - truth); negative is improvement',
 'best':'minimum (delta, sample_id)','worst':'minimum (-delta, sample_id)',
 'median':'minimum (abs(delta - population median delta), sample_id)',
 'population_median_delta_kcal':median,'pair_count':len(pairs),
 'invalids':'all cases with baseline success and candidate non-success; excludes 2 shared not_attempted rows'},
 'prediction_mapping':'Captions use BE normalized totals, not raw_model_prediction. Highest-confidence candidate per group is resolved; sum nutrition_per_unit nutrient * estimated_serving; mass is resolved grams sum. Missing selected nutrition invalidates whole total.',
 'source_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sources},
 'cases':cases,'additional_candidate_invalids':invalid,
 'attribution':'사진: Nutrition5k, Google Research, CC BY 4.0. https://github.com/google-research-datasets/Nutrition5k ; https://creativecommons.org/licenses/by/4.0/',
 'disclaimer_ko':'예시는 사전에 명시한 수치 규칙으로 고른 개별 사례이며 전체 성능을 대표하지 않습니다. 후보는 확인 평가의 채택 조건을 충족하지 못했습니다.',
 'photo_processing':'Original image content preserved; uniform aspect-fit resizing only, no crop/retouch/overlay on photos.'}
for dest in [OUT/'case_evidence.json',CONF/'case_evidence.json']:
    dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

FONT='C:/Windows/Fonts/malgun.ttf'
def font(n): return ImageFont.truetype(FONT,n)
def text(draw,xy,s,size=30,fill='#253047'): draw.text(xy,s,font=font(size),fill=fill)
def fit(canvas,path,box):
    im=Image.open(path).convert('RGB'); im.thumbnail((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
    canvas.paste(im,(box[0]+(box[2]-box[0]-im.width)//2,box[1]+(box[3]-box[1]-im.height)//2))
def num(v): return f'{v:.2f}'
def footer(draw,y):
    text(draw,(45,y),'사진: Nutrition5k / Google Research · CC BY 4.0 (원본 비율 유지, 사진 내용 변경 없음)',25)
    text(draw,(45,y+43),'개별 예시는 전체 성능을 대표하지 않음 · 최종 후보는 채택 조건 미충족',25)
def draw_pairs():
    im=Image.new('RGB',(2400,1130),'white'); d=ImageDraw.Draw(im)
    text(d,(45,25),'확인 평가: 수치 규칙으로 고른 실제 사진 3사례',45)
    text(d,(45,91),'열량 절대오차 변화 = 후보 오차 - 기준 오차 (음수: 개선) · 유효 쌍 151건',30)
    labels=['가장 크게 개선','가장 크게 악화','오차 변화 중앙값']
    for i,item in enumerate(cases):
        x=40+i*800; sid=item['sample_id']; tr=item['truth']; bt=item['baseline_normalized']['totals']; ct=item['candidate_normalized']['totals']
        text(d,(x,155),labels[i],34)
        text(d,(x,209),sid,25)
        fit(im,ROOT/item['image_path'],(x,255,x+740,673))
        text(d,(x,704),f"정답  {num(tr['calories_kcal'])} kcal / {num(tr['mass_g'])} g",30)
        text(d,(x,757),f"기준  {num(bt['calories'])} kcal / {num(bt['mass_g'])} g",30)
        text(d,(x,810),f"후보  {num(ct['calories'])} kcal / {num(ct['mass_g'])} g",30)
        eb=abs(bt['calories']-tr['calories_kcal']); ec=abs(ct['calories']-tr['calories_kcal'])
        text(d,(x,871),f'열량 오차  {eb:.2f} → {ec:.2f} kcal',28)
        text(d,(x,920),f"오차 변화  {item['absolute_calorie_error_delta_kcal']:+.2f} kcal",30)
    footer(d,1010); im.save(OUT/'confirmation_paired_cases.png',dpi=(220,220))
def draw_invalid():
    im=Image.new('RGB',(2200,1280),'white'); d=ImageDraw.Draw(im)
    text(d,(45,25),'추가 무효 2건: 소량 재료가 정규화 하한에 걸린 사례',42)
    text(d,(45,91),'두 사진 모두 음식과 작은 블루베리가 보임 · 실제 질량은 사진만으로 확정할 수 없음',28)
    for i,item in enumerate(invalid):
        x=45+i*1100; tr=item['truth']; bt=item['baseline_normalized']['totals']; sid=item['sample_id']
        blue=next(r for r in item['candidate_raw_candidates'] if r['food_name']=='블루베리')
        rt=item['candidate_normalized']['raw_model_prediction']['totals']
        text(d,(x,157),sid,30); fit(im,ROOT/item['image_path'],(x,218,x+1010,786))
        text(d,(x,815),f"정답  {num(tr['calories_kcal'])} kcal / {num(tr['mass_g'])} g",30)
        text(d,(x,867),f"기준  {num(bt['calories'])} kcal / {num(bt['mass_g'])} g",30)
        text(d,(x,919),'후보  합계 무효 (incomplete_nutrition)',30)
        text(d,(x,971),f"참고: 원문 {num(rt['calories'])} kcal / {num(rt['mass_g'])} g",26)
        text(d,(x,1020),f"원문 블루베리 {blue['estimated_serving_g']:g} g → 5 g 하한 미달",28)
        text(d,(x,1066),'AI 질량·영양 null → BE 전체 합계 무효',28)
    footer(d,1165); im.save(OUT/'confirmation_invalid_cases.png',dpi=(220,220))
draw_pairs(); draw_invalid()
doc['generation_script_sha256']=sha(Path(__file__))
doc['figure_sha256']={p.name:sha(p) for p in [OUT/'confirmation_paired_cases.png',OUT/'confirmation_invalid_cases.png']}
for dest in [OUT/'case_evidence.json',CONF/'case_evidence.json']:
    dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(json.dumps({'output':str(OUT),'paired_ids':[x['sample_id'] for x in cases],'invalid_ids':[x['sample_id'] for x in invalid]},ensure_ascii=False))
