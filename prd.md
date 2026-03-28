PRD: Global Finance News Terminal (Bloomberg Style)
1. 项目愿景
构建一个高密度的财经新闻聚合网站，通过 GitHub Actions 每小时自动更新，利用 AI 进行中英双语翻译，并以 Bloomberg Terminal 风格呈现。

2. 核心技术栈
框架: Astro (推荐，适合内容驱动型网站) 或 Next.js

部署: Cloudflare Pages

数据存储: Cloudflare D1 (Serverless SQL 数据库) 或 GitHub Repository (存为 news.json)

自动化: GitHub Actions (执行 Python 抓取脚本)

样式: Tailwind CSS

3. 功能需求详述
3.1 自动化数据抓取 (基于 news_fetcher.py)

RSS 优先: 仅保留 news_fetcher.py 中稳定的 RSS 源。

频率: GitHub Actions 每 60 分钟运行一次。

安全: API_KEY 必须通过 GitHub Secrets 传入环境变量，严禁硬编码。

翻译逻辑:

检测到英文标题/描述时，调用 LLM API 翻译。

存储格式必须包含 title_en (原文) 和 title_zh (译文)。

3.2 数据留存策略

后端数据库: 存储过去 7 天 的完整抓取记录。

前端展示: 仅查询并展示过去 72 小时 内的新闻。

清理机制: 每次执行脚本时，自动删除数据库中超过 7 天的旧数据。

3.3 前端展示与交互

排序: 严格按 timestamp 从近到远排序。

分页: 每页固定 15 条 新闻，提供“上一页 (Previous)”和“下一页 (Next)”按钮。

双语呈现: 每一条新闻条目中，英文内容在上，中文翻译在下（使用较小的字号或不同颜色区分）。

Bloomberg UI 规范:

配色: 纯黑背景 (#000000) 或 极暗灰色。

文字: 亮白色标题，亮蓝色 (#0000FF) 或 琥珀色 (#FFB100) 的链接/标签。

边框: 使用粗实线分隔区块，体现金融终端的工业感。

4. 数据库结构 (Schema)
若使用 Cloudflare D1 (SQL)，表结构建议如下：
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| id | TEXT (PK) | 唯一 ID |
| source | TEXT | 媒体来源名称 |
| title_en | TEXT | 英文原文标题 |
| title_zh | TEXT | 中文翻译标题 |
| link | TEXT | 原始链接 |
| timestamp | INTEGER | 发布时间戳 (ms) |
| category | TEXT | 财经/综合/快讯 |

5. Cursor 开发指令 (Step-by-Step)
第一步：环境配置与脚本重构

任务：修改 news_fetcher.py 以适配 GitHub Actions。

接入 os.environ.get("LLM_API_KEY")。

修改 fetch_source_news 函数，确保它只抓取 RSS 源。

增加翻译逻辑：调用 LLM 将抓取到的标题翻译成中文。

确保输出结果包含 title_en 和 title_zh 两个字段。

第二步：数据库与自动化工作流

任务：配置 GitHub Actions 与数据存储。

编写 .github/workflows/scrape.yml，设置 Cron 为 0 * * * *。

在 Action 中配置 Python 环境，运行脚本并将结果写入项目的 public/data/news.json (或连接 Cloudflare D1)。

第三步：前端页面开发 (Bloomberg UI)

任务：构建 Astro 页面。

创建新闻列表组件。

使用 Tailwind CSS 实现高对比度的黑色终端风格。

实现 72 小时数据过滤逻辑：filter(item => item.timestamp > Date.now() - 259200000)。

实现每页 15 条的分页逻辑。

第四步：部署

任务：发布至 Cloudflare Pages。

集成 GitHub 仓库。

配置构建指令。

6. 特别注意
禁止硬编码 API Key: 脚本运行必须依赖系统环境变量。

容错处理: 如果 LLM 翻译失败，应保留英文原文，不能导致整个抓取进程崩溃。

性能: 前端页面应尽量采用静态渲染 (SSG) 或 边缘渲染 (ISR)，以保证极致的加载速度。