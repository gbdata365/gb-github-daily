import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import collect
from collect import rank_repos, readme_digest, star_pool

README = """# Tool
![badge](https://img.shields.io/x)

Tool turns office files into clean Markdown for search and LLM pipelines.

## Table of Contents
- [Install](#install)
- [Usage](#usage)

## Installation
```bash
# not a heading
pip install tool
```
- pip install tool

## Key Features
- **PDF and Word**: converts [documents](https://x.y) to Markdown
- Excel sheets become tables

## Use Cases
- Feed reports into a RAG index
"""

class TestRank(unittest.TestCase):
    def test_first_day(self):
        candidates={str(i):{'id':str(i),'stars':i*100} for i in range(1,13)}
        got=rank_repos(candidates,{})
        self.assertEqual(len(got),10)
        self.assertTrue(all(r['selection']=='누적 인기' for r in got))
        self.assertTrue(all(r['stars_change'] is None for r in got))
    def test_mix(self):
        candidates={str(i):{'id':str(i),'stars':i*100} for i in range(1,13)}
        old={str(i):i*100-(200 if i<6 else 1) for i in range(1,13)}
        got=rank_repos(candidates,old)
        self.assertEqual(len(got),10)
        self.assertEqual(len(set(p['id'] for p in got)),10)
        self.assertEqual(sum(p['selection']=='급상승' for p in got),5)

class TestStarPool(unittest.TestCase):
    def setUp(self):
        self.saved=(collect.KEEP_STARS,collect.MIN_PER,collect.LIMIT)
        collect.KEEP_STARS,collect.MIN_PER,collect.LIMIT=2000,5,10
    def tearDown(self):
        collect.KEEP_STARS,collect.MIN_PER,collect.LIMIT=self.saved
    def cands(self,stars):
        return {str(i):{'id':str(i),'stars':s} for i,s in enumerate(stars)}
    def test_many_strong(self):          # 2천 이상이 많으면 최대 10개
        pool,limit=star_pool(self.cands([5000+i for i in range(30)]))
        self.assertEqual(limit,10)
    def test_some_strong(self):          # 2천 이상이 6개면 6개
        pool,limit=star_pool(self.cands([9000,8000,7000,6000,3000,2000,1999,500]))
        self.assertEqual((limit,len(pool)),(6,6))
    def test_few_strong(self):           # 2천 이상이 4개뿐이면 스타 순으로 5개까지 채움
        pool,limit=star_pool(self.cands([9000,8000,3000,2500,1200,900,100]))
        self.assertEqual(limit,5)
        self.assertEqual(sorted(p['stars'] for p in pool.values()),[1200,2500,3000,8000,9000])
    def test_rank_uses_limit(self):
        pool,limit=star_pool(self.cands([9000,8000,7000,6000,3000,2000,1999]))
        self.assertEqual(len(rank_repos(pool,{},limit)),6)

class TestReadme(unittest.TestCase):
    def test_digest(self):
        d=readme_digest(README)
        self.assertTrue(d['intro'].startswith('Tool turns office files'))
        self.assertEqual(d['features'],['PDF and Word: converts documents to Markdown','Excel sheets become tables'])
        self.assertEqual(d['use_cases'],['Feed reports into a RAG index'])
        self.assertNotIn('pip install',d['excerpt'])      # 설치 절·코드 블록은 근거에서 뺌
        self.assertNotIn('Install',' '.join(d['features']))  # 링크뿐인 목차는 버림
    def test_empty(self):
        self.assertEqual(readme_digest('')['features'],[])

if __name__=='__main__':unittest.main()
