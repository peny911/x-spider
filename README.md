# X-Spider

本项目当前方案基准文档：

- [X-Spider 本地免费版方案](docs/x-spider-local-plan.md)

后续讨论、开发和实现边界默认以该文档为准。

## 当前实现状态

已实现本地媒体下载的基础能力：

- Playwright 持久化浏览器会话
- 手动登录入口
- 本地 doctor 自检命令
- 本地 Chrome 可执行文件启动模式
- 已启动 Chrome remote debugging 连接模式
- 作者主页抓取
- X 搜索页抓取
- 关键词、发布者、提及账号组合
- 分段滚动和可配置滚动间隔
- 图片高清候选下载，优先 `name=orig`
- 视频 best-effort 下载，优先捕获最高分辨率 mp4 候选
- SQLite 去重和任务记录
- 失败图片重试

## 安装

建议使用 Python 3.12。

```bash
# 创建项目本地虚拟环境，依赖会安装到 .venv 里
python -m venv .venv

# 激活虚拟环境；后续终端命令会优先使用 .venv 里的 Python 和工具
source .venv/bin/activate

# 以可编辑模式安装当前项目，同时安装 pyproject.toml 中声明的依赖
pip install -e .

# 安装 Playwright 需要控制的 Chromium 浏览器；如果只使用本机 Chrome 或 CDP 模式，这一步通常不是必须的
playwright install chromium
```

可选配置：

```bash
# 复制环境变量示例文件；需要自定义数据目录、无头模式等配置时再修改 .env
cp .env.example .env
```

说明：

- `source .venv/bin/activate` 只用于激活 Python 虚拟环境，仍然需要。
- 不需要执行 `source .env`。程序启动时会自动读取当前目录或上级目录里的 `.env`。
- 如果你之前手动执行过 `source .env`，shell 里可能残留旧的 `X_SPIDER_` 环境变量；现在程序会以 `.env` 文件中的当前值为准。
- 修改 `.env` 后，直接重新运行 `x-spider doctor` 或抓取命令即可。

## 浏览器模式

X-Spider 支持三种浏览器模式，按优先级选择：

1. `X_SPIDER_CDP_ENDPOINT`：连接已经通过 remote debugging 启动的 Chrome。
2. `X_SPIDER_BROWSER_EXECUTABLE_PATH`：使用指定路径的本地 Chrome 启动一个 X-Spider 专用窗口。
3. `X_SPIDER_BROWSER_CHANNEL=chrome`：使用 Playwright 的 Chrome channel。
4. 以上都为空：使用 Playwright 自带 Chromium。

推荐优先使用 CDP 模式，因为它允许你先手动启动并登录 Chrome，再让 X-Spider 连接这个已登录会话。

禁用某个模式时，把对应值留空即可。程序会把空值视为未配置，不会把空路径当作当前目录执行：

```env
X_SPIDER_CDP_ENDPOINT=
X_SPIDER_BROWSER_EXECUTABLE_PATH=
X_SPIDER_BROWSER_CHANNEL=
```

### 切换浏览器模式

#### 切到 Chrome remote debugging

先启动一个带调试端口的 Chrome：

```bash
# 启动一个带 remote debugging 的独立 Chrome profile
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.x-spider-chrome-cdp"
```

在这个 Chrome 里手动登录 X。然后修改 `.env`：

```env
# 使用已启动的 Chrome remote debugging
X_SPIDER_CDP_ENDPOINT=http://127.0.0.1:9222

# CDP 模式下这两项留空，避免混淆
X_SPIDER_BROWSER_EXECUTABLE_PATH=
X_SPIDER_BROWSER_CHANNEL=
```

检查：

```bash
# CDP endpoint 应显示 http://127.0.0.1:9222
x-spider doctor
```

#### 切回 Playwright 启动本机 Chrome

修改 `.env`：

