---
name: list-detail-scraper
description: >-
  爬取具有列表页→详情页结构的网站，提取用户指定的结构化字段。
  流程：inspect → analyze → generate → run → fix loop。
  支持多种前端渲染方式和反爬绕过。
---

## When to use

当需要从具有列表页→详情页结构的网站批量抓取数据时使用。每个网站结构不同，需要按以下流程针对性处理。

## Workflow

执行时先用 TodoWrite 列出 Steps。每个 Step 完成后，先简要输出该 Step 的结论，再更新 Todo 状态。

### Step 1: Inspect — 获取页面 HTML 并确定数据源类型

```
webfetch 获取渲染后 HTML
 ├─ 拿到 200 HTML
 │   ├─ 检查是否为 challenge/login/maintenance 页面
 │   │   ├─ 是 → 进入阻塞/异常页面处理：尝试 curl_cffi、sitemap/RSS、Playwright 或 API 逆向
 │   │   └─ 否 → 检查能否选出至少一条列表项或目标字段文本
 │   │       ├─ 能 → 数据源类型 = [SSR HTML]，进入 Step 2
 │   │       └─ 不能 → 进入下方空壳分支
 ├─ CSR 空壳（200 HTML 但无目标内容）
 │   ├─ 搜索 JS/HTML 找 API 端点（关键词见下方清单）
 │   │   ├─ 找到 → 数据源类型 = [JSON API]，进入 Step 2
 │   │   └─ 找不到 → 尝试 robots.txt → sitemap/RSS
 │   │       ├─ 有目标栏目 URL → 数据源类型 = [Sitemap]，进入 Step 2
 │   │       └─ 均无 → Playwright 无头浏览器渲染 → 回到"拿到 200 HTML"分支重新判断
 ├─ 403/CDN 阻塞
 │   ├─ curl_cffi impersonate 尝试绕过 → 若 200，回到上述分支重新判断
 │   ├─ robots.txt → sitemap/RSS 有目标栏目 → 数据源类型 = [Sitemap]，进入 Step 2
 │   ├─ Playwright 无头浏览器尝试渲染 → 若 200，回到"拿到 200 HTML"分支重新判断
 │   └─ 均失败 → 提示用户手动处理
 └─ 输出：数据源类型 + 原始内容 + 端点 URL（如有）
```

