use bson::{doc, oid::ObjectId};
use mongodb::results::{DeleteResult, InsertOneResult, UpdateResult};
use crate::error::AppError;
use crate::model::integration::IntegrationDoc;
use crate::db::Database;
use futures::stream::TryStreamExt;

impl Database {
    pub async fn create_integration(&self, integration: IntegrationDoc) -> Result<InsertOneResult, AppError> {
        Ok(self.integrations.insert_one(integration).await?)
    }

    pub async fn get_integrations_by_user(&self, user_id: ObjectId) -> Result<Vec<IntegrationDoc>, AppError> {
        let mut cursor = self.integrations.find(doc! { "user_id": user_id }).await?;
        let mut docs = Vec::new();
        while let Some(doc) = cursor.try_next().await? {
            docs.push(doc);
        }
        Ok(docs)
    }

    pub async fn get_integration(&self, id: ObjectId, user_id: ObjectId) -> Result<Option<IntegrationDoc>, AppError> {
        Ok(self.integrations.find_one(doc! { "_id": id, "user_id": user_id }).await?)
    }

    pub async fn get_integration_by_provider(&self, user_id: ObjectId, provider: &str) -> Result<Option<IntegrationDoc>, AppError> {
        Ok(self.integrations.find_one(doc! { "user_id": user_id, "provider": provider }).await?)
    }

    pub async fn update_integration(&self, id: ObjectId, user_id: ObjectId, encrypted_creds: &str) -> Result<UpdateResult, AppError> {
        let update = doc! {
            "$set": {
                "credentials_encrypted": encrypted_creds,
                "updated_at": chrono::Utc::now().to_rfc3339()
            }
        };
        Ok(self.integrations.update_one(doc! { "_id": id, "user_id": user_id }, update).await?)
    }

    pub async fn delete_integration(&self, id: ObjectId, user_id: ObjectId) -> Result<DeleteResult, AppError> {
        Ok(self.integrations.delete_one(doc! { "_id": id, "user_id": user_id }).await?)
    }
}