```env
# 不连接 CDP Chrome
X_SPIDER_CDP_ENDPOINT=

# 使用本机 Chrome 可执行文件
X_SPIDER_BROWSER_EXECUTABLE_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome

# executable path 不可用时再使用 Chrome channel
X_SPIDER_BROWSER_CHANNEL=chrome
```

检查并登录：

```bash
# Browser executable 应显示本机 Chrome 路径
x-spider doctor

# 打开 X-Spider 专用 Chrome 窗口登录
x-spider login
```

#### 切回 Playwright 自带 Chromium

修改 `.env`：

```env
# 不连接 CDP Chrome
X_SPIDER_CDP_ENDPOINT=

# 不指定本机 Chrome
X_SPIDER_BROWSER_EXECUTABLE_PATH=

# 不使用 Chrome channel
X_SPIDER_BROWSER_CHANNEL=
```

检查并登录：

```bash
# Browser channel 应显示 playwright chromium
x-spider doctor

# 打开 Playwright 自带 Chromium 登录
x-spider login
```

### X 登录被临时限制

如果在 Playwright 自带 Chromium 中登录 X 时提示“我们已临时限制你的登录。请稍后重试。”，通常是 X 把这个新浏览器环境识别成高风险登录。此时不要反复重试，先等待限制解除。

可以改用本机安装的 Chrome 启动 Playwright。先确认 Mac 上已安装 Google Chrome，然后在 `.env` 中设置：

```env
# 优先使用这个本地 Chrome 可执行文件路径启动 Playwright；登录态仍保存在 .data/browser-profile/
X_SPIDER_BROWSER_EXECUTABLE_PATH=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome

# 如果没有配置 executable path，则使用本机 Chrome 渠道
X_SPIDER_BROWSER_CHANNEL=chrome

# 启用 Chromium sandbox，避免浏览器顶部出现 --no-sandbox 警告
X_SPIDER_CHROMIUM_SANDBOX=true
```

然后重新检查和登录：

```bash
# 检查当前配置；Browser executable 应显示本机 Chrome 路径
x-spider doctor

# 重新打开登录窗口
x-spider login
```

如果仍然提示临时限制，建议先用普通浏览器确认账号本身正常，再等待一段时间后重试；不要频繁清空 profile 或连续登录，这会更容易触发风控。

### 连接已启动的 Chrome remote debugging

如果希望先手动启动一个 Chrome，再让 X-Spider 连接它，可以使用 CDP 模式。这个模式的前提是：Chrome 必须带 `--remote-debugging-port` 参数启动，普通已经打开的 Chrome 不能直接连接。

建议使用独立 profile，不要直接暴露你日常主 Chrome profile。

```bash
# 关闭当前用于调试的 Chrome 实例后，启动一个带远程调试端口的独立 Chrome
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.x-spider-chrome-cdp"
```

在这个 Chrome 窗口里手动登录 X。登录成功后，设置 `.env`：

```env
# 连接上面启动的 Chrome
X_SPIDER_CDP_ENDPOINT=http://127.0.0.1:9222
```

然后检查：

```bash
# CDP endpoint 应显示 http://127.0.0.1:9222
x-spider doctor
```

之后可以直接运行抓取命令：

```bash
# 连接已登录的 CDP Chrome，新开标签页抓取作者主页图片
x-spider crawl-user @authorA --media images --max-scrolls 100
```

注意：只在本机使用 `127.0.0.1`，不要把 remote debugging 端口暴露到公网或局域网。

### 推荐 CDP 流程

1. 启动带 remote debugging 的 Chrome：

```bash
# 启动一个给 X-Spider 使用的独立 Chrome profile
open -na "Google Chrome" --args \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.x-spider-chrome-cdp"
```

2. 在这个 Chrome 里手动登录 X。

3. 配置 `.env`：

```env
# 让 X-Spider 连接已经启动的 Chrome
X_SPIDER_CDP_ENDPOINT=http://127.0.0.1:9222
```

