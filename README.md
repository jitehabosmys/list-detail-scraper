# list-detail-scraper

通用列表页→详情页爬取 Agent Skill，基于 OpenCode 构建，兼容任意 Agent Skill 平台。

An [Agent Skill](https://agentskills.io) for scraping list-page → detail-page websites. Originally built for [OpenCode](https://opencode.ai), compatible with Claude Code, Cursor, Codex, and more.

## 支持的网站类型

| 类型 | 示例脚本 | 技术方案 |
|------|---------|---------|
| SSR HTML + CDN 反爬 | `sec.py` | `curl_cffi` TLS 指纹模拟 |
| JSON API | `sfc_news.py` | `httpx` 直接调用 API |
| JSON API + `__NEXT_DATA__` 详情 | `the_rankings.py` | `httpx` + SSR 详情页解析 |
| Sitemap 旁路绕过反爬 | `fca.py` | `httpx` + sitemap URL 发现 |
| ASP.NET WebForms Postback | `thailand_sec.py` | `curl_cffi` + ViewState postback |

## 快速开始

```bash
git clone git@github.com:jitehabosmys/list-detail-scraper.git
cd list-detail-scraper
uv sync

# SSR HTML 示例 (SEC)
uv run python scripts/sec.py

# JSON API 示例 (THE 世界大学排名)
uv run python scripts/the_rankings.py

# Sitemap 旁路示例 (FCA)
uv run python scripts/fca.py
```

## 作为 Agent Skill 安装

```bash
npx skills add jitehabosmys/list-detail-scraper -a opencode
```

## 项目结构

```
list-detail-scraper/
├── SKILL.md              # 核心 SOP 指令
├── scripts/
│   ├── base_ssr.py       # SSR 站通用基类 (限流/重试/并发/保存)
│   ├── sec.py            # [SSR HTML] SEC 美国证券交易委员会
│   ├── sfc_news.py       # [JSON API] 香港证监会新闻
│   ├── fca.py            # [Sitemap] 英国金融行为监管局
│   ├── thailand_sec.py   # [ASP.NET Postback] 泰国证监会
│   └── the_rankings.py   # [JSON API] THE 世界大学排名
├── examples/
│   └── sample_output.json
├── pyproject.toml
├── uv.lock
├── LICENSE
└── README.md
```

## License

MIT
