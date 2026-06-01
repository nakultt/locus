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
}
