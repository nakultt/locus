use bson::{doc, oid::ObjectId};
use mongodb::results::UpdateResult;
use crate::error::AppError;
use crate::model::setting::SettingDoc;
use crate::db::Database;
use mongodb::options::UpdateOptions;

impl Database {
    pub async fn get_settings(&self, user_id: ObjectId) -> Result<Option<SettingDoc>, AppError> {
        Ok(self.settings.find_one(doc! { "user_id": user_id }).await?)
    }

    pub async fn update_gemini_key(&self, user_id: ObjectId, encrypted_key: &str) -> Result<UpdateResult, AppError> {
        let update = doc! {
            "$set": {
                "gemini_key_encrypted": encrypted_key,
                "updated_at": chrono::Utc::now().to_rfc3339()
            }
        };
        let options = UpdateOptions::builder().upsert(true).build();
        Ok(self.settings.update_one(doc! { "user_id": user_id }, update).with_options(options).await?)
    }
}
