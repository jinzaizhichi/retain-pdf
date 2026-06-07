use crate::error::AppError;
use crate::models::{to_absolute_url, JobSnapshot, MarkdownDocumentView, MarkdownImageView};
use crate::storage_paths::{resolve_markdown_images_dir, resolve_markdown_path};

use super::paths::safe_markdown_image_path;
use super::{FileDownload, MarkdownDownload, QueryJobsDeps};
use crate::services::jobs::presentation::load_supported_job;

const MARKDOWN_IMAGE_LINK_RE: &str = r#"!\[([^\]]*)\]\((images/[^)]+)\)"#;

pub(crate) async fn markdown_download(
    deps: &QueryJobsDeps<'_>,
    job_id: String,
) -> Result<MarkdownDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, &job_id)?;
    let markdown_path = resolve_markdown_path(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("markdown not found: {job_id}")))?;
    let content = tokio::fs::read_to_string(&markdown_path).await?;
    Ok(MarkdownDownload {
        job_id: job.job_id.clone(),
        content,
    })
}

pub(crate) async fn markdown_document_view(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    base_url: &str,
) -> Result<MarkdownDocumentView, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let markdown_path = resolve_markdown_path(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("markdown not found: {job_id}")))?;
    let content = tokio::fs::read_to_string(&markdown_path).await?;
    let raw_path = format!("/api/v1/jobs/{}/markdown?raw=true", job.job_id);
    let markdown_path_url = format!("/api/v1/jobs/{}/markdown/document", job.job_id);
    let images_base_path = format!("/api/v1/jobs/{}/markdown/images/", job.job_id);
    let images = markdown_images_view(deps, &job, base_url)?;
    let content_with_absolute_image_urls =
        rewrite_markdown_image_links_to_absolute_urls(&content, &job.job_id, base_url);
    Ok(MarkdownDocumentView {
        job_id: job.job_id.clone(),
        ready: true,
        content,
        content_with_absolute_image_urls,
        markdown_path: markdown_path_url.clone(),
        markdown_url: to_absolute_url(base_url, &markdown_path_url),
        raw_path: raw_path.clone(),
        raw_url: to_absolute_url(base_url, &raw_path),
        images_base_path: images_base_path.clone(),
        images_base_url: to_absolute_url(base_url, &images_base_path),
        images,
    })
}

pub(crate) fn markdown_image_download(
    deps: &QueryJobsDeps<'_>,
    job_id: &str,
    path: &str,
) -> Result<FileDownload, AppError> {
    let job = load_supported_job(deps.db, deps.data_root, job_id)?;
    let images_dir = resolve_markdown_images_dir(&job, deps.data_root)
        .ok_or_else(|| AppError::not_found(format!("markdown images not found: {job_id}")))?;
    let relative_path = safe_markdown_image_path(path)?;
    let file_path = images_dir.join(relative_path);
    if !file_path.exists() || !file_path.is_file() {
        return Err(AppError::not_found(format!(
            "markdown image not found: {path}"
        )));
    }
    let mime = mime_guess::from_path(&file_path).first_or_octet_stream();
    Ok(FileDownload::new(file_path, mime.as_ref(), None))
}

fn markdown_images_view(
    deps: &QueryJobsDeps<'_>,
    job: &JobSnapshot,
    base_url: &str,
) -> Result<Vec<MarkdownImageView>, AppError> {
    let Some(images_dir) = resolve_markdown_images_dir(job, deps.data_root) else {
        return Ok(Vec::new());
    };
    let mut images = Vec::new();
    for entry in walkdir::WalkDir::new(&images_dir)
        .into_iter()
        .filter_map(std::result::Result::ok)
        .filter(|entry| entry.file_type().is_file())
    {
        let path = entry.path();
        let Ok(relative) = path.strip_prefix(&images_dir) else {
            continue;
        };
        let relative_path = relative.to_string_lossy().replace('\\', "/");
        let resource_path = format!(
            "/api/v1/jobs/{}/markdown/images/{}",
            job.job_id,
            url_path_escape(&relative_path)
        );
        let metadata = path.metadata().ok();
        images.push(MarkdownImageView {
            path: format!("images/{relative_path}"),
            url: to_absolute_url(base_url, &resource_path),
            content_type: mime_guess::from_path(path)
                .first_or_octet_stream()
                .to_string(),
            size_bytes: metadata.map(|item| item.len()),
        });
    }
    images.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(images)
}

fn rewrite_markdown_image_links_to_absolute_urls(
    content: &str,
    job_id: &str,
    base_url: &str,
) -> String {
    let re = regex::Regex::new(MARKDOWN_IMAGE_LINK_RE).expect("valid markdown image regex");
    re.replace_all(content, |captures: &regex::Captures<'_>| {
        let alt = &captures[1];
        let path = &captures[2];
        let relative = path.strip_prefix("images/").unwrap_or(path);
        let resource_path = format!(
            "/api/v1/jobs/{job_id}/markdown/images/{}",
            url_path_escape(relative)
        );
        format!("![{alt}]({})", to_absolute_url(base_url, &resource_path))
    })
    .into_owned()
}

fn url_path_escape(path: &str) -> String {
    path.split('/')
        .map(percent_encode_path_segment)
        .collect::<Vec<_>>()
        .join("/")
}

fn percent_encode_path_segment(segment: &str) -> String {
    let mut encoded = String::new();
    for byte in segment.as_bytes() {
        let ch = *byte as char;
        if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | '~') {
            encoded.push(ch);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}