4. 检查配置：

```bash
# 确认 CDP endpoint 已生效
x-spider doctor
```

5. 开始抓取：

```bash
# 连接已登录 Chrome，新开标签页抓取图片
x-spider crawl-user @authorA --media images --max-scrolls 100
```

## 使用

检查本地目录和数据库：

```bash
# 初始化并检查 .data、browser-profile、downloads 和 SQLite 数据库是否可用
x-spider doctor
```

首次登录：

```bash
# 打开持久化浏览器窗口；你需要在窗口里手动登录 X，登录后回到终端按 Enter
x-spider login
```

抓取作者主页图片：

```bash
# 抓取 @authorA 主页当前可滚动加载到的图片，最多滚动 100 轮
x-spider crawl-user @Miao_yoga --media images --max-scrolls 100
```

抓取作者主页视频：

```bash
# 抓取 @authorA 主页当前可滚动加载到的视频，最多滚动 100 轮
x-spider crawl-user @authorA --media videos --max-scrolls 100
```

同时抓取图片和视频：

```bash
# 抓取 @authorA 主页当前可滚动加载到的图片和视频
x-spider crawl-user @authorA --media all --max-scrolls 100
```

抓取作者范围内关键词搜索结果：

```bash
# 在 @authorA 的内容范围内搜索“苹果”，下载搜索结果中可见帖子的图片
# X search: from:authorA 苹果 filter:images
x-spider crawl-user @authorA --keyword 苹果 --media images --max-scrolls 100
```

抓取作者范围内正文提及指定账号的图片：

```bash
# 搜索 @authorA 发布、正文提及 @authorB 或 @authorC 的帖子，并下载图片
# X search: from:authorA (@authorB OR @authorC) filter:images
x-spider crawl-user @authorA --mentions @authorB,@authorC --media images --max-scrolls 100
```

默认情况下，`crawl-user` 带 `--keyword` 或 `--mentions` 时会走 X 搜索页，因为搜索页能直接表达 `from:作者 + 关键词/提及` 条件，漏抓概率更低。

搜索页默认使用 `Top` 标签页，不追加 `f=live`。`Top` 通常比 `Latest` 更容易返回结果，尤其是复杂表达式、较早发布的内容、低互动内容，或被 X 搜索设置过滤的内容。

如果要切到 `Latest`，显式指定：

```bash
# 使用 Latest 标签页搜索
# X search: from:authorA (@authorB OR @authorC) filter:images
# URL 会额外追加 f=live，打开 X 的 Latest 标签页
x-spider crawl-user @authorA --mentions @authorB,@authorC --media images --source search --search-tab latest
```

注意：`Latest` 不是“更全”的模式。它更偏实时流，X 可能只返回较新的、通过当前搜索过滤规则的内容；同一个表达式在 `Top` 有结果，在 `Latest` 显示 `No results` 是正常现象。遇到这种情况，建议先使用默认 `Top`，或放宽搜索条件后再试。

如果你希望始终打开作者主页滚动，再由工具在本地过滤正文提及，可以指定：

```bash
# 打开 @authorA 主页滚动，本地过滤正文中提及 @authorB 或 @authorC 的帖子
x-spider crawl-user @authorA --mentions @authorB,@authorC --media images --source homepage --max-scrolls 100
```

抓取作者范围内正文提及指定账号且包含关键词的图片：

```bash
# 搜索 @authorA 发布、正文提及 @authorB，且包含“苹果”的帖子，并下载图片
# X search: from:authorA @authorB 苹果 filter:images
x-spider crawl-user @authorA --mentions @authorB --keyword 苹果 --media images --max-scrolls 100
```

抓取正文提及账号且包含关键词的搜索结果：

```bash
# 搜索正文中提及 @authorA 或 @authorB，且包含“青春正好”的帖子，并下载图片
# X search: (@authorA OR @authorB) 青春正好 filter:images
x-spider crawl-search --mentions @authorA,@authorB --keyword 青春正好 --media images --max-scrolls 100
```

