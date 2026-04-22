use std::path::{Path, PathBuf};

use crate::models::{JobSnapshot, JobStatusKind};

mod control;
mod creation;
mod debug;
mod facade;
mod presentation;
mod query;
mod support;

pub(crate) use control::cancel_job;
pub use control::wait_for_terminal_job;
pub(crate) use creation::context::{
    BundleBuildDeps, CommandJobsDeps, ControlDeps, QueryJobsDeps, ReplayDeps,
};
pub(crate) use creation::{
    build_translation_bundle_artifact, create_ocr_job_from_upload, create_translation_job,
    store_pdf_upload, UploadedPdfInput,
};
pub(crate) use debug::{
    load_translation_debug_item_view, load_translation_debug_list_view,
    load_translation_diagnostics_view, replay_translation_item,
};
pub(crate) use facade::build_jobs_facade;
pub use facade::JobsFacade;
pub(crate) use presentation::{
    build_job_artifact_links_view, build_job_artifact_manifest_view, build_job_detail_view,
    build_job_events_view, build_job_list_view, load_ocr_job_or_404,
    load_ocr_job_with_supported_layout, load_supported_job,
};
pub(crate) use query::{ensure_supported_job_layout, load_job_or_404};
pub(crate) use support::{build_submission_view, ensure_cancelable, request_base_url};

pub use crate::services::job_validation::{
    validate_mineru_upload_limits, validate_ocr_provider_request, validate_provider_credentials,
};

pub fn readiness(
    job: &JobSnapshot,
    data_root: &Path,
    resolve_output_pdf: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
    resolve_markdown_path: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
) -> (bool, bool, bool) {
    let pdf_ready = resolve_output_pdf(job, data_root)
        .map(|p: PathBuf| p.exists())
        .unwrap_or(false);
    let markdown_ready = resolve_markdown_path(job, data_root)
        .map(|p: PathBuf| p.exists())
        .unwrap_or(false);
    let bundle_ready = matches!(job.status, JobStatusKind::Succeeded);
    (pdf_ready, markdown_ready, bundle_ready)
}
