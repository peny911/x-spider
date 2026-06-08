# X-Spider

本项目当前方案基准文档：

- [X-Spider 本地免费版方案](docs/x-spider-local-plan.md)

后续讨论、开发和实现边界默认以该文档为准。

## 当前实现状态

已实现第一阶段图片 MVP 的基础能力：

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
- SQLite 去重和任务记录
- 失败图片重试

视频下载还未实现，后续按方案文档第三阶段处理。

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

抓取作者范围内关键词搜索结果：

```bash
# 在 @authorA 的内容范围内搜索“苹果”，下载搜索结果中可见帖子的图片
x-spider crawl-user @authorA --keyword 苹果 --media images --max-scrolls 100
```

抓取正文提及账号且包含关键词的搜索结果：

```bash
# 搜索正文中提及 @authorA 或 @authorB，且包含“青春正好”的帖子，并下载图片
x-spider crawl-search --mentions @authorA,@authorB --keyword 青春正好 --media images --max-scrolls 100
```

重试失败下载：

```bash
# 重试数据库中 download_status 为 failed 或 pending 的图片资源
x-spider retry-failed
```

查看统计：

```bash
# 查看本地任务数、帖子数、资源数、成功下载数和失败数
x-spider stats
```

### 常用参数

- `--media images`：下载图片。当前 MVP 稳定支持该模式。
- `--media all`：当前会先下载图片，视频将在后续阶段实现。
- `--media videos`：暂未实现，会直接提示错误。
- `--keyword 苹果`：按关键词过滤搜索结果或页面内容。
- `--mentions @a,@b`：搜索正文中提及这些账号的帖子，多个账号用英文逗号分隔。
- `--publishers @a,@b`：限制发布者账号，多个账号用英文逗号分隔。
- `--max-scrolls 100`：最多滚动 100 轮，数值越大，尝试加载的内容越多。
- `--max-items 200`：最多处理 200 条帖子，适合小范围试跑。

### 滚动配置

抓取时每一轮不再一次性大幅滚动，而是按较小步长分段滚动，降低页面加载压力。

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

# 每一轮抓取后执行几小段滚动
X_SPIDER_SCROLL_STEPS_PER_ROUND=2
```

默认效果是：每轮抓取后滚动 2 小段，每小段 400-800px，每段后等待 1-2 秒。

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
.data/downloads/users/authorA/images/
.data/downloads/mentions/authorA_authorB/images/
.data/downloads/searches/q_青春正好/images/
```