> sitemap/RSS 是通用补充检查，可在任何分支中作为旁路验证数据完整性。检查时机：403/CDN 阻塞、CSR 数据疑似不全、无法确认覆盖范围时。
>
> API 搜索关键词参考：api、endpoint、fetch(、axios、XMLHttpRequest、graphql、_api、__NEXT_DATA__、__NUXT__、window.__INITIAL_STATE__、drupalSettings、pageSize、limit、offset、cursor、skiptoken、loadMore、ajax

### Step 2: Analyze — 分析数据源

根据 Step 1 确定的数据源类型，进入对应分支。

#### 分支 A: SSR HTML（含 Rendered HTML）

- **列表容器选择器** — 每条列表项的父级元素
- **字段选择器** — 各字段的 CSS 选择器及详情页链接
- **分页机制**：URL 参数翻页 / AJAX Load More（需搜索 XHR 端点）
- **详情页** — 是否需要进入详情页？选择器是什么？
- **`__NEXT_DATA__` 检查** — 如 SSR 页面含此标签，检查其中是否嵌入全量数据或暴露 API URL；如是，可改用 [JSON API] 方式处理

#### 分支 B: JSON API

- **API 参数分析** — 请求方式、参数格式
- **优先尝试全量** — 测试 pageSize/rows/loadmorecount 上限，看是否能一次拉完
- **数据范围验证** — latest/recent 等端点名可能只返回部分数据，检查最早/最晚记录或总数。如数据疑似不全，可尝试 sitemap/RSS 验证覆盖范围
- **详情策略** — 响应已包含全部字段，还是仅提供 URL/id/refNo 需额外请求？若需额外请求，确认详情来源是 JSON API 还是 HTML 详情页

#### 分支 C: Sitemap

- **URL 提取模式** — 正则或 XPath 提取目标栏目 URL
- **详情页结构** — 分析 HTML 选择器
- **Sitemap 分页** — 如有多页 sitemap

#### 通用（所有分支）

- **详情获取路径** — 确认每条记录的详情来源：API 字段直接包含、需额外调详情 API、需抓详情 HTML 页、或无详情。若需额外详情请求，抽样请求 1-3 条，分析字段路径/HTML 选择器、字段完整性和失败状态
- **确认字段映射** — 用户字段→数据源中的路径/选择器，输出 key 统一用英文。标明哪些字段是 required（不可为空），哪些允许为空
- **排序要求** — 按哪个字段？升降序？排序前必须实现 sort_key：date 字段先解析为 datetime；numeric/rank 字段提取可排序数值（如 "=12" 取 12，"501-600" 取 501）；无法可靠解析时保留原始顺序
- **分页终止条件** — 写明停止依据：total/totalPages 达到后停止；next/cursor/__next 缺失时停止；offset/page 返回空列表时停止；无限滚动返回数量 < pageSize 或无新 URL 时停止。**全程维护 seen_urls/seen_ids，一页全部已见则停止，防止死循环**
- **筛选条件** — 年份/分类/地区等
- **调用 sub-agent 分析** — HTML 或 API 响应超过 100KB 时，用 `@explore`（或类似的 sub-agent 功能）分析并返回结构化结论，避免原始数据占满上下文。例如：大型 SSR 页面的结构解析、JS bundle 查找 API 端点等

#### 输出

输出为一组结构化配置（数据源类型、字段映射、分页/API参数、详情策略、排序要求）。

### Step 3: Generate — 生成爬虫脚本

根据 Step 2 的配置生成 Python 脚本。

#### 技术选型

- SSR HTML / Rendered HTML → `httpx` + `BeautifulSoup`
- JSON API → `httpx` 直接调用
- CDN 反爬（Cloudflare / Akamai）→ `curl_cffi`，模拟浏览器 TLS 指纹（JA3）
- 以上均无效 → Playwright 无头浏览器渲染
- `asyncio.sleep` 随机延迟 + `Semaphore` 控制并发（默认 `CONCURRENCY = 5`）
- 先测试 `httpx` 能否 200，确认需要再升级到 `curl_cffi`

#### 执行策略

- 429/503 指数退避重试；4xx 直接跳过
- 脚本默认只爬前 2 页用于验证，Step 4 确认后再改为全量
- `NEED_DETAIL` 开关节省详情页请求：列表页已有足够信息时设 `False`
- 每爬完一页增量保存到 `data/<site_name>.json`
- `tqdm` 显示进度条

#### 输出格式

- 输出字段：根据 Step 2 的字段映射动态生成，key 统一英文；`url` 和 `source` 固定输出
- 输出 schema：`[{"<字段1英文名>": str, "<字段2英文名>": str, ..., "url": str, "source": str}]`
- 输出文件路径：`data/<site_name>.json`
- **输出排序**：根据 Step 2 的排序要求，保存前做 `sorted()`
- 详情页是 PDF 或无正文时，对应字段留空
- **在脚本开头添加类型注释头**，格式如下：

  ```
  # ============================================================
  # [<数据源类型>] <网站名称> - <简短描述>
  # URL: <目标 URL>
  # 策略: <HTTP 客户端 + 反爬方案>
  # API: <API 端点 URL>（如适用）
  # 基类: <使用的基类>（如无则留空）
  # 分页: <分页参数说明>
  # 字段: <用户指定字段列表>
  # 详情: <详情页选择器或策略>
  # ============================================================
  ```

  `<数据源类型>` 使用 Step 1 确定的类型：`SSR HTML`、`JSON API`、`Sitemap`、`Rendered HTML`

优先检查当前项目 `scripts/` 下已有脚本，复用其中的 fetch/retry/save/parse 工具函数。仅当字段结构和保存/排序逻辑匹配时继承基础类（如 `scripts/base_ssr.py`）；分页参数必须从当前页面分析，禁止复制其他脚本的数值。

#### 注意事项

- **Drupal Views 分页陷阱**：超出有效范围后返回重复内容而非空页，循环时需做去重检测

### Step 4: Run — 先爬 2 页验证

首次运行前先确保环境和依赖就绪：

```
uv sync
```

执行命令（脚本默认只爬前 2 页）：

```
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && PYTHONPATH=scripts uv run python scripts/<name>.py
```

若直连返回 403/Cloudflare 挑战，尝试保留系统代理（取消 `unset`）重新运行，部分 CDN 对直连 TLS 指纹更敏感。

> `PYTHONPATH=scripts` 使 `from base_ssr import` 能正确找到同级模块。不要直接用 `python3`，要确保走项目虚拟环境。

### Step 4b: Verify — 检查质量 & 估算全量时间

爬完 2 页后：

1. **检查质量**：输出验证指标——实际条数/预期条数、每个 required 字段空值率、duplicate url/id 数、前 3 条样例、最早/最晚日期或排序字段范围
2. **验证 gate**：如果 required 字段空值率 > 5%，或某一页全部为已见 url/id，不进入全量，先修选择器或 API 字段
3. **检查注释头**：验证脚本开头的类型标记与分析结果一致（分类、分页、字段选择器是否准确）
4. **预估全量时间**：根据 2 页实际耗时 × (总页数 / 2)，包含详情页并发时间
5. 用 `question` 工具向用户交互式确认是否爬取全量（展示预览结果和估算全量时间作为选项）

### Step 4c: Confirm — 确认后全量运行

用户确认后，去掉页数限制重新运行：

```
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY && PYTHONPATH=scripts uv run python scripts/<name>.py
```

如果失败：分析错误信息，修复脚本，重新运行。

执行后检查：

- 输出字段是否完整（空值率）
- 数据量是否合理
- 排序要求（如有）是否满足

