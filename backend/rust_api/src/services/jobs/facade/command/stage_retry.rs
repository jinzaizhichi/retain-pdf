use serde_json::{json, Value};

use crate::error::AppError;
use crate::models::{
    build_job_actions, build_job_links_with_workflow, CreateJobInput, JobArtifacts, JobSnapshot,
    JobSourceInput, JobStatusKind, ResolvedJobSpec, RetryStageKind, RetryStageRequest,
    RetryStageSubmissionView, StageActionsView, StageRetryActionLinkView, StageRetryActionView,
    WorkflowKind,
};
use crate::services::job_launcher::start_job_execution;

use super::super::super::creation::create_translation_job;
use super::super::super::query::load_job_or_404;
use super::super::JobsFacade;
use super::rerun::prepare_in_place_render_job;

impl<'a> JobsFacade<'a> {
    pub fn stage_actions_view(
        &self,
        base_url: &str,
        job_id: &str,
    ) -> Result<StageActionsView, AppError> {
        let job = load_job_or_404(self.command.db, job_id)?;
        Ok(build_stage_actions_view(base_url, &job))
    }

    pub fn retry_stage_submission(
        &self,
        base_url: &str,
        source_job_id: &str,
        request: RetryStageRequest,
    ) -> Result<RetryStageSubmissionView, AppError> {
        if !request.mode.trim().is_empty() && request.mode.trim() != "from_stage" {
            return Err(AppError::bad_request(format!(
                "unsupported retry mode: {}",
                request.mode
            )));
        }

        let source_job = load_job_or_404(self.command.db, source_job_id)?;
        let plan = build_stage_plan(&source_job, request.stage.clone());
        if !plan.can_retry {
            return Err(AppError::bad_request(plan.disabled_reason));
        }

        let request_input = if request.create_new_job {
            build_retry_request(&source_job, &request.stage)?
        } else if matches!(request.stage, RetryStageKind::Render) {
            let mut job = prepare_in_place_render_job(source_job)?;
            apply_retry_overrides_to_resolved_spec(&mut job.request_payload, &request.overrides)?;
            job.request_payload.runtime.job_id = job.job_id.clone();
            job.sync_runtime_state();
            let job = start_job_execution(&self.command.submit.launcher, job)?;
            return Ok(build_retry_stage_submission_view(
                base_url,
                source_job_id,
                &job,
                RetryStageKind::Render,
                plan.will_reuse,
                plan.will_rerun,
                WorkflowKind::Render,
            ));
        } else {
            return Err(AppError::bad_request(
                "create_new_job=false is currently supported only for render retry",
            ));
        };

        let mut request_input = request_input;
        apply_retry_overrides(&mut request_input, &request.overrides)?;
        let workflow = request_input.workflow.clone();
        let job = create_translation_job(&self.command.submit, &request_input)?;
        Ok(build_retry_stage_submission_view(
            base_url,
            source_job_id,
            &job,
            request.stage,
            plan.will_reuse,
            plan.will_rerun,
            workflow,
        ))
    }
}

#[derive(Debug)]
struct StageRetryPlan {
    stage: RetryStageKind,
    label: String,
    can_retry: bool,
    disabled_reason: String,
    will_reuse: Vec<String>,
    will_rerun: Vec<String>,
    danger: bool,
}

fn build_stage_actions_view(base_url: &str, job: &JobSnapshot) -> StageActionsView {
    StageActionsView {
        job_id: job.job_id.clone(),
        stages: vec![
            build_stage_action(base_url, job, RetryStageKind::Ocr),
            build_stage_action(base_url, job, RetryStageKind::Translation),
            build_stage_action(base_url, job, RetryStageKind::Render),
        ],
    }
}

fn build_stage_action(
    base_url: &str,
    job: &JobSnapshot,
    stage: RetryStageKind,
) -> StageRetryActionView {
    let plan = build_stage_plan(job, stage.clone());
    let action = plan.can_retry.then(|| StageRetryActionLinkView {
        method: "POST".to_string(),
        url: absolute_url(
            base_url,
            &format!("/api/v1/jobs/{}/retry-stage", job.job_id),
        ),
        body: json!({ "stage": plan_stage_name(&stage) }),
    });
    StageRetryActionView {
        stage: plan.stage,
        label: plan.label,
        can_retry: plan.can_retry,
        reason: plan.disabled_reason.clone(),
        disabled_reason: plan.disabled_reason,
        action,
        will_reuse: plan.will_reuse,
        will_rerun: plan.will_rerun,
        danger: plan.danger,
    }
}

