import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from collect import rank_repos

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

if __name__=='__main__':unittest.main()
