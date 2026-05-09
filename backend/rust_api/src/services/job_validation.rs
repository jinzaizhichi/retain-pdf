use crate::error::AppError;
use crate::models::{CreateJobInput, OcrProviderKind, UploadRecord};
use crate::ocr_provider::{
    parse_provider_kind, provider_display_name, provider_token, provider_token_field_name,
    require_supported_provider,
};

const MINERU_MAX_BYTES: u64 = 200 * 1024 * 1024;
const MINERU_MAX_PAGES: u32 = 600;
const PADDLE_MAX_BYTES: u64 = 100 * 1024 * 1024;
const PADDLE_MAX_PAGES: u32 = 300;

pub fn validate_provider_credentials(input: &CreateJobInput) -> Result<(), AppError> {
    let provider_kind = require_supported_provider(input.ocr.provider.trim())
        .map_err(|err| AppError::bad_request(err.to_string()))?;
    validate_provider_token(input, &provider_kind)?;
    validate_translation_credentials(input)
}

pub fn validate_translation_credentials(input: &CreateJobInput) -> Result<(), AppError> {
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
    let provider_kind = require_supported_provider(provider)
        .map_err(|err| AppError::bad_request(err.to_string()))?;
    validate_provider_token(input, &provider_kind)?;
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
    match parse_provider_kind(&input.ocr.provider) {
        OcrProviderKind::Mineru => {
            validate_upload_limit(upload, "MinerU", MINERU_MAX_BYTES, MINERU_MAX_PAGES, false)?;
        }
        OcrProviderKind::Paddle => {
            validate_upload_limit(
                upload,
                "PaddleOCR",
                PADDLE_MAX_BYTES,
                PADDLE_MAX_PAGES,
                true,
            )?;
        }
        OcrProviderKind::Unknown => {}
    }
    Ok(())
}

fn validate_upload_limit(
    upload: &UploadRecord,
    provider_name: &str,
    max_bytes: u64,
    max_pages: u32,
    bytes_inclusive: bool,
) -> Result<(), AppError> {
    let too_large = if bytes_inclusive {
        upload.bytes > max_bytes
    } else {
        upload.bytes >= max_bytes
    };
    if too_large {
        let relation = if bytes_inclusive {
            "不超过"
        } else {
            "小于"
        };
        return Err(AppError::bad_request(format!(
            "{provider_name} API 限制：PDF 文件大小必须{relation} {:.0}MB；当前文件为 {:.2}MB",
            max_bytes as f64 / 1024.0 / 1024.0,
            upload.bytes as f64 / 1024.0 / 1024.0
        )));
    }
    if upload.page_count > max_pages {
        return Err(AppError::bad_request(format!(
            "{provider_name} API 限制：PDF 页数必须不超过 {max_pages} 页；当前文件为 {} 页",
            upload.page_count
        )));
    }
    Ok(())
}

fn looks_like_url(value: &str) -> bool {
    let value = value.trim().to_ascii_lowercase();
    value.starts_with("http://") || value.starts_with("https://")
}

fn validate_provider_token(
    input: &CreateJobInput,
    provider_kind: &OcrProviderKind,
) -> Result<(), AppError> {
    let token = provider_token(provider_kind, &input.ocr);
    let field_name = provider_token_field_name(provider_kind).unwrap_or("provider_token");
    let display_name = provider_display_name(provider_kind).unwrap_or("Provider");
    if token.is_empty() {
        return Err(AppError::bad_request(format!("{field_name} is required")));
    }
    if looks_like_url(token) {
        return Err(AppError::bad_request(format!(
            "{field_name} looks like a URL, not a {display_name} API key; check whether frontend fields were mixed up",
        )));
    }
    Ok(())
}