fn build_stage_plan(job: &JobSnapshot, stage: RetryStageKind) -> StageRetryPlan {
    let artifacts = job.artifacts.as_ref();
    let running = matches!(job.status, JobStatusKind::Queued | JobStatusKind::Running);
    let source_available =
        has_request_source(job) || has_artifact(artifacts, |item| &item.source_pdf);
    let ocr_available = has_artifact(artifacts, |item| &item.normalized_document_json)
        && has_artifact(artifacts, |item| &item.source_pdf);
    let translations_available = has_artifact(artifacts, |item| &item.translations_dir)
        && has_artifact(artifacts, |item| &item.source_pdf);

    let (label, mut can_retry, mut disabled_reason, will_reuse, will_rerun, danger) = match stage {
        RetryStageKind::Ocr => (
            "重试 OCR".to_string(),
            source_available && has_request_source(job),
            String::new(),
            vec!["source_pdf".to_string()],
            vec![
                "ocr".to_string(),
                "translation".to_string(),
                "render".to_string(),
            ],
            true,
        ),
        RetryStageKind::Translation => (
            "重试翻译".to_string(),
            ocr_available,
            String::new(),
            vec!["source_pdf".to_string(), "ocr_result".to_string()],
            vec!["translation".to_string(), "render".to_string()],
            false,
        ),
        RetryStageKind::Render => (
            "重新渲染".to_string(),
            translations_available,
            String::new(),
            vec![
                "source_pdf".to_string(),
                "ocr_result".to_string(),
                "translation_result".to_string(),
            ],
            vec!["render".to_string()],
            false,
        ),
    };

    if running {
        can_retry = false;
        disabled_reason = "job is queued or running; cancel it before retrying a stage".to_string();
    } else if !can_retry {
        disabled_reason = match stage {
            RetryStageKind::Ocr if !has_request_source(job) => {
                "OCR retry currently requires the original upload_id or source_url on the job"
                    .to_string()
            }
            RetryStageKind::Ocr => "source PDF is not available".to_string(),
            RetryStageKind::Translation => {
                "need source_pdf and normalized_document_json to retry translation".to_string()
            }
            RetryStageKind::Render => {
                "need source_pdf and translations_dir to retry render".to_string()
            }
        };
    }

    StageRetryPlan {
        stage,
        label,
        can_retry,
        disabled_reason,
        will_reuse,
        will_rerun,
        danger,
    }
}

fn build_retry_request(
    source_job: &JobSnapshot,
    stage: &RetryStageKind,
) -> Result<CreateJobInput, AppError> {
    let artifacts = source_job
        .artifacts
        .as_ref()
        .ok_or_else(|| AppError::bad_request("source job has no reusable artifacts"))?;
    let workflow = match stage {
        RetryStageKind::Ocr => WorkflowKind::Book,
        RetryStageKind::Translation => WorkflowKind::Book,
        RetryStageKind::Render => WorkflowKind::Render,
    };
    let mut request = CreateJobInput {
        workflow,
        source: JobSourceInput::default(),
        ocr: source_job.request_payload.ocr.clone(),
        translation: source_job.request_payload.translation.clone(),
        render: source_job.request_payload.render.clone(),
        runtime: source_job.request_payload.runtime.clone(),
    };
    match stage {
        RetryStageKind::Ocr => {
            request.source.upload_id = source_job.request_payload.source.upload_id.clone();
            request.source.source_url = source_job.request_payload.source.source_url.clone();
            if request.source.upload_id.trim().is_empty()
                && request.source.source_url.trim().is_empty()
            {
                return Err(AppError::bad_request(
                    "OCR retry requires the original upload_id or source_url",
                ));
            }
        }
        RetryStageKind::Translation => {
            require_artifact(
                artifacts.normalized_document_json.as_ref(),
                "normalized_document_json",
            )?;
            require_artifact(artifacts.source_pdf.as_ref(), "source_pdf")?;
            request.source.artifact_job_id = source_job.job_id.clone();
        }
        RetryStageKind::Render => {
            require_artifact(artifacts.translations_dir.as_ref(), "translations_dir")?;
            require_artifact(artifacts.source_pdf.as_ref(), "source_pdf")?;
            request.source.artifact_job_id = source_job.job_id.clone();
        }
    }
    request.runtime.job_id.clear();
    Ok(request)
}

fn apply_retry_overrides(input: &mut CreateJobInput, overrides: &Value) -> Result<(), AppError> {
    apply_retry_overrides_to_sections(
        overrides,
        |patch| {
            let patched = merge_json(to_json_value(&input.ocr)?, patch)?;
            input.ocr = serde_json::from_value(patched)
                .map_err(|err| AppError::bad_request(format!("invalid ocr overrides: {err}")))?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&input.translation)?, patch)?;
            input.translation = serde_json::from_value(patched).map_err(|err| {
                AppError::bad_request(format!("invalid translation overrides: {err}"))
            })?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&input.render)?, patch)?;
            input.render = serde_json::from_value(patched)
                .map_err(|err| AppError::bad_request(format!("invalid render overrides: {err}")))?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&input.runtime)?, patch)?;
            input.runtime = serde_json::from_value(patched).map_err(|err| {
                AppError::bad_request(format!("invalid runtime overrides: {err}"))
            })?;
            input.runtime.job_id.clear();
            Ok(())
        },
    )
}

