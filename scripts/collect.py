#!/usr/bin/env python3
"""Collect GitHub repos into date-stamped JSON, optionally enrich in Korean."""
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
KST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(KST).date().isoformat()
LIMIT = 10
SEARCHES = {
 'AI 에이전트': ['topic:ai-agents stars:>80', 'agentic framework in:name,description stars:>80', 'multi-agent in:name,description stars:>80'],
 'Python 코딩': ['topic:python stars:>300', 'python developer tools in:description stars:>80', 'python productivity in:description stars:>80'],
 'AI 코딩 도구': ['topic:ai-coding stars:>40', 'coding agent in:name,description stars:>50', 'ai code assistant in:description stars:>80'],
 '업무 자동화': ['topic:workflow-automation stars:>40', 'browser automation in:description stars:>100', 'automation workflow in:description stars:>100'],
 '데이터 분석': ['topic:data-analysis stars:>200', 'data analytics python in:description stars:>80', 'topic:data-visualization stars:>150'],
 'LLM·RAG': ['topic:retrieval-augmented-generation stars:>80', 'topic:rag stars:>100', 'topic:large-language-models stars:>200'],
 '문서·보고서 자동화': ['topic:document-automation stars:>10', 'pdf excel word automation in:description stars:>20', 'document generation in:description stars:>50'],
}
HEADERS = {'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'github-daily-open-source/1.0'}
if os.environ.get('GITHUB_TOKEN'): HEADERS['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']


def api_search(query, sort='stars', per_page=35):
    for attempt in range(4):
        try:
            r = requests.get('https://api.github.com/search/repositories', headers=HEADERS,
                params={'q':query+' archived:false fork:false', 'sort':sort, 'order':'desc', 'per_page':per_page}, timeout=35)
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


def rank_repos(candidates, old_stars):
    pool = list(candidates.values())
    for p in pool:
        p['stars_change'] = max(0, p['stars']-old_stars[p['id']]) if p['id'] in old_stars else None
    popular = sorted(pool,key=lambda x:(x['stars'],x['id']),reverse=True)
    rising = sorted((p for p in pool if p['stars_change'] is not None),key=lambda x:(x['stars_change'],x['stars']),reverse=True)
    chosen = popular[:5]; present = {r['id'] for r in chosen}
    for p in rising:
        if len(chosen)>=LIMIT: break
        if p['id'] not in present:
            chosen.append(p);present.add(p['id'])
    for p in popular:
        if len(chosen)>=LIMIT: break
        if p['id'] not in present:
            chosen.append(p);present.add(p['id'])
    for n,p in enumerate(chosen,1):
        p['rank']=n
        p['selection']= '누적 인기' if n<=5 else ('급상승' if p['stars_change'] is not None and len(rising)>0 else '누적 인기')
    return chosen


def local_fallback(repo,category):
    # Avoid pretending to have translated or read source code without an AI key.
    repo['analysis'] = {
      'summary': '원문 설명: '+(repo['description'] or 'GitHub에 공개 설명이 없습니다.'),
      'features': ['GitHub 저장소의 README 및 사용 예제를 확인하세요.', '라이선스와 최근 업데이트 상태를 검토하세요.'],
      'use_cases': ['기관 업무 적용 전 기능·보안·라이선스 적합성 검토가 필요합니다.'],
      'cautions': 'AI 분석이 비활성화되어 원문 메타데이터를 표시합니다.',
      'source': 'metadata', 'category': category}


def enrich_korean(selected):
    key = os.getenv('OPENAI_API_KEY','').strip()
    for cat, repos in selected.items():
        for repo in repos: local_fallback(repo,cat)
    if not key:
        print('OPENAI_API_KEY missing: using transparent metadata fallback'); return
    model = os.environ.get('OPENAI_MODEL','gpt-4.1-mini')
    for cat,repos in selected.items():
        payload = [{'id':p['id'],'description':p['description'],'topics':p['topics'],'language':p['language']} for p in repos]
        prompt = ('다음 공개 GitHub 메타데이터만 근거로 프로젝트별 한국어 분석 JSON을 작성하세요. '\
         'README를 읽었다고 주장하거나 미확인 성능을 단정하지 마세요. summary 2문장, features 배열 3개, '\
         'use_cases 배열 2~3개(행정·사무 실무 연결 가능한 경우), cautions 1문장. '\
         '확인 불가능한 사항은 확인 필요하다고 명시하세요. 최상위 객체 키는 projects, 각 원소에는 id, summary, features, use_cases, cautions. 분야: '+cat+'\n'+json.dumps(payload,ensure_ascii=False))
        try:
            r = requests.post('https://api.openai.com/v1/chat/completions', timeout=110,
             headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json={
              'model':model,'temperature':0.2,'response_format':{'type':'json_object'},
              'messages':[{'role':'system','content':'검증 가능한 정보만 간결하게 요약하는 한국어 기술 분석가입니다.'},{'role':'user','content':prompt}]})
            r.raise_for_status()
            out = json.loads(r.json()['choices'][0]['message']['content'])
            byid={p['id']:p for p in out.get('projects',[]) if isinstance(p,dict) and p.get('id')}
            for repo in repos:
                p=byid.get(repo['id'])
                if not p: continue
                if not isinstance(p.get('features'),list) or not isinstance(p.get('use_cases'),list):continue
                repo['analysis']={'summary':str(p.get('summary',''))[:1100],
                 'features':[str(s)[:250] for s in p['features'][:4]],
                 'use_cases':[str(s)[:280] for s in p['use_cases'][:4]],
                 'cautions':str(p.get('cautions',''))[:500], 'source':'ai','category':cat}
            print('AI enriched:',cat)
        except (requests.RequestException, ValueError, KeyError,TypeError) as ex:
            print('AI enrichment failed, fallback retained:',cat,str(ex)[:250],file=sys.stderr)
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
                    if p['stars'] < 10: continue
                    candidates[p['id']]=p
                    all_found[p['id']]=p['stars']
                time.sleep(2.2)  # search API has stricter secondary limits
            except Exception as ex:
                errors.append(f'{cat}: {query}: {ex}')
        selected[cat]=rank_repos(candidates,old)
        print(cat,len(selected[cat]))
    if not any(selected.values()):
        raise RuntimeError('No repositories collected. Previous archive left untouched. '+ '; '.join(errors))
    enrich_korean(selected)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA/'days').mkdir(exist_ok=True)
    (DATA/'snapshots').mkdir(exist_ok=True)
    day={'date':TODAY,'baseline_date':baseline,'limit_per_category':LIMIT,
      'categories':[{'name':k,'repos':v} for k,v in selected.items()], 'errors':errors,
      'methodology':'누적 스타 상위 5개 + 직전 수집일 대비 스타 증가 상위 5개(비교 자료 없을 경우 누적 인기 보충). 분야별 검색 후보군 중에서 선정.'}
    (DATA/'days'/f'{TODAY}.json').write_text(json.dumps(day,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (DATA/'snapshots').mkdir(exist_ok=True)
    # Snapshot includes *all discovered candidates* so more candidates have delta next day.
    (DATA/'snapshots'/f'{TODAY}.json').write_text(json.dumps({'date':TODAY,'stars':all_found},ensure_ascii=False),encoding='utf-8')
    dates=sorted([p.stem for p in (DATA/'days').glob('????-??-??.json')],reverse=True)
    (DATA/'index.json').write_text(json.dumps({'dates':dates,'latest':dates[0] if dates else None,'categories':list(SEARCHES)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if errors: print('Partial search errors:',*errors,sep='\n',file=sys.stderr)
    print('Wrote',TODAY)

if __name__=='__main__': main()
