use serde_json::{json, Value};

pub(super) fn build_paddle_optional_payload(model: &str, max_input_images: u16) -> Value {
    let normalized = model.trim().to_ascii_lowercase();
    if normalized.contains("pp-structurev3") {
        return json!({
            "max_num_input_imgs": max_input_images,
            "markdownIgnoreLabels": [
                "header",
                "header_image",
                "footer",
                "footer_image",
                "number",
                "footnote",
                "aside_text"
            ],
            "useChartRecognition": false,
            "useRegionDetection": true,
            "useDocOrientationClassify": false,
            "useDocUnwarping": false,
            "useTextlineOrientation": false,
            "useSealRecognition": true,
            "useFormulaRecognition": true,
            "useTableRecognition": true,
            "layoutThreshold": 0.5,
            "layoutNms": true,
            "layoutUnclipRatio": 1,
            "textDetLimitType": "min",
            "textDetLimitSideLen": 64,
            "textDetThresh": 0.3,
            "textDetBoxThresh": 0.6,
            "textDetUnclipRatio": 1.5,
            "textRecScoreThresh": 0,
            "sealDetLimitType": "min",
            "sealDetLimitSideLen": 736,
            "sealDetThresh": 0.2,
            "sealDetBoxThresh": 0.6,
            "sealDetUnclipRatio": 0.5,
            "sealRecScoreThresh": 0,
            "useTableOrientationClassify": true,
            "useOcrResultsWithTableCells": true,
            "useE2eWiredTableRecModel": false,
            "useE2eWirelessTableRecModel": false,
            "useWiredTableCellsTransToHtml": false,
            "useWirelessTableCellsTransToHtml": false,
            "parseLanguage": "default",
            "visualize": false
        });
    }

    json!({
        "max_num_input_imgs": max_input_images,
        "mergeLayoutBlocks": false,
        "markdownIgnoreLabels": [
            "header",
            "header_image",
            "footer",
            "footer_image",
            "number",
            "footnote",
            "aside_text"
        ],
        "useDocOrientationClassify": false,
        "useDocUnwarping": false,
        "useLayoutDetection": true,
        "useChartRecognition": false,
        "useSealRecognition": true,
        "useOcrForImageBlock": false,
        "mergeTables": true,
        "relevelTitles": true,
        "layoutShapeMode": "auto",
        "promptLabel": "ocr",
        "repetitionPenalty": 1,
        "temperature": 0,
        "topP": 1,
        "minPixels": 147384,
        "maxPixels": 2822400,
        "layoutNms": true,
        "restructurePages": true,
        "visualize": false
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paddle_optional_payload_sets_page_limit() {
        let payload = build_paddle_optional_payload("PaddleOCR-VL-1.5", 888);
        assert_eq!(payload["max_num_input_imgs"], 888);

        let structure_payload = build_paddle_optional_payload("PP-StructureV3", 777);
        assert_eq!(structure_payload["max_num_input_imgs"], 777);
    }
}
