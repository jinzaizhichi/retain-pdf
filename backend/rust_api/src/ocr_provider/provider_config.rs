use std::env;
use std::fs;
use std::path::PathBuf;

use serde_json::Value;

const OCR_PROVIDER_CONFIG_ENV: &str = "RUST_API_OCR_PROVIDER_CONFIG";
const OCR_PROVIDER_CONFIG_COMPAT_ENV: &str = "RETAIN_OCR_PROVIDER_CONFIG";
const PADDLE_DEFAULT_MODEL_ENV: &str = "RUST_API_PADDLE_DEFAULT_MODEL";
const PADDLE_DEFAULT_MODEL_COMPAT_ENV: &str = "RETAIN_PADDLE_DEFAULT_MODEL";
const PADDLE_DEFAULT_MODEL_FALLBACK: &str = "PaddleOCR-VL-1.6";

pub fn paddle_default_model() -> String {
    env_override(PADDLE_DEFAULT_MODEL_ENV)
        .or_else(|| env_override(PADDLE_DEFAULT_MODEL_COMPAT_ENV))
        .or_else(|| {
            paddle_config()
                .get("default_model")
                .and_then(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(ToString::to_string)
        })
        .unwrap_or_else(|| PADDLE_DEFAULT_MODEL_FALLBACK.to_string())
}

pub fn normalize_paddle_model_name(model: &str) -> String {
    let trimmed = model.trim();
    if trimmed.is_empty() {
        return paddle_default_model();
    }
    let lowered = trimmed.to_ascii_lowercase();
    paddle_config()
        .get("model_aliases")
        .and_then(Value::as_object)
        .and_then(|aliases| aliases.get(&lowered))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .unwrap_or_else(|| trimmed.to_string())
}

fn paddle_config() -> Value {
    ocr_provider_config()
        .get("paddle")
        .cloned()
        .unwrap_or(Value::Null)
}

fn ocr_provider_config() -> Value {
    let Some(path) = config_path() else {
        return Value::Null;
    };
    let Ok(text) = fs::read_to_string(path) else {
        return Value::Null;
    };
    serde_json::from_str(&text).unwrap_or(Value::Null)
}

fn config_path() -> Option<PathBuf> {
    env_override(OCR_PROVIDER_CONFIG_ENV)
        .or_else(|| env_override(OCR_PROVIDER_CONFIG_COMPAT_ENV))
        .map(PathBuf::from)
        .or_else(|| {
            let rust_api_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            rust_api_root
                .parent()
                .map(|backend_root| backend_root.join("config").join("ocr_providers.json"))
        })
}

fn env_override(name: &str) -> Option<String> {
    env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paddle_default_model_reads_shared_config() {
        assert_eq!(paddle_default_model(), "PaddleOCR-VL-1.6");
    }

    #[test]
    fn normalize_paddle_model_name_uses_shared_aliases() {
        assert_eq!(normalize_paddle_model_name(""), "PaddleOCR-VL-1.6");
        assert_eq!(
            normalize_paddle_model_name("paddleocr-vl"),
            "PaddleOCR-VL-1.6"
        );
        assert_eq!(
            normalize_paddle_model_name("paddleocr-vl-1.5"),
            "PaddleOCR-VL-1.5"
        );
    }
}
