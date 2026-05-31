use axum::extract::Multipart;

use crate::error::AppError;
use crate::models::CreateJobInput;

use super::fields::apply_multipart_request_field;

pub struct ParsedTranslateBundle {
    pub filename: String,
    pub file_bytes: Vec<u8>,
    pub developer_mode: bool,
    pub request: CreateJobInput,
}

pub struct ParsedOcrJob {
    pub filename: Option<String>,
    pub file_bytes: Option<Vec<u8>>,
    pub developer_mode: bool,
    pub request: CreateJobInput,
}

pub async fn parse_translate_bundle_request(
    multipart: &mut Multipart,
) -> Result<ParsedTranslateBundle, AppError> {
    let mut file_name: Option<String> = None;
    let mut file_bytes: Option<Vec<u8>> = None;
    let mut developer_mode = false;
    let mut request = CreateJobInput::default();

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::bad_request(e.to_string()))?
    {
        let name = field.name().unwrap_or_default().trim().to_string();
        if name.is_empty() {
            continue;
        }
        if name == "file" {
            let filename = field
                .file_name()
                .map(|s| s.to_string())
                .unwrap_or_else(|| "upload.pdf".to_string());
            let data = field
                .bytes()
                .await
                .map_err(|e| AppError::bad_request(e.to_string()))?;
            file_name = Some(filename);
            file_bytes = Some(data.to_vec());
            continue;
        }

        let value = field
            .text()
            .await
            .map_err(|e| AppError::bad_request(e.to_string()))?;
        apply_multipart_request_field(&mut request, &mut developer_mode, &name, value.trim())?;
    }

    Ok(ParsedTranslateBundle {
        filename: file_name
            .ok_or_else(|| AppError::bad_request("missing multipart field: file"))?,
        file_bytes: file_bytes.ok_or_else(|| AppError::bad_request("empty upload"))?,
        developer_mode,
        request,
    })
}

pub async fn parse_ocr_job_request(multipart: &mut Multipart) -> Result<ParsedOcrJob, AppError> {
    let mut file_name: Option<String> = None;
    let mut file_bytes: Option<Vec<u8>> = None;
    let mut developer_mode = false;
    let mut request = CreateJobInput::default();

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|e| AppError::bad_request(e.to_string()))?
    {
        let name = field.name().unwrap_or_default().trim().to_string();
        if name.is_empty() {
            continue;
        }
        if name == "file" {
            let filename = field
                .file_name()
                .map(|s| s.to_string())
                .unwrap_or_else(|| "upload.pdf".to_string());
            let data = field
                .bytes()
                .await
                .map_err(|e| AppError::bad_request(e.to_string()))?;
            file_name = Some(filename);
            file_bytes = Some(data.to_vec());
            continue;
        }
        let value = field
            .text()
            .await
            .map_err(|e| AppError::bad_request(e.to_string()))?;
        apply_multipart_request_field(&mut request, &mut developer_mode, &name, value.trim())?;
    }

    Ok(ParsedOcrJob {
        filename: file_name,
        file_bytes,
        developer_mode,
        request,
    })
}
