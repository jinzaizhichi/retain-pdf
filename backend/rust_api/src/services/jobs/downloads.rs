use std::path::PathBuf;

use crate::error::AppError;
use crate::models::PagePreviewQuery;
use crate::storage_paths::{resolve_output_pdf, resolve_source_pdf};

use super::creation::context::QueryJobsDeps;
use super::presentation::load_supported_job;

// Keep this file as the small public facade for job downloads. Concrete
// handlers live in submodules so PDF, markdown, preview, and artifact behavior
// can evolve without turning one route helper into another large grab bag.
mod artifacts;
mod documents;
mod markdown;
mod paths;
mod pdf;
mod previews;

use previews::{
    preview_kind, render_book_image, render_pdf_page_preview, BookImageKind, PagePreviewKind,
};

pub(crate) use artifacts::{bundle_download, registered_artifact_download};
pub(crate) use documents::document_download;
pub(crate) use markdown::{markdown_document_view, markdown_download, markdown_image_download};

#[derive(Debug)]
pub struct FileDownload {
    pub path: PathBuf,
    pub content_type: String,
    pub download_name: Option<String>,
    pub job_id_header: Option<String>,
}

impl FileDownload {
    pub fn new(
        path: PathBuf,
        content_type: impl Into<String>,
        download_name: Option<String>,
    ) -> Self {
        Self {
            path,
            content_type: content_type.into(),
            download_name,
            job_id_header: None,
        }
    }

    pub fn with_job_id_header(mut self, job_id: impl Into<String>) -> Self {
        self.job_id_header = Some(job_id.into());
        self
    }
}

#[derive(Debug)]
pub struct MarkdownDownload {
    pub job_id: String,
    pub content: String,
}

pub fn page_preview_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    page: u32,
    query: &PagePreviewQuery,
) -> Result<FileDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let source_pdf = match preview_kind(&query.kind)? {
        PagePreviewKind::Source => resolve_source_pdf(&job, deps.data_root)
            .ok_or_else(|| AppError::not_found(format!("source pdf not ready: {}", job.job_id)))?,
        PagePreviewKind::Translated => {
            resolve_output_pdf(&job, deps.data_root).ok_or_else(|| {
                AppError::not_found(format!("translated pdf not ready: {}", job.job_id))
            })?
        }
    };
    let page_index = page
        .checked_sub(1)
        .ok_or_else(|| AppError::bad_request("page must be 1-based"))?;
    let width_px = query.width.unwrap_or(1200).clamp(240, 2400);
    let dpi = query.dpi.unwrap_or(0).min(300);
    let output_dir = paths::job_artifacts_dir(deps, &job)?;
    let output_path = output_dir.join(format!(
        "preview-{}-p{:04}-w{}-d{}.jpg",
        preview_kind(&query.kind)?.as_str(),
        page,
        width_px,
        dpi
    ));
    if output_path.exists() && output_path.is_file() {
        return Ok(FileDownload::new(output_path, "image/jpeg", None));
    }
    render_pdf_page_preview(
        deps.replay.python_bin,
        &source_pdf,
        &output_path,
        page_index,
        width_px,
        dpi,
    )?;
    Ok(FileDownload::new(output_path, "image/jpeg", None))
}

pub fn cover_download(deps: &QueryJobsDeps<'_>, job_id: &str) -> Result<FileDownload, AppError> {
    let path = render_book_image(deps, job_id, BookImageKind::Cover)?;
    Ok(FileDownload::new(path, "image/jpeg", None))
}

pub fn thumbnail_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
) -> Result<FileDownload, AppError> {
    let path = render_book_image(deps, job_id, BookImageKind::Thumbnail)?;
    Ok(FileDownload::new(path, "image/jpeg", None))
}
