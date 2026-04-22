use std::path::{Path, PathBuf};

use lopdf::Document;
use tokio::io::AsyncWriteExt;

use crate::db::Db;
use crate::error::AppError;
use crate::models::{build_job_id, now_iso, UploadRecord};

#[derive(Debug)]
pub struct UploadedPdfInput {
    pub filename: String,
    pub bytes: Vec<u8>,
    pub developer_mode: bool,
}

pub(super) fn load_upload_or_404(db: &Db, upload_id: &str) -> Result<UploadRecord, AppError> {
    db.get_upload(upload_id)
        .map_err(|_| AppError::not_found(format!("upload not found: {upload_id}")))
}

pub async fn store_pdf_upload(
    db: &Db,
    uploads_dir: &Path,
    upload_max_bytes: u64,
    upload_max_pages: u32,
    upload: UploadedPdfInput,
) -> Result<UploadRecord, AppError> {
    if !upload.filename.to_lowercase().ends_with(".pdf") {
        return Err(AppError::bad_request("uploaded file must be a PDF"));
    }
    let byte_count = upload.bytes.len() as u64;
    let upload_id = build_job_id();
    let upload_dir = uploads_dir.join(&upload_id);
    tokio::fs::create_dir_all(&upload_dir).await?;
    let upload_path: PathBuf = upload_dir.join(&upload.filename);
    let mut f = tokio::fs::File::create(&upload_path).await?;
    f.write_all(&upload.bytes).await?;
    f.flush().await?;

    let page_count = Document::load(&upload_path)
        .map(|doc| doc.get_pages().len() as u32)
        .map_err(|e| AppError::bad_request(format!("invalid pdf: {e}")))?;

    if upload_max_bytes > 0 && byte_count > upload_max_bytes {
        return Err(AppError::bad_request(format!(
            "当前服务限制：PDF 文件大小必须不超过 {:.2}MB",
            upload_max_bytes as f64 / 1024.0 / 1024.0
        )));
    }
    if upload_max_pages > 0 && page_count > upload_max_pages {
        return Err(AppError::bad_request(format!(
            "当前服务限制：PDF 页数必须不超过 {} 页",
            upload_max_pages
        )));
    }

    let record = UploadRecord {
        upload_id,
        filename: upload.filename,
        stored_path: upload_path.to_string_lossy().to_string(),
        bytes: byte_count,
        page_count,
        uploaded_at: now_iso(),
        developer_mode: upload.developer_mode,
    };
    db.save_upload(&record)?;
    Ok(record)
}
