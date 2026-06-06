use serde_json::Value;

use crate::error::AppError;
use crate::models::{CreateJobInput, ResolvedJobSpec};

pub(super) fn apply_retry_overrides(
    input: &mut CreateJobInput,
    overrides: &Value,
) -> Result<(), AppError> {
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

pub(super) fn apply_retry_overrides_to_resolved_spec(
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
