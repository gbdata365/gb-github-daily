#!/usr/bin/env python3
"""Collect GitHub repos into date-stamped JSON, then describe each one from its README.

설명 순서(2026-10-27):
  1) README 를 GitHub API 로 받아 '기능' 절의 실제 목록·첫 소개 문단을 뽑는다(AI 없음, 비용 없음).
  2) ANTHROPIC_API_KEY 가 있으면 1)의 README 발췌를 근거로 Claude 가 한국어로 요약한다.
     키가 없거나 실패하면 1)의 README 원문 발췌를 그대로 보여 준다 — 모든 저장소에 같은 문구를 찍지 않는다.
분야·검색어·개수는 config.json 에서 읽는다.
"""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date().isoformat()
LIMIT = int(CONFIG.get('per_category', 10))            # 분야별 최대 개수
MIN_PER = int(CONFIG.get('min_per_category', 5))        # 분야별 최소 개수
KEEP_STARS = int(CONFIG.get('keep_min_stars', 0))       # 이 스타 이상만 싣되, 모자라면 최소 개수까지 스타 순으로 채움
CREATED_AFTER = CONFIG.get('created_after', '')        # 이 날짜 이후 만들어진 저장소만(YYYY-MM-DD, 비우면 제한 없음)
MIN_STARS = int(CONFIG.get('minimum_stars', 10))
PER_QUERY = int(CONFIG.get('candidates_per_query', 30))
MAX_AI = int(CONFIG.get('max_ai_summaries_per_run', 70))
SEARCHES = {c['label']: c['queries'] for c in CONFIG['categories']}
HEADERS = {'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'github-daily-open-source/1.0'}
if os.environ.get('GITHUB_TOKEN'): HEADERS['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']

# README 절 제목으로 '기능'·'활용' 절을 찾는다 — 소문자로 비교
FEATURE_HEAD = re.compile(r'feature|capabilit|highlight|why (use|choose|should)|what (is|can|does)|key |overview|benefit|주요 기능|특징|기능')
USE_HEAD = re.compile(r'use case|use-case|example|who (is|should)|application|showcase|projects using|활용|사례|예시')
SKIP_HEAD = re.compile(r'install|quick ?start|getting started|setup|licen[sc]e|citation|contribut|sponsor|resources|docs|documentation|community|faq|table of contents|contents|acknowledg|star history|support|changelog|roadmap|설치|라이선스|기여')
README_CHARS = 60000      # 받아 둘 README 최대 길이
EXCERPT_CHARS = 2500      # AI 에 근거로 줄 발췌 최대 길이


def api_search(query, sort='stars', per_page=PER_QUERY):
    q = query if 'archived:' in query else query+' archived:false fork:false'
    if CREATED_AFTER and 'created:' not in q:
        q += ' created:>='+CREATED_AFTER
    for attempt in range(4):
        try:
            r = requests.get('https://api.github.com/search/repositories', headers=HEADERS,
                params={'q':q, 'sort':sort, 'order':'desc', 'per_page':per_page}, timeout=35)
            if r.status_code in (403,429):
                pause = min(int(r.headers.get('Retry-After','0') or '0') or (10 * (attempt+1)), 90)
                print('rate limit:', r.status_code, 'retry in', pause, file=sys.stderr)
                if attempt == 3: r.raise_for_status()
                time.sleep(pause); continue
            r.raise_for_status()
            return r.json().get('items',[])
        except (requests.RequestException,ValueError) as ex:
            if attempt == 3: raise
            print('retry:',ex,file=sys.stderr); time.sleep(3*(attempt+1))
    return []


def fetch_readme(repo_id):
    try:
        r = requests.get(f'https://api.github.com/repos/{repo_id}/readme', timeout=30,
                         headers={**HEADERS, 'Accept':'application/vnd.github.raw'})
        return r.text[:README_CHARS] if r.status_code == 200 else ''
    except requests.RequestException:
        return ''


def _plain(s):
    """마크다운 한 줄을 읽기 쉬운 글로 — 그림·링크 주소·강조 기호·HTML 태그 제거."""
    s = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', s)
    s = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', s)
    s = re.sub(r'\[([^\]]*)\]\[[^\]]*\]', r'\1', s)      # 참조형 링크 [글][ref]
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'[*_`]{1,3}', '', s)
    s = re.sub(r'\s+', ' ', s).strip(' -–—:|')
    return s


