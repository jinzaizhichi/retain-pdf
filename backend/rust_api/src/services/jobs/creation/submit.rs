use crate::error::AppError;
use crate::models::{CreateJobInput, JobSnapshot};
use crate::services::job_factory::start_job_execution;

use super::context::CreationDeps;
use super::job_builders::{build_ocr_job_snapshot, build_translation_job_snapshot};
use super::upload::{store_pdf_upload, UploadedPdfInput};

pub(crate) fn create_translation_job(
    deps: &CreationDeps<'_>,
    input: &CreateJobInput,
) -> Result<JobSnapshot, AppError> {
    let job = build_translation_job_snapshot(deps, input)?;
    start_job_execution(&deps.launcher, job)
}

pub(crate) async fn create_ocr_job_from_upload(
    deps: &CreationDeps<'_>,
    input: &CreateJobInput,
    upload: Option<UploadedPdfInput>,
) -> Result<JobSnapshot, AppError> {
    let stored = match upload {
        Some(upload) => Some(
            store_pdf_upload(
                deps.db,
                &deps.config.uploads_dir,
                deps.config.upload_max_bytes,
                deps.config.upload_max_pages,
                upload,
            )
            .await?,
        ),
        None => None,
    };
    let job = build_ocr_job_snapshot(deps, input, stored.as_ref())?;
    start_job_execution(&deps.launcher, job)
}
