# GitHub Daily Open Source

GitHub 공개 저장소 중 **2026-01-01 이후 만들어진 것**을 **7개 분야 × 하루 5~10개**로 선별하고, 스타 수와 최근 증가량, (선택적) AI 한국어 분석을 제공하는 날짜별 정적 웹사이트입니다. 디자인은 [Daily Papers](https://gbdata365.github.io/daily_papers/)의 소개/날짜/검색/카테고리/카드형 구성을 참고해 독립적으로 작성했습니다.

## 제공 기능
- 7개 분야: AI 에이전트, Python 코딩, AI 코딩 도구, 업무 자동화, 데이터 분석, LLM·RAG, 문서·보고서 자동화
- 각 분야는 **스타 2,000개 이상만** 최대 10개 싣고, 모자라면 스타 순으로 최소 5개까지 채웁니다(`config.json`의 `keep_min_stars`·`per_category`·`min_per_category`). 그중 절반은 누적 스타 상위, 나머지는 전날 대비 증가 상위입니다. 기준 날짜는 `created_after`.
- 첫날에는 비교 데이터가 없으므로 급상승 선정이 없습니다. 다음 실행부터 수집한 **직전 스냅샷** 기준으로 증가량을 계산합니다. GitHub 전체에서 하루 동안 가장 많이 오른 저장소의 완전한 순위를 의미하지 않습니다.
- 키워드 검색, 날짜 선택, 카테고리/선정 방식 필터, 반응형 화면
- 저장소마다 **README를 받아** '기능'·'활용' 절의 실제 목록과 소개 문단을 뽑습니다(AI 없음).
- `ANTHROPIC_API_KEY`를 설정하면 그 **README 발췌를 근거로** Claude(Haiku 4.5)가 한국어 요약·기능·활용 사례·주의사항을 씁니다. 키가 없거나 호출이 실패하면 README 원문 발췌(영문)를 그대로 보여 줍니다.
- 카드마다 확인 정보(라이선스·마지막 커밋일·공개 연도)와 설명 출처(AI 요약 / README 원문 / 공개 정보)를 표시합니다.
- GitHub Actions 매일 KST 08:17 실행 / 커밋 / GitHub Pages 배포

## 1. 배포 방법

1. GitHub에서 새 **Public** 저장소를 만들고(현재 `gbdata365/gb-github-daily`) 숨김 폴더 `.github`까지 저장소 루트에 올립니다. 기본 브랜치는 `main`입니다.
2. 저장소 **Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 허용합니다. 조직 정책에 따라 변경이 제한될 수 있습니다.
3. 저장소 **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 지정합니다.
4. 선택사항: **Settings → Secrets and variables → Actions → New repository secret**에 `ANTHROPIC_API_KEY`를 등록합니다(또는 `gh secret set ANTHROPIC_API_KEY`). **비용이 발생할 수 있습니다**(하루 최대 70개, `config.json`의 `max_ai_summaries_per_run`). 등록하지 않아도 README 원문 발췌로 운영됩니다.
5. **Actions → Daily GitHub Open Source → Run workflow**를 한 번 실행합니다. 실행 성공 후 `data/days/YYYY-MM-DD.json`, `data/snapshots/YYYY-MM-DD.json`, `data/index.json`이 커밋됩니다.
6. 데이터 커밋이 발생하면 **Deploy GitHub Pages**가 실행됩니다. 또는 해당 워크플로에서 **Run workflow**를 클릭합니다.
7. 게시 주소: `https://gbdata365.github.io/gb-github-daily/`
8. 수집 워크플로는 데이터 커밋 뒤 Pages 배포를 직접 호출합니다(`GITHUB_TOKEN`으로 한 push는 다른 워크플로를 깨우지 않기 때문).

> 공개 리포지토리의 Actions 사용 조건, API 제한 및 Pages 정책은 계정/조직 상황에 따라 다릅니다. `GITHUB_TOKEN`은 Actions에서 기본 제공됩니다.

## 2. 로컬 실행

```bash
python -m pip install -r requirements.txt
# 선택: export GITHUB_TOKEN=...; export ANTHROPIC_API_KEY=...
python scripts/collect.py
```

로컬 웹서버에서는 `web/` 아래에 `data/`가 있어야 하므로 아래 방식으로 미리 배포 구조를 구성하세요.

```bash
mkdir -p _site
cp -R web/. _site/
cp -R data _site/data
python -m http.server 8000 --directory _site
```

Windows PowerShell: `Copy-Item web\* _site -Recurse -Force; Copy-Item data _site\data -Recurse -Force` 명령으로 복사할 수 있습니다.

## 3. 데이터와 랭킹

- `data/days/YYYY-MM-DD.json`: 선택된 분야별 프로젝트와 한국어 분석 보관
- `data/snapshots/YYYY-MM-DD.json`: 해당 날짜 검색에서 발견된 **모든 후보 저장소**의 스타 스냅샷
- `data/index.json`: 날짜 목록 및 분야
- 분야·검색어·분야별 개수·최소 스타·AI 요약 상한은 `config.json`에서 고칩니다(코드 수정 불필요).
- 중복 프로젝트는 같은 분야 검색 내에서 제거합니다. 분야 간 중복은 허용합니다.
- 스타 증가량은 **현재 스타 - 이전 수집일의 동일 저장소 스타**이며, 이전 후보에서 빠진 저장소의 변화는 알 수 없습니다.
- GitHub 검색 API는 일부 결과만 제공하므로 10개 미만으로 나오는 분야가 있을 수 있습니다. API 제한/검색 조건에 따라 결과가 달라질 수 있습니다.
- 검색 오류가 일부 있어도 수집된 데이터는 저장하고 오류를 해당 날짜 JSON의 `errors`에 남깁니다. 모든 분야 수집에 실패하면 기존 데이터를 건드리지 않고 실패합니다.
- 참고로 이 구현의 `sort=stars`는 누적 인기를 우선 수집하므로 **진정한 전체 GitHub 급상승 순위의 완전한 추적은 아닙니다.** 후보군 안에서 관찰한 증가량 순위입니다.

## 4. 보안·운영 참고

- API 키는 `Secrets`에만 저장하고 파일로 커밋하지 마세요.
- 프런트엔드에는 API 키가 노출되지 않습니다.
- 사용자 제공 코드 실행이나 외부 저장소 설치 기능은 없습니다.
- AI 요약은 기능의 실증 검증이 아니므로 적용 전 라이선스, 개인정보, 보안성 검토가 필요합니다.
- 정적 사이트는 `fetch()`를 사용하므로 HTML을 파일 더블클릭으로 열기보다는 웹서버/Pages를 사용하세요.

## 기술 스택
Python, requests, GitHub REST API, Anthropic Messages API(Claude Haiku 4.5, 선택), HTML/CSS/JavaScript, GitHub Actions, GitHub Pages.
