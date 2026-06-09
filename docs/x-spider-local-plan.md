# X-Spider 本地免费版方案

## 1. 目标

实现一个面向个人使用的本地工具，使用 Playwright 控制已登录的 X 浏览器会话，抓取作者主页、搜索结果页和提及场景中的图片/视频资源，并下载到本地。

本方案强调：

- 只做个人辅助下载
- 不依赖官方 API
- 不保证全量
- 不绕过登录、验证码和风控
- 重点保证本地去重、可恢复、可增量续跑

## 2. 适用场景

### 2.1 作者主页抓取

输入某个作者账号，例如 `@authorA`，抓取该账号主页当前可加载到的图片/视频。

### 2.2 关键词抓取

在作者主页或搜索页中，按关键词抓取命中的资源，例如：

- 作者 A 账号里搜索“苹果”
- 搜索正文里包含“青春正好”

### 2.3 提及抓取

支持正文中包含 `@作者A`、`@作者B` 的帖子资源抓取。

示例：

> @作者 A，@作者 B 青春正好，未来可期！——致贵州省2026届高考考生

只要正文命中提及条件，且帖子中有图片/视频资源，就应被采集。

## 3. 非目标

以下内容不在本方案承诺范围内：

- 全量历史回溯
- 稳定、持续、无遗漏的长期增量
- 无登录访问
- 绕过验证码、账号限制或访问限制
- 以官方 API 级别的完整性作为承诺

## 4. 技术选型

- 语言：Python 3.12
- 自动化：Playwright
- 存储：SQLite
- ORM：SQLAlchemy
- CLI：Typer
- 网络下载：httpx
- 日志与输出：rich

### 4.1 选择原因

- Playwright 支持持久化浏览器上下文，便于复用用户登录态。
- SQLite 足够支撑本地去重、任务状态和断点恢复。
- Typer 适合先做命令行版本，再平滑扩展为 Web UI。

## 5. 浏览器会话策略

第一次运行时启动持久化浏览器目录，让用户手动登录 X。

建议目录：

```text
.data/browser-profile/
```

后续运行复用该目录中的 cookies、localStorage 和会话状态。

### 5.1 持久化上下文

使用 Playwright 的 `launchPersistentContext(user_data_dir=...)`。

### 5.2 会话失效处理

如果页面出现以下情况，任务应暂停并标记为需要人工处理：

- 登录页
- 验证码页
- 访问受限页
- 页面结构异常

## 6. 运行模式

### 6.1 作者主页模式

抓取指定作者主页当前可见的帖子和资源。

### 6.2 搜索模式

通过 X 搜索页抓取关键词、提及或组合条件命中的帖子和资源。

### 6.3 组合模式

支持以下组合：

- 作者主页 + 关键词
- 提及 + 关键词
- 作者主页 + 提及
- 作者主页 + 关键词 + 提及

## 7. 查询语义

### 7.1 主要字段

- `publisher`：实际发帖账号
- `mentions`：正文中提及的账号
- `keyword`：关键词
- `media_type`：图片、视频、全部
- `scope_type`：users、mentions、searches
- `scope_name`：具体查询范围名称

### 7.2 例子

```text
from:authorA 苹果 filter:media
@authorA OR @authorB 青春正好 filter:media
```

### 7.3 说明

本方案允许用户输入展示名或备注名，但系统内部统一使用真实 handle。

## 8. 数据目录

默认存储在项目本地 `.data` 下。

推荐结构：

```text
.data/
  browser-profile/
  downloads/
    users/
      authorA/
        images/
        videos/
    mentions/
      authorA_authorB/
        images/
        videos/
    searches/
      q_青春正好/
        images/
        videos/
  db/
    x_spider.sqlite3
  logs/
```

### 8.1 目录原则

- 作者主页模式按作者名分目录
- 提及模式按提及集合分目录
- 关键词模式按关键词分目录
- 文件名中保留实际发布者和资源标识，方便人工查看

## 9. 文件命名规则

推荐格式：

```text
{tweet_date}_{tweet_id}_{publisher}_{media_id}_{quality}.{ext}
```

示例：

```text
20260608_1930000000000000000_authorA_abcd1234_orig.jpg
```

## 10. 高清图片策略

图片优先请求 `pbs.twimg.com/media/...` 对应的高清版本。

### 10.1 候选顺序

1. `name=orig`
2. `name=4096x4096`
3. `name=large`
4. `name=medium`
5. `name=small`
6. 原始 URL

### 10.2 原则

