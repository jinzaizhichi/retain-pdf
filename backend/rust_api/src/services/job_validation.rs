use crate::error::AppError;
use crate::models::{CreateJobInput, UploadRecord};
use crate::ocr_provider::require_supported_provider;

const MINERU_MAX_BYTES: u64 = 200 * 1024 * 1024;
const MINERU_MAX_PAGES: u32 = 600;

pub fn validate_provider_credentials(input: &CreateJobInput) -> Result<(), AppError> {
    match input.ocr.provider.trim().to_ascii_lowercase().as_str() {
        "paddle" => {
            let paddle_token = input.ocr.paddle_token.trim();
            if paddle_token.is_empty() {
                return Err(AppError::bad_request("paddle_token is required"));
            }
            if looks_like_url(paddle_token) {
                return Err(AppError::bad_request(
                    "paddle_token looks like a URL, not a Paddle API key; check whether frontend fields were mixed up",
                ));
            }
        }
        _ => {
            let mineru_token = input.ocr.mineru_token.trim();
            if mineru_token.is_empty() {
                return Err(AppError::bad_request("mineru_token is required"));
            }
            if looks_like_url(mineru_token) {
                return Err(AppError::bad_request(
                    "mineru_token looks like a URL, not a MinerU API key; check whether frontend fields were mixed up",
                ));
            }
        }
    }

    let base_url = input.translation.base_url.trim();
    if base_url.is_empty() {
        return Err(AppError::bad_request("base_url is required"));
    }
    if !(base_url.starts_with("http://") || base_url.starts_with("https://")) {
        return Err(AppError::bad_request(
            "base_url must start with http:// or https://",
        ));
    }

    let api_key = input.translation.api_key.trim();
    if api_key.is_empty() {
        return Err(AppError::bad_request("api_key is required"));
    }
    if looks_like_url(api_key) {
        return Err(AppError::bad_request(
            "api_key looks like a URL, not a model API key; check whether frontend fields were mixed up",
        ));
    }
    if input.translation.model.trim().is_empty() {
        return Err(AppError::bad_request("model is required"));
    }
    Ok(())
}

pub fn validate_ocr_provider_request(input: &CreateJobInput) -> Result<(), AppError> {
    let provider = input.ocr.provider.trim();
    if provider.is_empty() {
        return Err(AppError::bad_request("provider is required"));
    }
    if let Err(err) = require_supported_provider(provider) {
        return Err(AppError::bad_request(err.to_string()));
    }
    match provider.to_ascii_lowercase().as_str() {
        "mineru" => {
            let mineru_token = input.ocr.mineru_token.trim();
            if mineru_token.is_empty() {
                return Err(AppError::bad_request("mineru_token is required"));
            }
            if looks_like_url(mineru_token) {
                return Err(AppError::bad_request(
                    "mineru_token looks like a URL, not a MinerU API key; check whether frontend fields were mixed up",
                ));
            }
        }
        "paddle" => {
            let paddle_token = input.ocr.paddle_token.trim();
            if paddle_token.is_empty() {
                return Err(AppError::bad_request("paddle_token is required"));
            }
            if looks_like_url(paddle_token) {
                return Err(AppError::bad_request(
                    "paddle_token looks like a URL, not a Paddle API key; check whether frontend fields were mixed up",
                ));
            }
        }
        _ => {}
    }
    if !input.source.source_url.trim().is_empty()
        && !(input.source.source_url.starts_with("http://")
            || input.source.source_url.starts_with("https://"))
    {
        return Err(AppError::bad_request(
            "source_url must start with http:// or https://",
        ));
    }
    if input.runtime.timeout_seconds <= 0 {
        return Err(AppError::bad_request(
            "timeout_seconds must be a positive integer",
        ));
    }
    Ok(())
}

pub fn validate_mineru_upload_limits(
    input: &CreateJobInput,
    upload: &UploadRecord,
) -> Result<(), AppError> {
    if !request_uses_mineru(input) {
        return Ok(());
    }
    if upload.bytes >= MINERU_MAX_BYTES {
        return Err(AppError::bad_request(format!(
            "MinerU API 限制：PDF 文件大小必须小于 200MB；当前文件为 {:.2}MB",
            upload.bytes as f64 / 1024.0 / 1024.0
        )));
    }
    if upload.page_count > MINERU_MAX_PAGES {
        return Err(AppError::bad_request(format!(
            "MinerU API 限制：PDF 页数必须不超过 600 页；当前文件为 {} 页",
            upload.page_count
        )));
    }
    Ok(())
}

fn request_uses_mineru(input: &CreateJobInput) -> bool {
    matches!(input.workflow, crate::models::WorkflowKind::Book)
        || input.ocr.provider.trim().eq_ignore_ascii_case("mineru")
}

fn looks_like_url(value: &str) -> bool {
    let value = value.trim().to_ascii_lowercase();
    value.starts_with("http://") || value.starts_with("https://")
}