抓取搜索结果中的视频：

```bash
# 搜索正文中提及 @authorA 或 @authorB，且包含“青春正好”的帖子，并下载视频
# X search: (@authorA OR @authorB) 青春正好 filter:videos
x-spider crawl-search --mentions @authorA,@authorB --keyword 青春正好 --media videos --max-scrolls 100
```

重试失败下载：

```bash
# 重试数据库中 download_status 为 failed 或 pending 的图片资源
x-spider retry-failed
```

重置作者后重新爬取：

```bash
# 删除 @authorA 的本地数据库记录，但不删除已下载文件
x-spider reset-author @authorA

# 跳过确认，适合明确知道要重置时使用
x-spider reset-author @authorA --yes

# 重置后重新爬取，资源会重新入库并重新下载
x-spider crawl-user @authorA --media images --max-scrolls 100
```

查看统计：

```bash
# 查看本地任务数、帖子数、资源数、成功下载数和失败数
x-spider stats
```

### 常用参数

- `--media images`：下载图片。
- `--media videos`：下载视频。视频会逐条打开 tweet 详情页捕获 `video.twimg.com` 的 mp4 候选，速度会慢于图片。
- `--media all`：同时尝试下载图片和视频；搜索页会使用 `filter:media`。
- `--keyword 苹果`：按关键词过滤搜索结果或页面内容。
- `--mentions @a,@b`：搜索正文中提及这些账号的帖子，多个账号用英文逗号分隔；`crawl-user` 中会组合成 `from:作者 (@a OR @b)`。
- `--publishers @a,@b`：限制发布者账号，多个账号用英文逗号分隔。
- `--source auto`：`crawl-user` 默认模式；带 `--keyword` 或 `--mentions` 时走搜索页，否则走作者主页。
- `--source homepage`：`crawl-user` 强制打开作者主页滚动，并在本地过滤关键词/提及。
- `--source search`：`crawl-user` 强制使用 X 搜索页。
- `--search-tab top`：搜索页默认标签页，不追加 `f=live`。
- `--search-tab latest`：搜索页使用 Latest 标签页，会追加 `f=live`。
- `--max-scrolls 100`：最多滚动 100 轮，数值越大，尝试加载的内容越多。
- 不传 `--max-scrolls` 或传 `--max-scrolls 0`：不限制滚动轮数。
- `--max-items 200`：最多处理 200 条帖子，适合小范围试跑。
- `--no-new-round-limit 20`：连续 20 轮没有发现新帖子后才停止；不传时使用 `.env` 中的 `X_SPIDER_NO_NEW_ROUND_LIMIT`。
- `--no-new-round-limit 0`：关闭连续无新增提前停止，只按 `--max-scrolls` 或 `--max-items` 停止。
- `reset-author @authorA --yes`：重置指定作者的本地 DB 记录，便于下一次重新爬取；不会删除 `.data/downloads` 下的文件。

### 浏览器关闭配置

默认情况下，Playwright 启动的浏览器会在命令结束后自动关闭：

```env
X_SPIDER_CLOSE_BROWSER_ON_FINISH=true
```

如果希望爬取结束后浏览器窗口保留，用于检查当前页面状态，可以改成：

```env
X_SPIDER_CLOSE_BROWSER_ON_FINISH=false
```

说明：

- 这个配置主要影响 Playwright 启动的浏览器。
- Playwright 模式下，`false` 表示爬取结束后命令会暂停并提示你按 Enter；在你按 Enter 之前，浏览器窗口会保留。
- Playwright 管理的浏览器依赖当前 Python 进程。按 Enter 结束命令后，浏览器窗口仍会关闭。
- CDP 模式连接的是你手动启动的 Chrome，X-Spider 不会主动关闭这个外部 Chrome。
- 如果希望命令退出后 Chrome 仍继续存在，请使用 `X_SPIDER_CDP_ENDPOINT=http://127.0.0.1:9222` 连接已启动的 Chrome remote debugging。

