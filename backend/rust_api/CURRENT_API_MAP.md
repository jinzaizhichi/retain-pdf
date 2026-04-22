# Current API Map

这份文档只回答一个问题：

**现在这套 Rust API + Python worker，到底是怎么跑起来的。**

不讲历史，不展开兼容细节，优先看当前正式主链。

## 快速导航

- 文档总入口：
  [`README.md`](/home/wxyhgk/tmp/Code/backend/rust_api/README.md)
- 只看当前运行主链：
  [`CURRENT_API_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/CURRENT_API_MAP.md)
- 只看 Rust 模块边界：
  [`RUST_API_ARCHITECTURE.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_ARCHITECTURE.md)
- 只看 OCR provider 边界：
  [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)
- 只看 stage 运行时契约：
  [`STAGE_EXECUTION_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/STAGE_EXECUTION_CONTRACT.md)
- 只看外部 API 协议：
  [`API_SPEC.md`](/home/wxyhgk/tmp/Code/backend/rust_api/API_SPEC.md)

## 1. 当前系统分层

现在后端分两层：

### Rust 层

职责：

- 对外 HTTP API
- 鉴权
- job 创建 / 排队 / 状态机
- SQLite 持久化
- artifact / event 查询
- 启动 Python worker

代码主入口：

- [`src/routes/jobs/mod.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/routes/jobs/mod.rs)
- [`src/services/jobs/*`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs)
- [`src/job_runner/*`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner)

### Python 层

职责：

- OCR provider 调用
- raw OCR -> normalized `document.v1.json`
- 翻译
- 渲染
- PDF merge / post-process

代码主入口：

- [`backend/scripts/entrypoints/run_provider_case.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_provider_case.py)
- [`backend/scripts/entrypoints/run_provider_ocr.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_provider_ocr.py)
- [`backend/scripts/entrypoints/run_normalize_ocr.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_normalize_ocr.py)
- [`backend/scripts/entrypoints/run_translate_only.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_translate_only.py)
- [`backend/scripts/entrypoints/run_render_only.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_render_only.py)

## 2. 当前正式 workflow

现在真正对外可认为稳定的 workflow 只有这几个：

- `book`
  含义：provider-backed 全流程
  链路：OCR -> Normalize -> Translate -> Render

- `translate`
  含义：OCR -> Normalize -> Translate
  不做 render

- `render`
  含义：复用已有翻译产物，只做 render

- `ocr`
  含义：OCR-only / provider-only 子流程

注意：

- `book` 是现在 provider-backed full flow 的正式 API 标识
- **不是** `mineru`
- OCR provider 选择不靠 workflow，而靠 `ocr.provider`

## 3. 当前 provider 选择方式

当前 provider 分发口径：

- `workflow = book`
- `ocr.provider = mineru | paddle`

也就是：

- `workflow` 决定跑哪条大流程
- `ocr.provider` 决定 OCR 用哪个 provider

关键代码：

- Rust 写 spec：
  - [`src/job_runner/commands.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands.rs)
- Python 按 provider 分发：
  - [`backend/scripts/services/ocr_provider/provider_pipeline.py`](/home/wxyhgk/tmp/Code/backend/scripts/services/ocr_provider/provider_pipeline.py)

## 4. 当前正式协议：Stage Spec

Rust 和 Python worker 之间的正式协议已经不是长 CLI 参数，而是：

```bash
python -u <entrypoint> --spec <job_root>/specs/<stage>.spec.json
```

当前正式 stage：

- `provider.stage.v1`
- `normalize.stage.v1`
- `translate.stage.v1`
- `render.stage.v1`
- `book.stage.v1`

对应 Python loader：

- [`backend/scripts/foundation/shared/stage_specs.py`](/home/wxyhgk/tmp/Code/backend/scripts/foundation/shared/stage_specs.py)

## 5. Rust 到 Python 的真实执行链

以最重要的 `book` 为例：

### 第一步：前端 / 调用方发请求

典型入口：

- `POST /api/v1/jobs`

Rust 路由：

- [`src/routes/jobs/create.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/routes/jobs/create.rs)
- [`src/services/jobs/facade.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/facade.rs)

### 第二步：Rust 创建 job

负责：

- 校验请求
- 生成 job snapshot
- 持久化到 DB
- 进入队列

主要代码：

- [`src/services/jobs/creation.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/jobs/creation.rs)
- [`src/services/job_factory.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/services/job_factory.rs)

注意：

- route 层现在尽量只做 HTTP 适配
- `jobs` 相关用例已经统一先经过 `JobsFacade`
- `uploads` / `glossaries` 也分别经过 `upload_api` / `glossary_api`