def readme_sections(md):
    """README → [(절 제목, [글머리표 항목], 첫 문단)] — 코드 블록 안의 '#' 은 제목으로 보지 않는다."""
    md = re.sub(r'```.*?```', '', md, flags=re.S)
    md = re.sub(r'<!--.*?-->', '', md, flags=re.S)
    secs, head, bullets, para = [], '', [], []
    cont = False                                # 바로 앞 줄이 글머리표 항목이었나(여러 줄 항목 잇기)

    def flush():
        items = [t[:220] for t in (_plain(x) for x in bullets) if len(t) >= 3]
        secs.append((head, items, ' '.join(para)))
    for line in md.splitlines():
        m = re.match(r'^\s{0,3}(#{1,4})\s+(.*)', line)
        if m:
            flush(); head, bullets, para = _plain(m.group(2)), [], []
            cont = False
            continue
        b = re.match(r'^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)', line)
        if b:
            raw = b.group(1).strip()
            cont = not re.fullmatch(r'[^\w]*\[[^\]]*\]\((#|https?://)[^)]*\)[^\w]*', raw)   # 링크만 있는 목차·자료 목록은 버림
            if cont:
                bullets.append(raw)
        elif cont and line.startswith((' ', '\t')) and line.strip():
            bullets[-1] += ' ' + re.sub(r'^(?:[-*+]|\d+[.)])\s+', '', line.strip())   # 하위 항목은 이어 붙임
        elif not line.strip():
            cont = False
        elif not bullets and len(' '.join(para)) < 600 and not line.lstrip().startswith('>') \
                and len(re.findall(r'\]\(|<a\s', line)) < 3 and line.count('|') < 3:   # 안내 상자·언어 선택 줄은 소개가 아님
            t = _plain(line)
            short_html = line.lstrip().startswith('<') and len(t.split()) < 5    # 로고·배지·언어 선택 같은 HTML 조각
            if t and not short_html and not line.rstrip().endswith('|') and not re.fullmatch(r'[\W\d]*', t):
                para.append(t)
    flush()
    return secs


def readme_digest(md):
    """README 에서 소개 문단·기능 목록·활용 목록과 AI 근거용 발췌를 뽑는다(없으면 빈 값)."""
    if not md:
        return {'intro':'', 'features':[], 'use_cases':[], 'excerpt':''}
    secs = readme_sections(md)
    intro = next((p for h,_,p in secs if len(p) >= 40 and not SKIP_HEAD.search(h.lower())), '')[:400]
    pick = lambda rx: next((b for h,b,_ in secs if b and rx.search(h.lower()) and not SKIP_HEAD.search(h.lower())), [])
    features = pick(FEATURE_HEAD)
    if not features:   # 제목 없이 소개 바로 아래 목록(예: 지원 형식 나열)
        features = next((b for h,b,_ in secs if len(b) >= 3 and not SKIP_HEAD.search(h.lower())), [])
    use_cases = [u for u in pick(USE_HEAD) if u not in features]
    body = []
    for h,b,p in secs:
        if SKIP_HEAD.search(h.lower()): continue
        body.append((('## '+h+'\n') if h else '') + (p+'\n' if p else '') + ''.join('- '+x+'\n' for x in b[:8]))
    return {'intro':intro, 'features':features[:5], 'use_cases':use_cases[:4], 'excerpt':'\n'.join(body)[:EXCERPT_CHARS]}


def previous_snapshot():
    d = DATA / 'snapshots'
    matches = sorted(p for p in d.glob('*.json') if p.stem < TODAY) if d.exists() else []
    if not matches: return {}, None
    last = matches[-1]
    obj = json.loads(last.read_text(encoding='utf-8'))
    return obj.get('stars', {}), obj.get('date',last.stem)


def clean_repo(item):
    return {'id':item['full_name'], 'name':item['name'], 'url':item['html_url'],
       'description':(item.get('description') or '').strip()[:450],
       'stars':item.get('stargazers_count',0),'forks':item.get('forks_count',0),
       'language':item.get('language') or '기타', 'topics':item.get('topics') or [],
       'created_at':item.get('created_at',''), 'updated_at':item.get('pushed_at',''),
       'homepage':item.get('homepage') or '', 'license':(item.get('license') or {}).get('spdx_id') or '미확인'}


