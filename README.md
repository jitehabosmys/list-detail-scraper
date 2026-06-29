# list-detail-scraper

爬取具有**列表页→详情页**结构的网站，提取结构化字段。

这是一个 [Agent Skill](https://agentskills.io) — 既是给 AI coding agent 的 SOP 指令，也是一个可直接运行的 Python 爬虫工具箱。

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
uv sync
cd scripts

# SSR HTML 示例 (SEC)
uv run python sec.py

# JSON API 示例 (THE Rankings)
uv run python the_rankings.py

# Sitemap 旁路示例 (FCA)
uv run python fca.py
```

脚本默认只爬前 2 页验证，确认无误后加 `--all` 参数全量运行：

```bash
uv run python sec.py --all
```

## 项目结构

```
list-detail-scraper/
├── SKILL.md              # Agent Skill 核心 SOP
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
└── README.md
```

## 作为 Agent Skill 使用

```bash
# 使用 npx skills 安装到任意兼容 agent
npx skills add <你的用户名>/list-detail-scraper --agent opencode
npx skills add <你的用户名>/list-detail-scraper --agent claude-code

# 或直接指定 skill
npx skills add <你的用户名>/list-detail-scraper --skill list-detail-scraper -a claude-code
```

## License

MIT