- 优先使用 `name=orig`
- 失败时自动降级
- 保存时根据响应头或 URL 参数确定扩展名

### 10.3 记录字段

建议保存：

- `source_url`
- `best_url`
- `quality`
- `sha256`
- `width`
- `height`

## 11. 视频策略

当前采用 best-effort 视频下载。

流程：

1. 在列表页识别包含视频播放器或视频缩略图的 tweet。
2. 下载时打开该 tweet 详情页。
3. 捕获 `video.twimg.com` 网络请求，收集 mp4 候选。
4. 优先选择 URL 中分辨率最高的 mp4；分辨率相同时参考 `Content-Length`。
5. 如果只捕获到 HLS/m3u8，当前记录为 failed，不阻塞其他资源。

可通过 `.env` 调整每条视频详情页的捕获时间：

```env
X_SPIDER_VIDEO_CAPTURE_SECONDS=8
```

## 12. 增量与去重

免费本地版不依赖 API 级 `since_id`，采用本地事实库方式做增量。

### 12.1 去重层级

1. `tweet_id` 去重
2. `media_identity` 去重
3. `sha256` 去重
4. `scope_key + tweet_id` 记录命中关系

### 12.2 增量原则

- 每个查询条件有独立 checkpoint
- 每次运行只处理新发现内容
- 中断后可继续
- 下载失败可以重试

## 13. SQLite 数据模型

### 13.1 `crawl_tasks`

- `id`
- `task_type`
- `url`
- `publishers`
- `mentions`
- `keyword`
- `media_type`
- `status`
- `last_seen_tweet_id`
- `last_scroll_position`
- `no_new_rounds`
- `created_at`
- `updated_at`

### 13.2 `tweets`

- `tweet_id` unique
- `author_handle`
- `text`
- `url`
- `published_at`
- `first_seen_at`
- `last_seen_at`
- `raw_json`

### 13.3 `media_assets`

- `id`
- `media_identity` unique
- `tweet_id`
- `media_type`
- `source_url`
- `best_url`
- `local_path`
- `sha256`
- `width`
- `height`
- `duration_ms`
- `download_status`
- `error`
- `created_at`
- `updated_at`

### 13.4 `crawl_scopes`

- `scope_key` unique
- `latest_seen_tweet_id`
- `latest_seen_at`
- `total_seen`
- `total_downloaded`
- `last_success_at`

## 14. 爬取流程

1. 读取任务配置。
2. 打开持久化浏览器上下文。
3. 进入作者主页或搜索页。
4. 等待 `article` 元素出现。
5. 提取当前页面可见帖子。
6. 为每个帖子提取：
   - `tweet_id`
   - 作者 handle
   - 正文
   - 发布时间
   - 图片 URL
   - 视频候选 URL
7. 按 `keyword`、`mentions`、`media_type` 判断是否命中。
8. 新资源写入 SQLite。
9. 下载文件到本地。
10. 页面向下滚动。
11. 连续若干轮没有新内容则停止。
12. 保存 checkpoint。

## 15. 停止条件

建议满足以下任一条件即停止：

- 连续 5 到 10 次滚动没有发现新帖子
- 达到 `--max-scrolls`
- 达到 `--max-items`
- 页面出现登录、验证码、受限或异常状态

## 16. CLI 建议

```text
x-spider login
x-spider crawl-user @authorA --media images --max-scrolls 100
x-spider crawl-search --mentions @authorA,@authorB --keyword 青春正好 --media images --max-scrolls 100
x-spider retry-failed
x-spider stats
```

## 17. 实施阶段

### 17.1 第一阶段：图片 MVP

- 持久登录
- 作者主页采集
- 搜索页采集
- 图片下载
- SQLite 去重
- 断点恢复

### 17.2 第二阶段：提及与组合查询

- `@作者A`、`@作者B` 提及抓取
- 提及 + 关键词组合
- 查询作用域 checkpoint

### 17.3 第三阶段：视频支持

- 监听网络请求
- 捕获视频资源
- 选择最佳码率
- 失败重试

### 17.4 第四阶段：管理界面

- 任务列表
- 下载状态
- 本地资源浏览
- 失败重试

## 18. 风险与约束

- X 页面结构可能变化
- 登录态可能失效
- 搜索页和资源页可能触发限制
- 视频链路比图片更不稳定
- 免费本地版不适合做全量承诺

## 19. 开发基准

后续讨论和开发均以本文档为准。若实现中需要调整边界，应先更新本文件，再继续编码。
