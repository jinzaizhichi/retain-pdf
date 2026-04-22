# Stage Execution Contract

这份文档只回答一个问题：

**`job_runner` 现在是怎么驱动各个 stage 的，哪些语义是稳定契约。**

相关文档：

- 总体架构边界：
  [`RUST_API_ARCHITECTURE.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_ARCHITECTURE.md)
- 当前运行主链：
  [`CURRENT_API_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/CURRENT_API_MAP.md)
- OCR provider 边界：
  [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)

## 1. 目标

`job_runner` 负责把 Rust 侧 job 状态机和 Python worker 执行链连接起来。

它不负责：

- HTTP 请求解析
- job view 组装
- OCR provider transport 细节定义

它负责：

- 选择执行链
- 写 stage spec
- 启动 Python worker
- 消费 stdout/stderr
- 更新 job runtime 状态
- 处理 timeout / cancel / failure

## 2. 当前 stage family

当前运行链分成 4 类：

1. `provider`
2. `normalize`
3. `translate`
4. `render`

对应正式 spec：

- `provider.stage.v1`
- `normalize.stage.v1`
- `translate.stage.v1`
- `render.stage.v1`

## 3. workflow 到 stage chain 的映射

### 3.1 `workflow=book`

链路：

```text
OCR child job
  -> provider transport
  -> normalize
parent job
  -> translate
  -> render
```

入口代码：

- [translation_flow.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/translation_flow.rs)

### 3.2 `workflow=translate`

链路：

```text
OCR child job
  -> provider transport
  -> normalize
parent job
  -> translate
```

不进入 render。

### 3.3 `workflow=render`

链路：

```text
reuse source.artifact_job_id
  -> render
```

入口代码：

- [render_flow.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/render_flow.rs)

### 3.4 `workflow=ocr`

链路：

```text
provider transport
  -> normalize
```

入口代码：

- [ocr_flow/mod.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/ocr_flow/mod.rs)

## 4. 运行时主模块

### 4.1 `lifecycle`

文件：

- [lifecycle.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/lifecycle.rs)

职责：

- 任务进入队列
- 获取执行槽位
- 根据 workflow 分发到：
  - `ocr_flow`
  - `translation_flow`
  - `render_flow`

### 4.2 `commands`

目录：

- [commands.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands.rs)
- [commands/stage_specs.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands/stage_specs.rs)
- [commands/entrypoints.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands/entrypoints.rs)

职责：

- 写 stage spec
- 选 Python 入口
- 生成最终命令

### 4.3 `worker_process`

文件：

- [worker_process.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/worker_process.rs)

职责：

- 启动 Python worker
- 注入 env
- 终止进程树

### 4.4 `process_runner`

文件：

- [process_runner.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/process_runner.rs)

职责：

- 执行命令
- 读取 stdout/stderr
- 超时处理
- 完成态归类
- AI failure diagnosis

### 4.5 `runtime_state`

文件：

- [runtime_state.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/runtime_state.rs)

职责：

- 维护 artifacts/runtime/failure 的运行态变更

## 5. 运行态状态语义

当前 job status：

- `queued`
- `running`
- `succeeded`
- `failed`
- `canceled`

当前常见 stage：

- `queued`
- `ocr_submitting`
- `ocr_upload`
- `mineru_processing`
- `normalizing`
- `translating`
- `rendering`
- `finished`
- `failed`
- `canceled`

规则：

- `status` 是最终态分类
- `stage` 是当前执行阶段
- `stage_detail` 是给人看的运行态说明

不要把业务判断塞进 `stage` 文本里。

## 6. stdout contract

Python worker 通过 stdout 回传运行线索。

当前重要标签在：

- [stdout_parser/mod.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/stdout_parser/mod.rs)

例如：

- `job root`
- `source pdf`
- `layout json`
- `normalized document json`
- `normalization report json`
- `translations dir`
- `output pdf`
- `summary`

规则：

- 新增 Rust 侧需要消费的 worker 产物时，优先走 stdout label contract
- 不要让 route/service 层直接猜 Python 输出目录

## 7. timeout / cancel contract

### 7.1 cancel

当前 cancel 分两层：

- cancel registry
- process termination

模块：

- [cancel_registry.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/cancel_registry.rs)
- [worker_process.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/worker_process.rs)

语义：

- job 被标记 cancel 后，runner 会尽量终止进程树
- `normalizing` 阶段允许有限继续，以便收尾

### 7.2 timeout

语义：

- timeout 秒数来自 `request_payload.runtime.timeout_seconds`
- 超时后 runner 负责 kill worker
- 然后把 job 标为 `failed`

当前 detail：

- `normalizing` -> `normalization timeout`
- 其他 provider transport 阶段 -> `provider timeout`

## 8. 成功与失败的判定

`process_runner` 当前把进程结果归成 4 类：

- `Canceled`
- `Succeeded`
- `SucceededWithShutdownNoise`
- `Failed`

也就是：

- 进程退出码不是唯一标准
- 如果 artifacts 已经完整写出，某些 Python shutdown noise 会被视为成功

这部分规则集中在：

- [process_runner.rs](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/process_runner.rs)

## 9. artifacts contract

`job_runner` 当前依赖的核心 artifacts 字段包括：

- `job_root`
- `source_pdf`
- `layout_json`
- `normalized_document_json`
- `normalization_report_json`
- `translations_dir`
- `output_pdf`
- `summary`
- `provider_raw_dir`
- `provider_zip`
- `provider_summary_json`

规则：

- stage 切换时，尽量通过 artifacts 传递下游输入
- 不要让下游重新猜路径

## 10. 团队协作红线

### 红线 1

新增 stage 字段时，先改：

- `commands/stage_specs.rs`

不要先改 route 参数。

### 红线 2

新增 worker 入口时，先改：

- `commands/entrypoints.rs`

不要在 `process_runner` 里拼临时命令。

### 红线 3

新增取消/超时语义时，优先改：

- `cancel_registry.rs`
- `worker_process.rs`
- `process_runner.rs`

不要在 `translation_flow` / `render_flow` 里各自补一份。

### 红线 4

新增 artifacts 路径语义时：

- worker 产出 -> stdout label contract
- Rust 消费 -> `stdout_parser` + `runtime_state`

不要在 route/service 层直接解析 Python 目录结构。

## 11. 推荐改动路径

### 场景 1：新增一个 Python stage

顺序：

1. `commands/stage_specs.rs`
2. `commands/entrypoints.rs`
3. 对应 flow 模块
4. `stdout_parser`
5. `runtime_state`

### 场景 2：调整 OCR child -> parent 交接字段

顺序：

1. `ocr_flow/mod.rs`
2. `translation_flow.rs`
3. `runtime_state.rs`

### 场景 3：调整 render-only 输入来源

顺序：

1. `render_flow.rs`
2. `storage_paths`
3. 必要时补 presentation summary

## 12. 一句话约束

`job_runner` 的稳定边界应该是：

- 上游给它 `JobRuntimeState`
- 它通过 spec 驱动 Python worker
- 它通过 stdout/artifacts 回收运行结果
- 它把 job 状态更新回 Rust 持久层

除此之外的职责，都不应该继续往这里堆。