不传 `--max-scrolls` 时不会限制滚动轮数，但任务仍可能提前结束。原因是工具会在连续多轮滚动没有发现新帖子时停止，默认阈值是：

```env
X_SPIDER_NO_NEW_ROUND_LIMIT=8
```

如果页面加载较慢、账号内容很多但滚动触发不稳定，可以临时调大：

```bash
# 连续 20 轮无新内容才停止
x-spider crawl-user @Miao_yoga --media images --no-new-round-limit 20
```

如果你确认后面还有内容，但工具仍然太早停止，可以先关闭连续无新增停止：

```bash
# 不限制滚动轮数，也不按连续无新增停止；需要手动 Ctrl+C 或用 --max-items 停止
x-spider crawl-user @Miao_yoga --media images --max-scrolls 0 --no-new-round-limit 0

# 或者只按最大滚动轮数停止
x-spider crawl-user @Miao_yoga --media images --max-scrolls 200 --no-new-round-limit 0
```

结果表里的 `Stop reason` 会显示本次停止原因。

抓取过程中控制台会持续输出每轮信息，例如：

```text
[crawl] round=3 visible=5 new_visible=2 new_tweets=0 new_records=1 matched=2 media=4 downloaded=1 skipped=3 failed=0 total_seen=18 no_new_rounds=0 snapshots=3 scroll_y=4200 scroll_distance=1180
```

其中：

- `visible`：当前页面可见区域识别到的 tweet 数。
- `new_visible`：本轮首次看到的 tweet 数，仅用于观察页面是否还在出现本次运行未见过的内容。
- `new_tweets`：本轮新增 tweet 数；`no_new_rounds` 现在基于这个字段累计。
- `new_records`：本轮新增的本地记录数，包括新 scope 关联和新媒体资源；用于观察增量入库情况，不影响 `no_new_rounds`。
- `matched`：通过关键词/提及/作者条件的 tweet 数。
- `media`：本轮处理到的图片或视频资源数。
- `downloaded` / `skipped` / `failed`：本轮下载结果。
- `snapshots`：本轮实际提取了几次页面快照。每轮会先提取当前页面，再在每个小段滚动后继续提取。
- `scroll_y`：本轮结束时页面的垂直滚动位置。若多轮不变，通常表示页面没有继续向下加载。
- `scroll_distance`：本轮累计发出的滚动距离，单位 px。

### 视频下载说明

视频下载是 best-effort：

- 工具会打开每条含视频 tweet 的详情页，监听 `video.twimg.com` 网络请求。
- 如果捕获到多个 mp4 候选，会优先选择 URL 中分辨率最高的版本；分辨率相同时再参考 `Content-Length`。
- 如果捕获到 HLS/m3u8，会选择最高分辨率 variant，并把 init segment 和视频分片拼接保存。
- 这里的“最高”指 X 页面实际提供的最高候选版本，不等同于原始上传文件。
- HLS 拼接不使用 ffmpeg mux 音频；如果 X 把音频和视频拆成独立流，当前可能只能保存视频轨。

可以在 `.env` 中调整每条视频详情页的捕获时间：

```env
# 每条视频详情页捕获 video.twimg.com 网络请求的时间，单位秒
X_SPIDER_VIDEO_CAPTURE_SECONDS=8
```

如果视频经常失败，可以把它调大，例如 `12` 或 `15`；代价是视频抓取会更慢。

抓取视频时，控制台会输出 `[video]` 日志，例如：

