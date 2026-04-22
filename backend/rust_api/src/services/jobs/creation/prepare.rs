use std::path::PathBuf;

use crate::error::AppError;
use crate::models::{CreateJobInput, ResolvedJobSpec, UploadRecord, WorkflowKind};
use crate::services::glossaries::resolve_task_glossary_request;
use crate::services::job_factory::require_upload_path;
use crate::services::jobs::{
    validate_mineru_upload_limits, validate_ocr_provider_request, validate_provider_credentials,
};

use super::context::CreationDeps;
use super::upload::load_upload_or_404;

pub(super) struct PreparedTranslationUpload {
    pub(super) spec: ResolvedJobSpec,
    pub(super) upload_path: PathBuf,
}

pub(super) fn prepare_full_pipeline_input(
    ctx: &CreationDeps<'_>,
    input: &CreateJobInput,
) -> Result<PreparedTranslationUpload, AppError> {
    let input = resolve_task_glossary_request(ctx.db, input)?;
    let upload = require_translation_upload(ctx, &input)?;
    Ok(PreparedTranslationUpload {
        spec: ResolvedJobSpec::from_input(input),
        upload_path: require_upload_path(&upload)?,
    })
}

pub(super) fn prepare_translate_only_input(
    ctx: &CreationDeps<'_>,
    input: &CreateJobInput,
) -> Result<ResolvedJobSpec, AppError> {
    let input = resolve_task_glossary_request(ctx.db, input)?;
    let _ = require_translation_upload(ctx, &input)?;
    let mut spec = ResolvedJobSpec::from_input(input);
    spec.workflow = WorkflowKind::Translate;
    Ok(spec)
}

pub(super) fn prepare_render_input(
    ctx: &CreationDeps<'_>,
    input: &CreateJobInput,
) -> Result<ResolvedJobSpec, AppError> {
    if input.source.artifact_job_id.trim().is_empty() {
        return Err(AppError::bad_request(
            "source.artifact_job_id is required for render workflow",
        ));
    }
    if ctx.db.get_job(&input.source.artifact_job_id).is_err() {
        return Err(AppError::not_found(format!(
            "artifact job not found: {}",
            input.source.artifact_job_id
        )));
    }
    let mut spec = ResolvedJobSpec::from_input(input.clone());
    spec.workflow = WorkflowKind::Render;
    Ok(spec)
}

pub(super) fn prepare_ocr_input(
    input: &CreateJobInput,
    upload: Option<&UploadRecord>,
) -> Result<(ResolvedJobSpec, Option<PathBuf>), AppError> {
    validate_ocr_provider_request(input)?;
    if upload.is_none() && input.source.source_url.trim().is_empty() {
        return Err(AppError::bad_request(
            "either file or source_url is required",
        ));
    }

    let mut resolved = ResolvedJobSpec::from_input(input.clone());
    resolved.workflow = WorkflowKind::Ocr;
    if let Some(upload) = upload {
        resolved.source.upload_id = upload.upload_id.clone();
        validate_mineru_upload_limits(input, upload)?;
    }
    let upload_path = upload.map(require_upload_path).transpose()?;
    Ok((resolved, upload_path))
}

fn require_translation_upload(
    ctx: &CreationDeps<'_>,
    input: &CreateJobInput,
) -> Result<UploadRecord, AppError> {
    if input.source.upload_id.trim().is_empty() {
        return Err(AppError::bad_request("upload_id is required"));
    }
    validate_provider_credentials(input)?;
    let upload = load_upload_or_404(ctx.db, &input.source.upload_id)?;
    validate_mineru_upload_limits(input, &upload)?;
    Ok(upload)
}