def star_pool(candidates):
    """스타 기준으로 실을 후보 — KEEP_STARS 이상만, 모자라면 스타 순으로 MIN_PER 개까지 채움. 개수는 MIN_PER~LIMIT."""
    by_star = sorted(candidates.values(), key=lambda x:(x['stars'],x['id']), reverse=True)
    pool = [p for p in by_star if p['stars'] >= KEEP_STARS]
    if len(pool) < MIN_PER:
        pool = by_star[:MIN_PER]
    return {p['id']:p for p in pool}, min(LIMIT, len(pool))


def rank_repos(candidates, old_stars, limit=None):
    limit = limit or LIMIT
    pool = list(candidates.values())
    for p in pool:
        p['stars_change'] = max(0, p['stars']-old_stars[p['id']]) if p['id'] in old_stars else None
    popular = sorted(pool,key=lambda x:(x['stars'],x['id']),reverse=True)
    rising = sorted((p for p in pool if p['stars_change'] is not None),key=lambda x:(x['stars_change'],x['stars']),reverse=True)
    half = (limit + 1) // 2
    chosen = popular[:half]; present = {r['id'] for r in chosen}
    for p in rising:
        if len(chosen)>=limit: break
        if p['id'] not in present:
            chosen.append(p);present.add(p['id'])
    for p in popular:
        if len(chosen)>=limit: break
        if p['id'] not in present:
            chosen.append(p);present.add(p['id'])
    for n,p in enumerate(chosen,1):
        p['rank']=n
        p['selection']= '누적 인기' if n<=half else ('급상승' if p['stars_change'] is not None and len(rising)>0 else '누적 인기')
    return chosen


def repo_facts(repo):
    """확인 가능한 사실만 — 라이선스, 마지막 커밋, 처음 공개 연도."""
    lic = repo['license']
    f = ['라이선스 '+('표준 외(저장소에서 확인 필요)' if lic in ('NOASSERTION','OTHER') else lic)]
    try:
        pushed = dt.datetime.fromisoformat(repo['updated_at'].replace('Z','+00:00')).astimezone(KST).date()
        days = (dt.date.fromisoformat(TODAY) - pushed).days
        f.append('마지막 커밋 '+('오늘' if days <= 0 else f'{days}일 전')+f'({pushed.isoformat()})')
    except (ValueError, AttributeError):
        pass
    if repo.get('created_at'): f.append('공개 '+repo['created_at'][:4]+'년')
    return f


def readme_fallback(repo, category, dg):
    """AI 없이 README 원문 발췌로 채운다 — 저장소마다 실제 내용이 다르게 나온다."""
    repo['analysis'] = {
      'summary': repo['description'] or dg['intro'] or 'GitHub에 공개 설명이 없습니다.',
      'features': dg['features'], 'use_cases': dg['use_cases'], 'facts': repo_facts(repo),
      'cautions': ('README 원문에서 뽑은 내용(영문)임.' if dg['features'] or dg['use_cases']
                   else 'README에서 기능 목록을 찾지 못함 — 저장소에서 직접 확인 필요.'),
      'source': 'readme' if dg['features'] or dg['use_cases'] else 'metadata', 'category': category}


def _json_from(text):
    m = re.search(r'\{.*\}', text, flags=re.S)
    return json.loads(m.group(0)) if m else {}


