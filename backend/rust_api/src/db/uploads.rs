use std::path::Path;

use anyhow::{Context, Result};
use rusqlite::params;

use crate::models::UploadRecord;
use crate::storage_paths::{resolve_data_path, to_relative_data_path};

use super::Db;

impl Db {
    pub fn save_upload(&self, upload: &UploadRecord) -> Result<()> {
        let stored_path = to_relative_data_path(&self.data_root, Path::new(&upload.stored_path))?;
        let conn = self.connect()?;
        conn.execute(
            r#"
            INSERT INTO uploads (
                upload_id, filename, stored_path, bytes, page_count, uploaded_at, developer_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(upload_id) DO UPDATE SET
                filename=excluded.filename,
                stored_path=excluded.stored_path,
                bytes=excluded.bytes,
                page_count=excluded.page_count,
                uploaded_at=excluded.uploaded_at,
                developer_mode=excluded.developer_mode
            "#,
            params![
                upload.upload_id,
                upload.filename,
                stored_path,
                upload.bytes as i64,
                upload.page_count as i64,
                upload.uploaded_at,
                if upload.developer_mode { 1 } else { 0 },
            ],
        )?;
        Ok(())
    }

    pub fn get_upload(&self, upload_id: &str) -> Result<UploadRecord> {
        let conn = self.connect()?;
        let upload = conn
            .query_row(
                "SELECT upload_id, filename, stored_path, bytes, page_count, uploaded_at, developer_mode FROM uploads WHERE upload_id = ?1",
                params![upload_id],
                |row| {
                    Ok(UploadRecord {
                        upload_id: row.get(0)?,
                        filename: row.get(1)?,
                        stored_path: row.get(2)?,
                        bytes: row.get::<_, i64>(3)? as u64,
                        page_count: row.get::<_, i64>(4)? as u32,
                        uploaded_at: row.get(5)?,
                        developer_mode: row.get::<_, i64>(6)? != 0,
                    })
                },
            )
            .with_context(|| format!("upload not found: {upload_id}"))?;
        Ok(UploadRecord {
            stored_path: resolve_data_path(&self.data_root, &upload.stored_path)?
                .to_string_lossy()
                .to_string(),
            ..upload
        })
    }
}