```text
[video] start tweet_id=123 url=https://x.com/author/status/123
[video] open_detail capture_seconds=8.0 url=https://x.com/author/status/123
[video] capture_done total=3 mp4=2 hls=1
[video] hls_variant quality=1280x720 bandwidth=2176000 url=https://video.twimg.com/...
[video] hls_select quality=1280x720 segments=42 url=https://video.twimg.com/...
[video] hls_downloaded quality=1280x720 segments=42 bytes=12345678 url=https://video.twimg.com/...
[video] saved tweet_id=123 quality=1280x720 bytes=12345678 path=.data/downloads/...
```

常见判断：

- `media=0`：列表页没有识别到视频资源，可能当前可见帖子没有视频，也可能页面结构没有被识别到。
- `capture_done mp4=0 hls=0`：详情页打开了，但没有捕获到 `video.twimg.com` 请求；可以调大 `X_SPIDER_VIDEO_CAPTURE_SECONDS` 或确认视频是否能在浏览器中正常播放。
- `capture_done mp4>0` 但候选只有几百字节：这是 X 的 fMP4 初始化片段，不是完整视频；工具会跳过这种过小的直接 mp4。
- `capture_done hls>0`：工具会尝试解析 HLS，选择最高分辨率 variant 并拼接分片。
- `failed ... no downloadable mp4 video URL found`：没有捕获到可直接下载的 mp4。

### 滚动配置

抓取时每一轮不再一次性大幅滚动，而是按较小步长分段滚动。工具会先提取当前页面快照，然后每滚动一小段就再次提取，降低 X 虚拟列表卸载中间帖子导致漏爬的概率。

可在 `.env` 中调整：

```env
# 每小段滚动的最小距离，单位 px
X_SPIDER_SCROLL_STEP_MIN_PX=400

# 每小段滚动的最大距离，单位 px
X_SPIDER_SCROLL_STEP_MAX_PX=800

# 每小段滚动后的最短等待时间，单位秒
X_SPIDER_SCROLL_PAUSE_MIN_SECONDS=1

# 每小段滚动后的最长等待时间，单位秒
X_SPIDER_SCROLL_PAUSE_MAX_SECONDS=2

# 每一轮执行几小段滚动；每个小段滚动后都会再次提取页面快照
X_SPIDER_SCROLL_STEPS_PER_ROUND=2
```

默认效果是：每轮提取 3 次快照，分别是滚动前 1 次、两段小滚动后各 1 次；每小段 400-800px，每段后等待 1-2 秒。

如果怀疑漏爬，先使用更保守的滚动配置：

```env
X_SPIDER_SCROLL_STEP_MIN_PX=250
X_SPIDER_SCROLL_STEP_MAX_PX=450
X_SPIDER_SCROLL_PAUSE_MIN_SECONDS=1.5
X_SPIDER_SCROLL_PAUSE_MAX_SECONDS=3
X_SPIDER_SCROLL_STEPS_PER_ROUND=1
```

代价是速度变慢，但更容易让图片、视频标记和帖子正文加载完整。

## 测试

不依赖浏览器的单元测试可以直接运行：

```bash
# 运行纯单元测试，不启动浏览器，也不访问 X
PYTHONPATH=src python -m unittest discover -s tests
```

## 本地数据

默认数据目录：

```text
.data/
  browser-profile/
  downloads/
  db/x_spider.sqlite3
```

下载文件会按查询范围和媒体类型保存，例如：

```text
.data/downloads/users/Yoga_miao/images/
.data/downloads/users/Yoga_miao/IES_anh/images/
.data/downloads/users/Yoga_miao/WANIMAL912/images/
.data/downloads/searches/q_青春正好/images/
```

目录规则：

- 只抓某个作者时，保存到 `users/<作者>/images|videos/`。
- 在某个作者的作品中按 `--mentions` 搜索时，保存到 `users/<模特>/<摄影师>/images|videos/`。
- 不限定作者、只按 `--mentions` 搜索时，保存到 `users/<模特>/<发帖作者>/images|videos/`；如果当前条目拿不到作者，则退化到 `users/<模特>/`。
- 普通关键词搜索保存到 `searches/q_<关键词>/` 下。