fn apply_retry_overrides_to_resolved_spec(
    spec: &mut ResolvedJobSpec,
    overrides: &Value,
) -> Result<(), AppError> {
    apply_retry_overrides_to_sections(
        overrides,
        |patch| {
            let patched = merge_json(to_json_value(&spec.ocr)?, patch)?;
            spec.ocr = serde_json::from_value(patched)
                .map_err(|err| AppError::bad_request(format!("invalid ocr overrides: {err}")))?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&spec.translation)?, patch)?;
            spec.translation = serde_json::from_value(patched).map_err(|err| {
                AppError::bad_request(format!("invalid translation overrides: {err}"))
            })?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&spec.render)?, patch)?;
            spec.render = serde_json::from_value(patched)
                .map_err(|err| AppError::bad_request(format!("invalid render overrides: {err}")))?;
            Ok(())
        },
        |patch| {
            let patched = merge_json(to_json_value(&spec.runtime)?, patch)?;
            spec.runtime = serde_json::from_value(patched).map_err(|err| {
                AppError::bad_request(format!("invalid runtime overrides: {err}"))
            })?;
            Ok(())
        },
    )
}

fn apply_retry_overrides_to_sections(
    overrides: &Value,
    mut apply_ocr: impl FnMut(Value) -> Result<(), AppError>,
    mut apply_translation: impl FnMut(Value) -> Result<(), AppError>,
    mut apply_render: impl FnMut(Value) -> Result<(), AppError>,
    mut apply_runtime: impl FnMut(Value) -> Result<(), AppError>,
) -> Result<(), AppError> {
    if overrides.is_null() {
        return Ok(());
    }
    let Some(object) = overrides.as_object() else {
        return Err(AppError::bad_request("overrides must be a JSON object"));
    };
    for (section, patch) in object {
        match section.as_str() {
            "ocr" => apply_ocr(patch.clone())?,
            "translation" => apply_translation(patch.clone())?,
            "render" => apply_render(patch.clone())?,
            "runtime" => apply_runtime(patch.clone())?,
            other => {
                return Err(AppError::bad_request(format!(
                    "unsupported overrides section: {other}"
                )));
            }
        }
    }
    Ok(())
}

fn to_json_value<T: serde::Serialize>(value: &T) -> Result<Value, AppError> {
    serde_json::to_value(value)
        .map_err(|err| AppError::internal(format!("failed to encode retry override base: {err}")))
}

fn merge_json(mut base: Value, patch: Value) -> Result<Value, AppError> {
    let Some(base_object) = base.as_object_mut() else {
        return Err(AppError::internal("override base is not an object"));
    };
    let Some(patch_object) = patch.as_object() else {
        return Err(AppError::bad_request(
            "override sections must be JSON objects",
        ));
    };
    for (key, value) in patch_object {
        base_object.insert(key.clone(), value.clone());
    }
    Ok(base)
}

fn build_retry_stage_submission_view(
    base_url: &str,
    source_job_id: &str,
    job: &JobSnapshot,
    stage: RetryStageKind,
    reused_artifacts: Vec<String>,
    rerun_stages: Vec<String>,
    workflow: WorkflowKind,
) -> RetryStageSubmissionView {
    let mut view_job = job.clone();
    view_job.workflow = workflow.clone();
    RetryStageSubmissionView {
        job_id: job.job_id.clone(),
        source_job_id: source_job_id.to_string(),
        status: JobStatusKind::Queued,
        workflow: workflow.clone(),
        rerun_from_stage: stage,
        reused_artifacts,
        rerun_stages,
        links: build_job_links_with_workflow(&job.job_id, &workflow, base_url),
        actions: build_job_actions(&view_job, base_url, false, false, false),
    }
}

fn require_artifact(value: Option<&String>, name: &str) -> Result<(), AppError> {
    if value.as_ref().is_some_and(|item| !item.trim().is_empty()) {
        Ok(())
    } else {
        Err(AppError::bad_request(format!(
            "source job missing required artifact: {name}"
        )))
    }
}

fn has_request_source(job: &JobSnapshot) -> bool {
    !job.request_payload.source.upload_id.trim().is_empty()
        || !job.request_payload.source.source_url.trim().is_empty()
}

fn has_artifact(
    artifacts: Option<&JobArtifacts>,
    pick: impl Fn(&JobArtifacts) -> &Option<String>,
) -> bool {
    artifacts
        .and_then(|item| pick(item).as_deref())
        .map(str::trim)
        .is_some_and(|item| !item.is_empty())
}

fn plan_stage_name(stage: &RetryStageKind) -> &'static str {
    match stage {
        RetryStageKind::Ocr => "ocr",
        RetryStageKind::Translation => "translation",
        RetryStageKind::Render => "render",
    }
}

fn absolute_url(base_url: &str, path: &str) -> String {
    format!("{}{}", base_url.trim_end_matches('/'), path)
}
