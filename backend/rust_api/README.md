# Rust API Docs

这份索引只回答一个问题：

**现在看 `rust_api` 文档，先看哪篇。**

## 建议阅读顺序

1. 当前系统到底怎么跑：
   [`CURRENT_API_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/CURRENT_API_MAP.md)
2. 先看目录，知道改哪里：
   [`RUST_API_DIRECTORY_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_DIRECTORY_MAP.md)
3. 团队协作边界和分层规则：
   [`RUST_API_ARCHITECTURE.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_ARCHITECTURE.md)
4. Rust 侧 artifact 四层边界：
   [`doc/rust_api/10-Rust 侧 Artifact Boundary.md`](/home/wxyhgk/tmp/Code/doc/rust_api/10-Rust%20%E4%BE%A7%20Artifact%20Boundary.md)
5. 对外 HTTP API 协议：
   [`API_SPEC.md`](/home/wxyhgk/tmp/Code/backend/rust_api/API_SPEC.md)
6. Rust 和 Python stage spec 契约：
   [`STAGE_EXECUTION_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/STAGE_EXECUTION_CONTRACT.md)
7. OCR provider 边界：
   [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)
8. Paddle OCR 异步 API 摘要：
   [`src/ocr_provider/paddle/API_SUMMARY.md`](/home/wxyhgk/tmp/Code/backend/rust_api/src/ocr_provider/paddle/API_SUMMARY.md)
8. Paddle Markdown / artifact 边界：
   [`../doc/paddle_ocr_api/06_job_artifact_boundary.md`](/home/wxyhgk/tmp/Code/doc/paddle_ocr_api/06_job_artifact_boundary.md)

## 每篇文档解决什么问题

- [`CURRENT_API_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/CURRENT_API_MAP.md)
  只看当前正式运行主链，重点回答“请求进来后，Rust 和 Python 到底怎么串起来”。
- [`RUST_API_DIRECTORY_MAP.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_DIRECTORY_MAP.md)
  只看当前目录职责，重点回答“应该先进哪个目录改代码”。
- [`RUST_API_ARCHITECTURE.md`](/home/wxyhgk/tmp/Code/backend/rust_api/RUST_API_ARCHITECTURE.md)
  只看当前团队协作边界，重点回答“改哪里才对，哪些层不能乱穿透”。
- [`doc/rust_api/10-Rust 侧 Artifact Boundary.md`](/home/wxyhgk/tmp/Code/doc/rust_api/10-Rust%20%E4%BE%A7%20Artifact%20Boundary.md)
  只看 Rust 侧 artifact boundary，重点回答“provider raw / normalized / published artifact / download API 四层各负责什么”。
- [`API_SPEC.md`](/home/wxyhgk/tmp/Code/backend/rust_api/API_SPEC.md)
  只看外部 HTTP 行为，重点回答“接口怎么调、返回什么、哪些字段是正式契约”。
- [`STAGE_EXECUTION_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/STAGE_EXECUTION_CONTRACT.md)
  只看 stage worker 的 spec 协议，重点回答“Rust 如何给 Python 传执行输入”。
- [`OCR_PROVIDER_CONTRACT.md`](/home/wxyhgk/tmp/Code/backend/rust_api/OCR_PROVIDER_CONTRACT.md)
  只看 provider adapter 边界，重点回答“MinerU / Paddle 在哪一层分发和收口”。
- [`src/ocr_provider/paddle/API_SUMMARY.md`](/home/wxyhgk/tmp/Code/backend/rust_api/src/ocr_provider/paddle/API_SUMMARY.md)
  只看 Paddle OCR 异步接口协议，重点回答“submit / poll / result download 到底怎么走”。
- [`../doc/paddle_ocr_api/06_job_artifact_boundary.md`](/home/wxyhgk/tmp/Code/doc/paddle_ocr_api/06_job_artifact_boundary.md)
  只看 Markdown 发布边界，重点回答“provider raw 为什么不能直接当 job markdown artifact”。

## 当前推荐认知路径

- 想快速理解系统：
  `README -> RUST_API_DIRECTORY_MAP -> CURRENT_API_MAP -> RUST_API_ARCHITECTURE`
- 想改后端代码：
  `RUST_API_DIRECTORY_MAP -> RUST_API_ARCHITECTURE -> 10-Rust 侧 Artifact Boundary -> CURRENT_API_MAP -> 对应源码`
- 想接前端或第三方：
  `API_SPEC -> CURRENT_API_MAP`

## 架构门禁

后端改动默认至少跑这几项：

- `python3 backend/rust_api/scripts/check_architecture.py`
- `cargo build --manifest-path backend/rust_api/Cargo.toml`
- `cargo test --manifest-path backend/rust_api/Cargo.toml --lib job_runner::process_runner::tests::execute_process_job_injects_provider_and_translation_envs`
- `cargo test --manifest-path backend/rust_api/Cargo.toml --lib routes::jobs::query::tests::job_detail_and_events_routes_redact_secrets`

第一条负责卡住最容易回退的架构问题：

- `AppState` 回流到 `services/job_runner/ocr_provider`
- `routes` 直接依赖 `job_runner`
- `routes/jobs/*` 重新手写局部 `route_deps(...)`
- artifact/download 边界层重新开始理解 provider raw 内部字段
- published markdown artifact 重新从 `provider_raw_dir/full.md|images` 反推
