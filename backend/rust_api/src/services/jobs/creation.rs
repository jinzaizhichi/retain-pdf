use crate::error::AppError;
use crate::models::{CreateJobInput, JobSnapshot, ResolvedJobSpec, UploadRecord};
use crate::services::job_factory::{
    build_and_start_job, require_upload_path, JobCommandKind, JobInit,
};
use crate::services::jobs::{
    validate_mineru_upload_limits, validate_ocr_provider_request, validate_provider_credentials,
};
use crate::AppState;

pub fn create_translation_job(
    state: &AppState,
    input: &CreateJobInput,
) -> Result<JobSnapshot, AppError> {
    if input.source.upload_id.trim().is_empty() {
        return Err(AppError::bad_request("upload_id is required"));
    }
    validate_provider_credentials(input)?;
    let upload = state.db.get_upload(&input.source.upload_id).map_err(|_| {
        AppError::not_found(format!("upload not found: {}", input.source.upload_id))
    })?;
    validate_mineru_upload_limits(input, &upload)?;
    let spec = ResolvedJobSpec::from_input(input.clone());
    let upload_path = require_upload_path(&upload)?;
    build_and_start_job(
        state,
        spec,
        JobCommandKind::TranslationFromUpload { upload_path },
        JobInit::default(),
    )
}

pub fn create_ocr_job(
    state: &AppState,
    input: &CreateJobInput,
    upload: Option<&UploadRecord>,
) -> Result<JobSnapshot, AppError> {
    validate_ocr_provider_request(input)?;
    if upload.is_none() && input.source.source_url.trim().is_empty() {
        return Err(AppError::bad_request(
            "either file or source_url is required",
        ));
    }

    let mut resolved = ResolvedJobSpec::from_input(input.clone());
    resolved.workflow = crate::models::WorkflowKind::Ocr;
    if let Some(upload) = upload {
        resolved.source.upload_id = upload.upload_id.clone();
        validate_mineru_upload_limits(input, upload)?;
    }
    let upload_path = upload.map(require_upload_path).transpose()?;
    build_and_start_job(
        state,
        resolved,
        JobCommandKind::Ocr { upload_path },
        JobInit::ocr_default(),
    )
}
