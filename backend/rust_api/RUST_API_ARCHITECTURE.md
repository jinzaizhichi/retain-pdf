# Rust API Architecture

这份文档只回答一个问题：

**`rust_api` 现在的团队协作边界是什么，改哪里才是对的。**

不讲历史，不讲兼容迁移，默认只看当前主干代码。

相关文档：

- 文档总入口：
  [`README.md`](/home/wxyhgk/tmp/Code/backend/rust_api/README.md)
- 目录地图：
  [`RUST_API_DIRECTORY_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_DIRECTORY_MAP.md)
- 当前运行主链：
  [`CURRENT_API_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/CURRENT_API_MAP.md)
- OCR provider 边界：
  [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)
- stage 运行时契约：
  [`STAGE_EXECUTION_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/STAGE_EXECUTION_CONTRACT.md)
- Rust 侧 artifact boundary：
  [`doc/rust_api/10-Rust 侧 Artifact Boundary.md`](/home/wxyhgk/tmp/Code/doc/rust_api/10-Rust%20%E4%BE%A7%20Artifact%20Boundary.md)
- 外部 API 协议：
  [`API_SPEC.md`](/home/wxyhgk/tmp/Code/backend/rust_api/API_SPEC.md)

## 1. 总体分层

当前 `rust_api` 分成 6 层：

1. `app`
2. `routes`
3. `services` 中的 application 入口
4. `services` 中的内部实现
5. `job_runner`
6. `ocr_provider`

依赖方向必须保持单向：

```text
app -> routes -> application services -> internal services -> job_runner / ocr_provider
```

禁止反向依赖。

例如：

- `routes` 不应该知道 Python worker 命令怎么拼
- `job_runner` 不应该知道 HTTP Header 和 JSON envelope
- `ocr_provider` 不应该知道路由层返回结构

## 1.1 `AppState` 允许出现的位置

`AppState` 不是通用依赖注入容器，当前只允许停留在这些位置：

- `app/*`
  负责组装和持有全局资源
- `axum` route 入口函数
  也就是 `State(AppState)` 解包的那一层
- 少量 `from_state(...)` 装配口
  用来把 `AppState` 压缩成更窄的 deps 结构
- 测试辅助代码

禁止直接把 `AppState` 往下传到：

- `services` 的业务实现主链
- `job_runner` 的运行时主链
- `ocr_provider`
- presentation / view 组装层

如果某个模块需要资源，正确做法是：

1. 在边界层从 `AppState` 取出需要的字段
2. 组装成显式 deps struct
3. 业务模块只接收这个更窄的 deps

当前已经固定的公共模式：

- `routes/common.rs`
  负责 route 侧公共轻量 deps builder
- `routes/jobs/common.rs`
  只保留 jobs route 侧共享 deps / facade builder
- `routes/jobs/download_adapter.rs`
  负责 jobs 文件下载类 route adapter
- `routes/jobs/query_adapter.rs`
  负责 jobs JSON 查询 / 调试 / 控制类 route adapter
- `services/jobs/*::from_state(...)`
  负责 service application 层装配
- `job_runner/mod.rs::ProcessRuntimeDeps::from_state(...)`
  负责 runner 装配

其中 runner 侧对外只应该优先使用：

- `job_runner::build_process_runtime_deps(...)`

`ProcessRuntimeDeps::from_state(...)` 保留在 `job_runner` 内部使用，不应该再从 service/application 层直接调用。

禁止在每个 route 文件里重复手写一套局部 `route_deps(...)`。

## 1.2 内部契约 vs 对外契约

这条边界必须明确：

- `CreateJobInput` / `ResolvedJobSpec` / `JobSnapshot`
  是**内部运行契约**
- `JobDetailView` / `JobEventListView` / `TranslationDiagnosticsView`
  是**对外 API 契约**

内部契约允许持有真实 credential：

- `translation.api_key`
- `ocr.mineru_token`
- `ocr.paddle_token`

但这些字段只能存在于：

- 运行态内存
- SQLite job record
- worker env 注入
- stage spec 的 `credential_ref`

禁止直接进入：

- HTTP JSON response
- 对外 diagnostics / replay / debug payload
- events API payload

当前的安全适配层分两类：

1. `public_request_payload(...)`
   负责把内部 `ResolvedJobSpec` 投影成对外可返回的 request payload
2. `models/redaction.rs`
   负责对任意字符串 / JSON payload 做统一脱敏

团队协作规则：

- 如果新增一个对外 view，先决定它消费的是内部契约还是对外契约
- 任何从内部对象直接序列化到 HTTP 的改动，都默认视为错误
- 新增 secret 字段时，必须同步更新 redaction 模块，而不是在路由里局部打补丁

## 1.3 架构门禁

这套边界不只靠文档约定，还靠硬性检查：

- 本地命令：
  `python3 backend/rust_api/scripts/check_architecture.py`
- CI workflow：
  `.github/workflows/rust-api-architecture.yml`

当前门禁最少覆盖：

- `AppState` 不允许回流到 `services/job_runner/ocr_provider` 主链
- `routes` 不允许直接依赖 `job_runner`
- `routes/jobs/*` 不允许重复定义局部 `route_deps(...)`
- artifact / download 边界层不允许开始理解 provider raw 内部字段
- published markdown artifact 不允许重新从 `provider_raw_dir/full.md` 或 `provider_raw_dir/images` 反推

如果后续要调整白名单，必须同步改脚本和这份文档，不能只改其中一个。

## 1.4 Artifact Boundary

Rust 侧和产物直接相关的边界固定为四层：

1. `provider raw`
2. `normalized`
3. `published artifact`
4. `download API`

依赖和职责必须保持单向：

```text
provider raw -> normalized -> published artifact -> download API
```

每层的最小定义：

- `provider raw`
  provider 原始结果快照，只用于保真、回溯、排错、normalize 输入
- `normalized`
  OCR 到翻译/渲染的统一文档契约
- `published artifact`
  Rust 对任务文件的 artifact key 注册、发现和导出层
- `download API`
  最外层 HTTP 下载暴露层

Rust 侧关键落点：

- [src/storage_paths.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/storage_paths.rs)
  负责 artifact key、路径规范、文件解析
- [src/services/artifacts.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/artifacts.rs)
  负责 artifact registry、bundle、资源路径
- [src/routes/jobs/download.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/routes/jobs/download.rs)
  负责下载类 HTTP adapter

边界规则：

- `storage_paths.rs` 和 `services/artifacts.rs`
  只处理文件、artifact key、稳定资源，不解释 provider raw 内部 JSON 结构
- `routes/jobs/download.rs`
  只暴露稳定下载入口，不承诺 provider 私有字段语义
- `normalized-document` / `normalization-report`
  属于 normalized 边界，不属于 provider raw
- `provider_result_json` / `provider_raw_dir`
  属于 provider raw 边界，只能作为显式 artifact 下载，不是统一文档接口
- published markdown materialize
  必须保留 provider 返回的图片相对路径语义；允许增加页作用域前缀，但不允许把内部路径模式固定改写成自定义目录规则

快速判定：

- 如果一个改动要求下载层理解 `layoutParsingResults`、`prunedResult` 之类的 provider 字段名，说明边界已经穿透了
- 如果一个改动只是新增 artifact key、调整资源路径、调整稳定下载入口，通常应该落在 published artifact 或 download API 层

## 1.4 Published Markdown Artifact Boundary

这一条是最近重点收紧的边界：

- `provider_result_json`
- `provider_raw_dir`

属于 provider raw。

- `ocr/normalized/document.v1.json`

属于 normalize 后的统一契约。

- `md/full.md`
- `md/images/`
- `markdown_bundle_zip`

属于已经发布出来的 job artifact。

规则：

1. `provider_raw_dir` 可以保留 provider 原始回包和调试材料。
2. `provider_raw_dir` 不能被当成 published markdown artifact 的回退来源。
3. `resolve_markdown_path()` / `resolve_markdown_images_dir()` 这类对外资源解析函数，只能解析 `job_root/md/*` 这类已发布路径。
4. 如果某个 provider 将来要暴露 Markdown，应该显式新增一个 publish/materialize 步骤，而不是让下载层或 storage path 层去猜 provider raw 布局。

补充约束：

- publish/materialize 可以做“防冲突包装”，例如多页任务下给图片路径增加 `page-N/`
- 但不能重写 provider 返回的内部相对路径结构
- 例如 Paddle 返回 `<img src="imgs/foo.jpg">` 时，发布后可以是 `page-6/imgs/foo.jpg`
- 不能变成我们自定义拍板的固定模式，比如 `assets/foo.jpg` 或其他仓库私有命名

这样做的原因很简单：

- provider raw 变化频繁
- published artifact 是外部稳定下载口径
- 两层一旦混在一起，`markdown_ready` 就会失真，下载接口也会和 provider 私有结构耦合

## 2. 模块职责

### 2.1 `app/`

文件：

- [src/app/mod.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/app/mod.rs)
- [src/app/state.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/app/state.rs)
- [src/app/router.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/app/router.rs)
- [src/app/server.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/app/server.rs)

职责：

- 组装 `AppState`
- 启动 HTTP server
- 挂载路由
- 启动时恢复遗留 running job

不该做的事：

- 不写业务校验
- 不拼 job view
- 不决定 worker workflow

### 2.2 `routes/`

目录：

- [src/routes](/home/wxyhgk/tmp/Code/backend/rust_api/src/routes)

职责：

- HTTP 请求解析
- Header / Query / Multipart 提取
- 把请求转给 service
- 返回统一 JSON / file response

不该做的事：

- 不直接访问 SQLite 细节
- 不自己读 artifacts 文件
- 不自己拼 Python 命令

当前 `jobs` 路由已经统一收口到：

- [src/services/jobs/facade.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade.rs)

也就是：

- `routes/jobs/*` 只调 `JobsFacade`
- `routes/common.rs`
  只保留统一 `ok_json(...)` 这种 HTTP envelope helper
- `routes/jobs/common.rs`
  只保留 jobs 路由共享 deps builder
- `routes/jobs/download_adapter.rs`
  只保留下载类 route adapter
- `routes/jobs/query_adapter.rs`
  只保留 JSON / debug / cancel 类 route adapter
- `routes/glossaries.rs`
  只调 `services/glossary_api.rs`
- `routes/uploads.rs`
  只调 `services/upload_api.rs`

快速判断：

- 要改 HTTP 入参/出参，先看 `routes/*`
- 要改用例编排，先看 application service
- 要改 provider / worker / stage 行为，不要先从 route 下手

### 2.3 `services/` 中的 application 入口

目录：

- [src/services](/home/wxyhgk/tmp/Code/backend/rust_api/src/services)

职责：

- 给 route 提供稳定调用入口
- 负责用例编排和返回对外 view
- 屏蔽 `db/config/data_root/storage` 等资源拼装细节

当前已经成型的 application 入口：

- [src/services/jobs/facade.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade.rs)
- [src/services/glossary_api.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/glossary_api.rs)
- [src/services/upload_api.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/upload_api.rs)

规则：

- route 优先只依赖这些入口
- 不要让 route 直接再去拼 `db + config + helper + artifact service`
- application service 内部如果继续长大，优先拆 facade 子模块或 deps 子结构，不要再回退成一个总入口文件加一个总 deps

### 2.4 `services/` 中的内部实现

当前关键分工：

- [src/services/job_factory.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/job_factory.rs)
  负责 job snapshot 组装和启动边界
- [src/services/jobs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs)
  负责 jobs 相关业务

其中 `services/jobs` 又拆成：

- `creation`
- `control`
- `query`
- `debug`
- `facade`
- `presentation`

#### `services/jobs/facade`

文件：

- [src/services/jobs/facade.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade.rs)
- [src/services/jobs/facade/command](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade/command)
- [src/services/jobs/facade/query](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade/query)

职责：

- 给路由层提供统一入口
- 屏蔽 `db/config/data_root` 等底层细节
- 按 use case 继续拆成更小的 facade 子模块，而不是把所有入口堆回一个文件
- 命令侧和查询侧依赖分离，避免一个总 deps 同时拖着 create/query/debug/download 一起膨胀

规则：

- 新增 job 路由能力，优先先加到 facade，再由 route 调用
- 需要创建 / 取消类资源，优先放进 `CommandJobsDeps`
- 需要查询 / 下载 / debug 类资源，优先放进 `QueryJobsDeps`

#### `services/jobs/creation`

目录：

- [src/services/jobs/creation](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/creation)

职责：

- `submit.rs`
  只负责“接收输入后创建并启动任务”
- `bundle.rs`
  只负责“同步跑完整链路并产出下载 bundle”
- `job_builders.rs`
  只负责把输入解析成 `JobSnapshot`
- `upload.rs`
  只负责 PDF 上传持久化和 upload record 读取
- `context.rs`
  只负责 creation 侧显式 deps

规则：

- 不要把“提交任务”和“同步打包”重新塞回一个文件
- 不要在 facade 或 route 里重新拼 upload 存储细节
- 新增 creation use case 时，优先先判断它属于 `submit`、`bundle`、`job_builders` 还是 `upload`

#### `services/jobs/presentation`

目录：

- [src/services/jobs/presentation](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/presentation)

职责：

- `views.rs`
  负责 API view 组装
- `summary_loaders.rs`
  负责从 manifest / report / summary 文件读取摘要信息
- `mod.rs`
  负责 presentation 对外边界

规则：

- 改 JSON 返回结构，优先改 `views.rs`
- 改从磁盘补充的摘要字段，优先改 `summary_loaders.rs`
- 不要把文件读取逻辑重新塞回 view 组装函数

### 2.5 `job_runner/`

目录：

- [src/job_runner](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner)

职责：

- job 运行时调度
- Python worker 启动
- stdout/stderr 解析
- 取消、超时、失败归因
- OCR child job / translate / render 的运行链路

当前拆分：

- `lifecycle`
  任务排队、取执行槽、按 workflow 分发
- `cancel_registry`
  取消请求注册表
- `execution_queue`
  并发槽位等待
- `commands`
  stage spec + worker 入口命令
- `worker_process`
  进程启动、环境注入、进程树终止
- `process_runner`
  stdout/stderr 消费、超时、进程完成态归类
- `runtime_state`
  运行态 snapshot 变更
- `translation_flow`
  translate / book 相关链路
- `render_flow`
  render-only 链路
- `ocr_flow`
  OCR provider 运行链路

#### `job_runner/commands`

目录：

- [src/job_runner/commands](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands)

职责：

- `stage_specs.rs`
  写 `provider/normalize/translate/render` 的 spec 文件
- `entrypoints.rs`
  选 Python 脚本入口，拼入口参数
- `command_builder.rs`
  只做命令行构建细节
- [src/job_runner/commands.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands.rs)
  只保留对外 `build_*` facade

规则：

- 改 spec 字段，改 `stage_specs.rs`
- 改 worker 入口脚本，改 `entrypoints.rs`
- 不要在 facade 层重新写 JSON

#### `job_runner/process_runner`

文件：

- [src/job_runner/process_runner.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/process_runner.rs)

职责：

- 执行已构建好的 worker 进程
- 消费 stdout/stderr
- 处理 timeout / cancel / shutdown noise
- 附加失败 AI 诊断

规则：

- 不在这里写新的命令构建逻辑
- 不在这里维护取消注册表
- 不在这里决定执行槽策略

### 2.5 `ocr_provider/`

目录：

- [src/ocr_provider](/home/wxyhgk/tmp/Code/backend/rust_api/src/ocr_provider)

职责：

- Provider transport 抽象
- MinerU / Paddle 的客户端、状态映射、错误归类

规则：

- 这里只处理 provider 通信和 provider 语义
- 不处理翻译、渲染、HTTP 返回结构

## 3. 当前主调用链

主链：

1. `POST /api/v1/jobs`
2. `routes/jobs/create.rs`
3. `services/jobs/facade.rs`
4. `services/jobs/creation.rs`
5. `services/job_factory.rs`
6. `job_runner/lifecycle.rs`
7. `job_runner/commands.rs`
8. `job_runner/process_runner.rs`
9. Python worker

也就是：

- route 只进 facade
- facade 只进 service
- service 只进 runner

## 4. 团队协作红线

下面这些是硬约束：

### 红线 1

`routes/*` 不直接读：

- `Db`
- `job_paths`
- manifest/report JSON 文件
- Python worker 命令细节

### 红线 2

`job_runner/*` 不依赖：

- `axum`
- `HeaderMap`
- HTTP response model

### 红线 3

`ocr_provider/*` 不做：

- job view 组装
- 翻译策略
- 渲染策略

### 红线 4

如果一个改动同时要碰：

- route
- service
- runner

先停一下，先问是不是边界放错了。

### 红线 5

新增文件读取摘要逻辑，优先放：

- `services/jobs/presentation/summary_loaders.rs`

不要散落到：

- route
- facade
- `views.rs`

## 5. 改动指南

### 场景 1：新增一个 jobs 查询接口

改动顺序：

1. `routes/jobs/*`
2. `services/jobs/facade.rs`
3. `services/jobs/query.rs` 或 `presentation/*`

不要直接从 route 跨过 facade 去摸底层。

### 场景 2：新增一个 worker stage spec 字段

改动顺序：

1. `job_runner/commands/stage_specs.rs`
2. Python `stage_specs` loader
3. 对应 worker 消费逻辑

不要在 route/service 层补临时参数。

### 场景 3：新增一个 provider

改动顺序：

1. `ocr_provider/<provider>/`
2. `job_runner/ocr_flow/*`
3. Python provider pipeline

不要把 provider 判断散落到 route 或 facade。

### 场景 4：调整 job detail 返回字段

改动顺序：

1. `services/jobs/presentation/views.rs`
2. 如果字段来自磁盘摘要，再改 `summary_loaders.rs`

## 6. 当前建议

如果后面继续重构，优先级建议是：

1. 给 `services/jobs` 增加更明确的 request/response DTO 边界
2. 给 `job_runner` 增加 stage execution contract 文档
3. 给 `ocr_provider` 定统一 trait / capability contract

但当前这一版已经足够支撑多人并行开发，前提是遵守上面的依赖方向和红线。

相关补充文档：

- [`STAGE_EXECUTION_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/STAGE_EXECUTION_CONTRACT.md)
- [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)