### 第三步：job_runner 选择 worker

Rust 根据 workflow 组装命令：

- `book` -> `run_provider_case.py`
- `ocr` -> `run_provider_ocr.py`
- `translate` -> `run_translate_only.py`
- `render` -> `run_render_only.py`

主要代码：

- [`src/job_runner/commands.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands.rs)

### 第四步：Rust 写 stage spec

例如 `book` 会写：

- `DATA_ROOT/jobs/<job_id>/specs/provider.spec.json`

里面会包含：

- `job`
- `source`
- `ocr`
- `translation`
- `render`

其中 OCR provider 就在：

- `ocr.provider`

### 第五步：Rust 启动 Python worker

这里会把必要 env 注入进去：

- `RETAIN_TRANSLATION_API_KEY`
- `RETAIN_MINERU_API_TOKEN`
- `RETAIN_PADDLE_API_TOKEN`

主要代码：

- [`src/job_runner/process_runner.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/process_runner.rs)

### 第六步：Python worker 执行

`run_provider_case.py` -> `provider_pipeline.main()`

然后：

- 读取 `provider.spec.json`
- 看 `ocr.provider`
- `mineru` 走 MinerU 分支
- `paddle` 走 Paddle 分支
- 统一产出 normalized `document.v1.json`
- 再调用 `run_book_pipeline(...)`

主要代码：

- [`backend/scripts/entrypoints/run_provider_case.py`](/home/wxyhgk/tmp/Code/backend/scripts/entrypoints/run_provider_case.py)
- [`backend/scripts/services/ocr_provider/provider_pipeline.py`](/home/wxyhgk/tmp/Code/backend/scripts/services/ocr_provider/provider_pipeline.py)

## 6. 当前最重要的产物目录

每个 job 的标准目录：

- `DATA_ROOT/jobs/<job_id>/source`
- `DATA_ROOT/jobs/<job_id>/ocr`
- `DATA_ROOT/jobs/<job_id>/translated`
- `DATA_ROOT/jobs/<job_id>/rendered`
- `DATA_ROOT/jobs/<job_id>/artifacts`
- `DATA_ROOT/jobs/<job_id>/logs`
- `DATA_ROOT/jobs/<job_id>/specs`

最重要的几个文件：

- `specs/provider.spec.json`
- `ocr/result.json`
- `ocr/normalized/document.v1.json`
- `ocr/normalized/document.v1.report.json`
- `translated/translation-manifest.json`
- `artifacts/pipeline_summary.json`
- `rendered/*.pdf`

## 7. 当前最重要的数据契约

现在 translation / rendering 主链真正依赖的是 normalized document。

正式字段口径：

- `geometry`
- `content`
- `layout_role`
- `semantic_role`
- `structure_role`
- `policy`
- `provenance`

兼容字段还可能存在：

- `type`
- `sub_type`
- `bbox`
- `text`
- `lines`
- `segments`

但这些已经不是推荐主契约。

## 8. 现在的入口口径

当前入口只保留中性命名：

- `run_provider_case.py`
- `run_provider_ocr.py`
- `run_document_flow.py`

当前原则：

- 主入口认 `run_provider_case.py`
- 主协议认 `provider.stage.v1`
- 主 summary 文件认 `pipeline_summary.json`

## 9. 现在最该记住的三句话

1. `workflow=book` 才是 provider-backed 全流程，不再是 `mineru`
2. OCR provider 选择看 `ocr.provider`，不是看 workflow 名字
3. Rust 和 Python 的稳定边界是 `--spec <stage>.spec.json`

## 10. 排查时先看哪几个文件

如果你只想快速定位问题，优先按这个顺序看：

### 看 API 请求长什么样

- [`API_SPEC.md`](/home/wxyhgk/tmp/Code/backend/rust_api/API_SPEC.md)

### 看 Rust 到底起了哪个 Python 脚本

- [`src/job_runner/commands.rs`](/home/wxyhgk/tmp/Code/backend/rust_api/src/job_runner/commands.rs)

### 看 Python provider 总入口怎么分发

- [`backend/scripts/services/ocr_provider/provider_pipeline.py`](/home/wxyhgk/tmp/Code/backend/scripts/services/ocr_provider/provider_pipeline.py)

### 看 stage spec 长什么样

- [`backend/scripts/foundation/shared/stage_specs.py`](/home/wxyhgk/tmp/Code/backend/scripts/foundation/shared/stage_specs.py)

### 看最终主链结果

- `DATA_ROOT/jobs/<job_id>/artifacts/pipeline_summary.json`
