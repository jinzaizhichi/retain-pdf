use std::path::{Path, PathBuf};

use crate::error::AppError;
use crate::models::JobSnapshot;

use super::pdf::linearized_pdf_or_original;
use super::{FileDownload, QueryJobsDeps};

pub(crate) fn document_download(
    deps: &QueryJobsDeps<'_>,
    job: &JobSnapshot,
    resolve_path: impl Fn(&JobSnapshot, &Path) -> Option<PathBuf>,
    not_ready_label: &str,
    content_type: &str,
) -> Result<FileDownload, AppError> {
    let path = resolve_path(job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("{not_ready_label}: {}", job.job_id)))?;
    let path = if content_type == "application/pdf" {
        linearized_pdf_or_original(deps, job, &path, "output")?
    } else {
        path
    };
    Ok(FileDownload::new(path, content_type, None))
}
