use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::ocr_provider::OcrProviderDiagnostics;
use crate::storage_paths::{
    resolve_markdown_path, resolve_normalization_report, resolve_normalized_document,
    resolve_output_pdf,
};

use super::common::{
    ActionLinkView, JobActionsView, JobLinksView, JobProgressView, JobTimestampsView,
};
#[cfg(test)]
use super::test_support::{
    build_ocr_job_summary, job_failure_to_legacy_view, load_glossary_summary,
    load_invocation_summary, load_normalization_summary,
};
use super::to_absolute_url;
#[cfg(test)]
use crate::job_failure::classify_job_failure;
#[cfg(test)]
use crate::models::public_request_payload;
use crate::models::{
    JobArtifactRecord, JobFailureInfo, JobRuntimeInfo, JobSnapshot, JobStatusKind,
    PublicResolvedJobSpec, UploadRecord, UploadView, WorkflowKind,
};

#[derive(Debug, Serialize)]
pub struct ResourceLinkView {
    pub ready: bool,
    pub path: String,
    pub url: String,
    pub method: String,
    pub content_type: String,
    pub file_name: Option<String>,
    pub size_bytes: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct MarkdownArtifactView {
    pub ready: bool,
    pub json_path: String,
    pub json_url: String,
    pub raw_path: String,
    pub raw_url: String,
    pub images_base_path: String,
    pub images_base_url: String,
    pub file_name: Option<String>,
    pub size_bytes: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct ArtifactLinksView {
    pub pdf_ready: bool,
    pub markdown_ready: bool,
    pub bundle_ready: bool,
    pub schema_version: Option<String>,
    pub provider_raw_dir: Option<String>,
    pub provider_zip: Option<String>,
    pub provider_summary_json: Option<String>,
    pub pdf_url: String,
    pub markdown_url: String,
    pub markdown_images_base_url: String,
    pub bundle_url: String,
    pub normalized_document_url: String,
    pub normalization_report_url: String,
    pub manifest_path: String,
    pub manifest_url: String,
    pub actions: JobActionsView,
    pub normalized_document: ResourceLinkView,
    pub normalization_report: ResourceLinkView,
    pub pdf: ResourceLinkView,
    pub markdown: MarkdownArtifactView,
    pub bundle: ResourceLinkView,
}

#[derive(Debug, Serialize)]
pub struct JobArtifactItemView {
    pub artifact_key: String,
    pub artifact_group: String,
    pub artifact_kind: String,
    pub ready: bool,
    pub file_name: Option<String>,
    pub content_type: String,
    pub size_bytes: Option<u64>,
    pub relative_path: String,
    pub checksum: Option<String>,
    pub source_stage: Option<String>,
    pub updated_at: String,
    pub resource_path: Option<String>,
    pub resource_url: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct JobArtifactManifestView {
    pub job_id: String,
    pub items: Vec<JobArtifactItemView>,
}

#[derive(Debug, Serialize)]
pub struct JobDetailView {
    pub job_id: String,
    pub workflow: WorkflowKind,
    pub status: JobStatusKind,
    pub request_payload: PublicResolvedJobSpec,
    pub trace_id: Option<String>,
    pub provider_trace_id: Option<String>,
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress: JobProgressView,
    pub timestamps: JobTimestampsView,
    pub links: JobLinksView,
    pub actions: JobActionsView,
    pub artifacts: ArtifactLinksView,
    pub ocr_job: Option<OcrJobSummaryView>,
    pub ocr_provider_diagnostics: Option<OcrProviderDiagnostics>,
    pub runtime: Option<JobRuntimeInfo>,
    pub failure: Option<JobFailureInfo>,
    pub error: Option<String>,
    pub failure_diagnostic: Option<JobFailureDiagnosticView>,
    pub normalization_summary: Option<NormalizationSummaryView>,
    pub glossary_summary: Option<GlossaryUsageSummaryView>,
    pub invocation: Option<InvocationSummaryView>,
    pub log_tail: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct JobFailureDiagnosticView {
    pub failed_stage: String,
    pub error_kind: String,
    pub summary: String,
    pub root_cause: Option<String>,
    pub retryable: bool,
    pub upstream_host: Option<String>,
    pub suggestion: Option<String>,
    pub last_log_line: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct NormalizationSummaryView {
    pub provider: String,
    pub detected_provider: String,
    pub provider_was_explicit: bool,
    pub pages_seen: Option<i64>,
    pub blocks_seen: Option<i64>,
    pub document_defaults: usize,
    pub page_defaults: usize,
    pub block_defaults: usize,
    pub schema: String,
    pub schema_version: String,
    pub page_count: Option<i64>,
    pub block_count: Option<i64>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct GlossaryUsageSummaryView {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub glossary_id: String,
    #[serde(default)]
    pub glossary_name: String,
    #[serde(default)]
    pub entry_count: i64,
    #[serde(default)]
    pub resource_entry_count: i64,
    #[serde(default)]
    pub inline_entry_count: i64,
    #[serde(default)]
    pub overridden_entry_count: i64,
    #[serde(default)]
    pub source_hit_entry_count: i64,
    #[serde(default)]
    pub target_hit_entry_count: i64,
    #[serde(default)]
    pub unused_entry_count: i64,
    #[serde(default)]
    pub unapplied_source_hit_entry_count: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct InvocationSummaryView {
    #[serde(default)]
    pub stage: String,
    #[serde(default)]
    pub input_protocol: String,
    #[serde(default)]
    pub stage_spec_schema_version: String,
}

#[derive(Debug, Serialize)]
pub struct JobListItemView {
    pub job_id: String,
    pub display_name: String,
    pub workflow: WorkflowKind,
    pub status: JobStatusKind,
    pub trace_id: Option<String>,
    pub stage: Option<String>,
    pub invocation: Option<InvocationSummaryView>,
    pub created_at: String,
    pub updated_at: String,
    pub detail_path: String,
    pub detail_url: String,
}

#[derive(Debug, Serialize, Default)]
pub struct JobListInvocationSummaryView {
    pub stage_spec_count: usize,
    pub unknown_count: usize,
}

#[derive(Debug, Serialize)]
pub struct OcrJobSummaryView {
    pub job_id: String,
    pub status: Option<JobStatusKind>,
    pub trace_id: Option<String>,
    pub provider_trace_id: Option<String>,
    pub detail_path: String,
    pub detail_url: String,
}

#[derive(Debug, Serialize)]
pub struct JobListView {
    pub items: Vec<JobListItemView>,
    pub invocation_summary: JobListInvocationSummaryView,
}

pub fn build_job_links(job_id: &str, base_url: &str) -> JobLinksView {
    build_job_links_with_workflow(job_id, &WorkflowKind::Book, base_url)
}

fn job_path_prefix(workflow: &WorkflowKind) -> &'static str {
    match workflow {
        WorkflowKind::Ocr => "/api/v1/ocr/jobs",
        WorkflowKind::Book | WorkflowKind::Translate | WorkflowKind::Render => "/api/v1/jobs",
    }
}

pub fn build_job_links_with_workflow(
    job_id: &str,
    workflow: &WorkflowKind,
    base_url: &str,
) -> JobLinksView {
    let prefix = job_path_prefix(workflow);
    let self_path = format!("{prefix}/{job_id}");
    let artifacts_path = format!("{prefix}/{job_id}/artifacts");
    let artifacts_manifest_path = format!("{prefix}/{job_id}/artifacts-manifest");
    let events_path = format!("{prefix}/{job_id}/events");
    let cancel_path = format!("{prefix}/{job_id}/cancel");
    JobLinksView {
        self_path: self_path.clone(),
        self_url: to_absolute_url(base_url, &self_path),
        artifacts_path: artifacts_path.clone(),
        artifacts_url: to_absolute_url(base_url, &artifacts_path),
        artifacts_manifest_path: artifacts_manifest_path.clone(),
        artifacts_manifest_url: to_absolute_url(base_url, &artifacts_manifest_path),
        events_path: events_path.clone(),
        events_url: to_absolute_url(base_url, &events_path),
        cancel_path: cancel_path.clone(),
        cancel_url: to_absolute_url(base_url, &cancel_path),
    }
}

fn can_cancel(status: &JobStatusKind) -> bool {
    matches!(status, JobStatusKind::Queued | JobStatusKind::Running)
}

fn action_link(enabled: bool, method: &str, path: String, base_url: &str) -> ActionLinkView {
    ActionLinkView {
        enabled,
        method: method.to_string(),
        url: to_absolute_url(base_url, &path),
        path,
    }
}

pub fn build_job_actions(
    job: &JobSnapshot,
    base_url: &str,
    pdf_ready: bool,
    markdown_ready: bool,
    bundle_ready: bool,
) -> JobActionsView {
    let prefix = job_path_prefix(&job.workflow);
    let job_path = format!("{prefix}/{}", job.job_id);
    let artifacts_path = format!("{prefix}/{}/artifacts", job.job_id);
    let cancel_path = format!("{prefix}/{}/cancel", job.job_id);
    let pdf_path = format!("{prefix}/{}/pdf", job.job_id);
    let markdown_path = format!("{prefix}/{}/markdown", job.job_id);
    let markdown_raw_path = format!("{prefix}/{}/markdown?raw=true", job.job_id);
    let bundle_path = format!("{prefix}/{}/download", job.job_id);
    JobActionsView {
        open_job: action_link(true, "GET", job_path, base_url),
        open_artifacts: action_link(true, "GET", artifacts_path, base_url),
        cancel: action_link(can_cancel(&job.status), "POST", cancel_path, base_url),
        download_pdf: action_link(pdf_ready, "GET", pdf_path, base_url),
        open_markdown: action_link(markdown_ready, "GET", markdown_path, base_url),
        open_markdown_raw: action_link(markdown_ready, "GET", markdown_raw_path, base_url),
        download_bundle: action_link(bundle_ready, "GET", bundle_path, base_url),
    }
}

pub fn build_artifact_links(
    job: &JobSnapshot,
    base_url: &str,
    data_root: &Path,
    pdf_ready: bool,
    markdown_ready: bool,
    bundle_ready: bool,
) -> ArtifactLinksView {
    let prefix = job_path_prefix(&job.workflow);
    let pdf_path = format!("{prefix}/{}/pdf", job.job_id);
    let markdown_path = format!("{prefix}/{}/markdown", job.job_id);
    let markdown_raw_path = format!("{prefix}/{}/markdown?raw=true", job.job_id);
    let markdown_images_base_path = format!("{prefix}/{}/markdown/images/", job.job_id);
    let bundle_path = format!("{prefix}/{}/download", job.job_id);
    let manifest_path = format!("{prefix}/{}/artifacts-manifest", job.job_id);
    let normalized_document_path = format!("{prefix}/{}/normalized-document", job.job_id);
    let normalization_report_path = format!("{prefix}/{}/normalization-report", job.job_id);
    let pdf_file_path = resolve_output_pdf(job, data_root);
    let markdown_file_path = resolve_markdown_path(job, data_root);
    let normalized_document_file_path = resolve_normalized_document(job, data_root);
    let normalization_report_file_path = resolve_normalization_report(job, data_root);
    let bundle_file_name = format!("{}.zip", job.job_id);
    let actions = build_job_actions(job, base_url, pdf_ready, markdown_ready, bundle_ready);
    ArtifactLinksView {
        pdf_ready,
        markdown_ready,
        bundle_ready,
        schema_version: job
            .artifacts
            .as_ref()
            .and_then(|item| item.schema_version.clone()),
        provider_raw_dir: job
            .artifacts
            .as_ref()
            .and_then(|item| item.provider_raw_dir.clone()),
        provider_zip: job
            .artifacts
            .as_ref()
            .and_then(|item| item.provider_zip.clone()),
        provider_summary_json: job
            .artifacts
            .as_ref()
            .and_then(|item| item.provider_summary_json.clone()),
        pdf_url: pdf_path.clone(),
        markdown_url: markdown_path.clone(),
        markdown_images_base_url: markdown_images_base_path.clone(),
        bundle_url: bundle_path.clone(),
        normalized_document_url: normalized_document_path.clone(),
        normalization_report_url: normalization_report_path.clone(),
        manifest_path: manifest_path.clone(),
        manifest_url: to_absolute_url(base_url, &manifest_path),
        actions,
        normalized_document: ResourceLinkView {
            ready: normalized_document_file_path.is_some(),
            path: normalized_document_path.clone(),
            url: to_absolute_url(base_url, &normalized_document_path),
            method: "GET".to_string(),
            content_type: "application/json".to_string(),
            file_name: file_name_from_path(normalized_document_file_path.as_deref()),
            size_bytes: file_size(normalized_document_file_path.as_deref()),
        },
        normalization_report: ResourceLinkView {
            ready: normalization_report_file_path.is_some(),
            path: normalization_report_path.clone(),
            url: to_absolute_url(base_url, &normalization_report_path),
            method: "GET".to_string(),
            content_type: "application/json".to_string(),
            file_name: file_name_from_path(normalization_report_file_path.as_deref()),
            size_bytes: file_size(normalization_report_file_path.as_deref()),
        },
        pdf: ResourceLinkView {
            ready: pdf_ready,
            path: pdf_path.clone(),
            url: to_absolute_url(base_url, &pdf_path),
            method: "GET".to_string(),
            content_type: "application/pdf".to_string(),
            file_name: file_name_from_path(pdf_file_path.as_deref()),
            size_bytes: file_size(pdf_file_path.as_deref()),
        },
        markdown: MarkdownArtifactView {
            ready: markdown_ready,
            json_path: markdown_path.clone(),
            json_url: to_absolute_url(base_url, &markdown_path),
            raw_path: markdown_raw_path.clone(),
            raw_url: to_absolute_url(base_url, &markdown_raw_path),
            images_base_path: markdown_images_base_path.clone(),
            images_base_url: to_absolute_url(base_url, &markdown_images_base_path),
            file_name: file_name_from_path(markdown_file_path.as_deref()),
            size_bytes: file_size(markdown_file_path.as_deref()),
        },
        bundle: ResourceLinkView {
            ready: bundle_ready,
            path: bundle_path.clone(),
            url: to_absolute_url(base_url, &bundle_path),
            method: "GET".to_string(),
            content_type: "application/zip".to_string(),
            file_name: Some(bundle_file_name),
            size_bytes: None,
        },
    }
}

pub fn build_artifact_manifest(
    job: &JobSnapshot,
    base_url: &str,
    items: &[JobArtifactRecord],
) -> JobArtifactManifestView {
    JobArtifactManifestView {
        job_id: job.job_id.clone(),
        items: items
            .iter()
            .map(|item| JobArtifactItemView {
                artifact_key: item.artifact_key.clone(),
                artifact_group: item.artifact_group.clone(),
                artifact_kind: item.artifact_kind.clone(),
                ready: item.ready,
                file_name: item.file_name.clone(),
                content_type: item.content_type.clone(),
                size_bytes: item.size_bytes,
                relative_path: item.relative_path.clone(),
                checksum: item.checksum.clone(),
                source_stage: item.source_stage.clone(),
                updated_at: item.updated_at.clone(),
                resource_path: crate::services::artifacts::artifact_resource_path(
                    job,
                    &item.artifact_key,
                ),
                resource_url: crate::services::artifacts::artifact_resource_path(
                    job,
                    &item.artifact_key,
                )
                .map(|path| to_absolute_url(base_url, &path)),
            })
            .collect(),
    }
}

#[cfg(test)]
pub fn job_to_detail(
    job: &JobSnapshot,
    base_url: &str,
    data_root: &Path,
    pdf_ready: bool,
    markdown_ready: bool,
    bundle_ready: bool,
) -> JobDetailView {
    let duration_seconds = match (&job.started_at, &job.finished_at, &job.result) {
        (_, _, Some(result)) => Some(result.duration_seconds),
        _ => None,
    };
    let percent = match (job.progress_current, job.progress_total) {
        (Some(current), Some(total)) if total > 0 => Some((current as f64 / total as f64) * 100.0),
        _ => None,
    };
    let failure = job.failure.clone().or_else(|| classify_job_failure(job));
    JobDetailView {
        job_id: job.job_id.clone(),
        workflow: job.workflow.clone(),
        status: job.status.clone(),
        request_payload: public_request_payload(&job.request_payload),
        trace_id: job
            .artifacts
            .as_ref()
            .and_then(|item| item.trace_id.clone()),
        provider_trace_id: job
            .artifacts
            .as_ref()
            .and_then(|item| item.provider_trace_id.clone()),
        stage: job.stage.clone(),
        stage_detail: job.stage_detail.clone(),
        progress: JobProgressView {
            current: job.progress_current,
            total: job.progress_total,
            percent,
        },
        timestamps: JobTimestampsView {
            created_at: job.created_at.clone(),
            updated_at: job.updated_at.clone(),
            started_at: job.started_at.clone(),
            finished_at: job.finished_at.clone(),
            duration_seconds,
        },
        links: build_job_links_with_workflow(&job.job_id, &job.workflow, base_url),
        actions: build_job_actions(job, base_url, pdf_ready, markdown_ready, bundle_ready),
        artifacts: build_artifact_links(
            job,
            base_url,
            data_root,
            pdf_ready,
            markdown_ready,
            bundle_ready,
        ),
        ocr_job: build_ocr_job_summary(job, base_url),
        ocr_provider_diagnostics: job
            .artifacts
            .as_ref()
            .and_then(|artifacts| artifacts.ocr_provider_diagnostics.clone()),
        runtime: job.runtime.clone(),
        failure: failure.clone(),
        error: job.error.clone(),
        failure_diagnostic: failure.as_ref().map(job_failure_to_legacy_view),
        normalization_summary: load_normalization_summary(job, data_root),
        glossary_summary: load_glossary_summary(job, data_root),
        invocation: load_invocation_summary(job, data_root),
        log_tail: job.log_tail.clone(),
    }
}

#[cfg(test)]
pub fn job_to_list_item(
    job: &JobSnapshot,
    base_url: &str,
    display_name: String,
    data_root: &Path,
) -> JobListItemView {
    let detail_path = format!("{}/{}", job_path_prefix(&job.workflow), job.job_id);
    JobListItemView {
        job_id: job.job_id.clone(),
        display_name,
        workflow: job.workflow.clone(),
        status: job.status.clone(),
        trace_id: job
            .artifacts
            .as_ref()
            .and_then(|item| item.trace_id.clone()),
        stage: job.stage.clone(),
        invocation: load_invocation_summary(job, data_root),
        created_at: job.created_at.clone(),
        updated_at: job.updated_at.clone(),
        detail_url: to_absolute_url(base_url, &detail_path),
        detail_path,
    }
}

pub fn summarize_list_invocation(items: &[JobListItemView]) -> JobListInvocationSummaryView {
    let mut summary = JobListInvocationSummaryView::default();
    for item in items {
        match item
            .invocation
            .as_ref()
            .map(|value| value.input_protocol.as_str())
            .unwrap_or("")
        {
            "stage_spec" => summary.stage_spec_count += 1,
            _ => summary.unknown_count += 1,
        }
    }
    summary
}

pub fn upload_to_response(upload: &UploadRecord) -> UploadView {
    UploadView {
        upload_id: upload.upload_id.clone(),
        filename: upload.filename.clone(),
        bytes: upload.bytes,
        page_count: upload.page_count,
        uploaded_at: upload.uploaded_at.clone(),
    }
}

fn file_name_from_path(path: Option<&Path>) -> Option<String> {
    path.and_then(|p| p.file_name())
        .map(|v| v.to_string_lossy().to_string())
}

fn file_size(path: Option<&Path>) -> Option<u64> {
    path.and_then(|p| std::fs::metadata(p).ok())
        .map(|meta| meta.len())
}
