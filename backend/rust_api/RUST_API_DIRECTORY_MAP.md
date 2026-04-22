# Rust API Directory Map

这份文档只回答一个问题：

**现在要改 `rust_api`，应该先进哪个目录。**

## 最常见入口

- 改 HTTP 接口：
  [`src/routes`](/home/wxyhgk/tmp/Code/backend/rust_api/src/routes)
- 改 jobs 用例编排：
  [`src/services/jobs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs)
- 改 worker 运行链路：
  [`src/job_runner`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner)
- 改 OCR provider 分发和适配：
  [`src/ocr_provider`](/home/wxyhgk/tmp/Code/backend/rust_api/src/ocr_provider)

## 目录地图

### `src/app`

- 作用：
  应用启动、`AppState` 组装、router 挂载、服务启动。
- 进入条件：
  只有在改全局资源、启动逻辑、路由挂载时才进这里。

### `src/routes`

- 作用：
  HTTP 参数提取、请求转发、统一响应封装。
- 不该做的事：
  不直接碰 `job_runner`，不自己拼底层业务逻辑。

#### `src/routes/jobs`

- `common.rs`
  jobs route 共享 deps builder。
- `download_adapter.rs`
  文件下载类 route adapter。
- `query_adapter.rs`
  JSON 查询 / debug / cancel 类 route adapter。
- `create.rs` / `download.rs` / `query.rs` / `control.rs` / `translation_debug.rs`
  真正的 axum route 入口。

### `src/services`

- 作用：
  application service 入口和内部业务实现。

#### `src/services/jobs/facade`

- 作用：
  给 route 提供统一 jobs 入口。
- `command/*`
  创建、取消、同步 bundle 这类命令型能力。
- `query/*`
  列表、详情、下载、artifacts、translation debug 这类查询型能力。

#### `src/services/jobs/creation`

- `submit.rs`
  创建并启动任务。
- `bundle.rs`
  同步跑完整链路并产出 bundle。
- `prepare.rs`
  输入解析、存在性检查、前置校验。
- `job_builders.rs`
  把已准备好的输入构造成 `JobSnapshot`。
- `upload.rs`
  upload 持久化和 upload record 读取。
- `context.rs`
  creation 侧显式 deps。

#### `src/services/jobs/presentation`

- 作用：
  对外 view 组装、摘要读取、响应投影。
- 进入条件：
  改 API 返回结构、摘要字段、脱敏展示时进这里。

#### 其他 service 入口

- [`src/services/upload_api.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/upload_api.rs)
  上传接口入口。
- [`src/services/glossary_api.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/glossary_api.rs)
  术语表接口入口。
- [`src/services/job_factory.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/job_factory.rs)
  job snapshot/command 构造和启动边界。

### `src/job_runner`

- 作用：
  任务排队、worker 启动、stdout/stderr 消费、失败归因、取消、超时。
- 快速判断：
  改 stage 执行顺序、并发槽位、进程控制、运行态同步时进这里。

### `src/ocr_provider`

- 作用：
  OCR provider 分发、provider 特定协议转换、provider 输出收口。
- 快速判断：
  改 MinerU / Paddle 接入细节时进这里。

## 三条快速判断

- “这是 HTTP 行为变化吗？”
  先看 `src/routes`
- “这是 jobs 用例编排变化吗？”
  先看 `src/services/jobs/facade` 和 `src/services/jobs/creation`
- “这是 worker / Python 执行变化吗？”
  先看 `src/job_runner`
