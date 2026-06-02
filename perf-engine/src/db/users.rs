use bson::{doc, oid::ObjectId};
use mongodb::{results::InsertOneResult, Collection};
use crate::error::AppError;
use crate::model::user::UserDoc;
use crate::db::Database;

impl Database {
    pub async fn create_user(&self, user: UserDoc) -> Result<InsertOneResult, AppError> {
        Ok(self.users.insert_one(user).await?)
    }

    pub async fn get_user_by_email(&self, email: &str) -> Result<Option<UserDoc>, AppError> {
        Ok(self.users.find_one(doc! { "email": email }).await?)
    }

    pub async fn get_user_by_id(&self, id: ObjectId) -> Result<Option<UserDoc>, AppError> {
        Ok(self.users.find_one(doc! { "_id": id }).await?)
    }

    pub async fn update_user(&self, id: ObjectId, email: Option<String>, name: Option<String>, password_hash: Option<String>) -> Result<mongodb::results::UpdateResult, AppError> {
        let mut update_doc = bson::Document::new();
        if let Some(e) = email {
            update_doc.insert("email", e);
        }
        if let Some(n) = name {
            update_doc.insert("name", n);
        }
        if let Some(p) = password_hash {
            update_doc.insert("password_hash", p);
        }
        
        Ok(self.users.update_one(
            doc! { "_id": id },
            doc! { "$set": update_doc }
        ).await?)
    }
}