def enrich_korean(selected):
    digests = {}
    for cat, repos in selected.items():
        for repo in repos:
            digests[repo['id']] = readme_digest(fetch_readme(repo['id']))
            readme_fallback(repo, cat, digests[repo['id']])
            time.sleep(0.3)
    key = os.getenv('ANTHROPIC_API_KEY','').strip()
    if not key:
        print('ANTHROPIC_API_KEY missing: README excerpts only'); return
    model = os.environ.get('ANTHROPIC_MODEL','claude-haiku-4-5-20251001')
    budget = MAX_AI
    for cat,repos in selected.items():
        todo = [p for p in repos if digests[p['id']]['excerpt'] or p['description']][:max(budget,0)]
        if not todo: continue
        budget -= len(todo)
        payload = [{'id':p['id'],'description':p['description'],'topics':p['topics'],'language':p['language'],
                    'readme_excerpt':digests[p['id']]['excerpt']} for p in todo]
        prompt = ('아래 GitHub 저장소들의 description 과 readme_excerpt(README 발췌)만 근거로 한국어 분석 JSON을 작성하세요.\n'
         '- summary: 무엇을 하는 도구인지 2문장.\n'
         '- features: README에 실제로 적힌 기능 3~4개. 저장소마다 구체적으로(제품명·지원 형식·연동 대상 등) 쓰고, 일반론 금지.\n'
         '- use_cases: 행정·사무 실무에 연결할 수 있는 활용 예 2~3개. README 근거가 약하면 1개만.\n'
         '- cautions: 도입 전 확인할 점 1문장(라이선스·외부 API 의존·유료 기능 등 발췌에 보이는 것).\n'
         '발췌에 없는 성능·수치는 쓰지 마세요. 출력은 JSON 하나만: {"projects":[{"id","summary","features","use_cases","cautions"}]}\n'
         '분야: '+cat+'\n'+json.dumps(payload,ensure_ascii=False))
        try:
            r = requests.post('https://api.anthropic.com/v1/messages', timeout=150,
             headers={'x-api-key':key,'anthropic-version':'2023-06-01','content-type':'application/json'},
             json={'model':model,'max_tokens':8000,'temperature':0.2,
                   'system':'README 근거만으로 간결하게 쓰는 한국어 기술 분석가입니다. 근거 없는 내용은 쓰지 않습니다.',
                   'messages':[{'role':'user','content':prompt}]})
            r.raise_for_status()
            out = _json_from(''.join(b.get('text','') for b in r.json().get('content',[]) if b.get('type')=='text'))
            byid={p['id']:p for p in out.get('projects',[]) if isinstance(p,dict) and p.get('id')}
            for repo in todo:
                p=byid.get(repo['id'])
                if not p or not isinstance(p.get('features'),list) or not isinstance(p.get('use_cases'),list): continue
                repo['analysis'].update({'summary':str(p.get('summary',''))[:1100],
                 'features':[str(s)[:250] for s in p['features'][:4]],
                 'use_cases':[str(s)[:280] for s in p['use_cases'][:4]],
                 'cautions':str(p.get('cautions',''))[:500], 'source':'ai'})
            print('AI enriched:',cat,len(byid),'/',len(todo))
        except (requests.RequestException, ValueError, KeyError,TypeError) as ex:
            print('AI enrichment failed, README excerpts retained:',cat,str(ex)[:250],file=sys.stderr)
        time.sleep(1)


def main():
    old, baseline=previous_snapshot()
    selected={}; all_found={}; errors=[]
    for cat,queries in SEARCHES.items():
        candidates={}
        for query in queries:
            try:
                results=api_search(query)
                for raw in results:
                    p=clean_repo(raw)
                    if p['stars'] < MIN_STARS: continue
                    candidates[p['id']]=p
                    all_found[p['id']]=p['stars']
                time.sleep(2.2)  # search API has stricter secondary limits
            except Exception as ex:
                errors.append(f'{cat}: {query}: {ex}')
        pool, limit = star_pool(candidates)
        selected[cat]=rank_repos(pool,old,limit)
        print(cat,len(selected[cat]))
    if not any(selected.values()):
        raise RuntimeError('No repositories collected. Previous archive left untouched. '+ '; '.join(errors))
    enrich_korean(selected)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA/'days').mkdir(exist_ok=True)
    (DATA/'snapshots').mkdir(exist_ok=True)
    day={'date':TODAY,'baseline_date':baseline,'limit_per_category':LIMIT,'created_after':CREATED_AFTER,
      'categories':[{'name':k,'repos':v} for k,v in selected.items()], 'errors':errors,
      'methodology':(f'{CREATED_AFTER} 이후 만들어진 저장소 중 ' if CREATED_AFTER else '')
                    + f'스타 {KEEP_STARS:,}개 이상만 분야별 최대 {LIMIT}개(모자라면 스타 순으로 최소 {MIN_PER}개). '
                    '그중 절반은 누적 스타 상위, 나머지는 직전 수집일 대비 스타 증가 상위(비교 자료 없으면 누적 인기 보충). '
                    '설명은 README 발췌를 근거로 Claude가 한국어로 요약(키가 없으면 README 원문 발췌).'}
    (DATA/'days'/f'{TODAY}.json').write_text(json.dumps(day,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Snapshot includes *all discovered candidates* so more candidates have delta next day.
    (DATA/'snapshots'/f'{TODAY}.json').write_text(json.dumps({'date':TODAY,'stars':all_found},ensure_ascii=False),encoding='utf-8')
    dates=sorted([p.stem for p in (DATA/'days').glob('????-??-??.json')],reverse=True)
    (DATA/'index.json').write_text(json.dumps({'dates':dates,'latest':dates[0] if dates else None,'categories':list(SEARCHES)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if errors: print('Partial search errors:',*errors,sep='\n',file=sys.stderr)
    print('Wrote',TODAY)

if __name__=='__main__': main()
