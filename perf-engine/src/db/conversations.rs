use bson::{doc, oid::ObjectId};
use mongodb::results::{DeleteResult, InsertOneResult};
use crate::error::AppError;
use crate::model::conversation::{ConversationDoc, MessageDoc};
use crate::db::Database;
use futures::stream::TryStreamExt;
use mongodb::options::FindOptions;

impl Database {
    pub async fn create_conversation(&self, conv: ConversationDoc) -> Result<InsertOneResult, AppError> {
        Ok(self.conversations.insert_one(conv).await?)
    }

    pub async fn get_conversations_by_user(&self, user_id: ObjectId, limit: i64, skip: u64) -> Result<Vec<ConversationDoc>, AppError> {
        let find_options = FindOptions::builder()
            .sort(doc! { "updated_at": -1 })
            .limit(limit)
            .skip(skip)
            .build();
            
        let mut cursor = self.conversations.find(doc! { "user_id": user_id }).with_options(find_options).await?;
        let mut docs = Vec::new();
        while let Some(doc) = cursor.try_next().await? {
            docs.push(doc);
        }
        Ok(docs)
    }

    pub async fn get_conversation(&self, id: ObjectId, user_id: ObjectId) -> Result<Option<ConversationDoc>, AppError> {
        Ok(self.conversations.find_one(doc! { "_id": id, "user_id": user_id }).await?)
    }

    pub async fn update_conversation_title(&self, id: ObjectId, user_id: ObjectId, title: String) -> Result<mongodb::results::UpdateResult, AppError> {
        Ok(self.conversations.update_one(
            doc! { "_id": id, "user_id": user_id },
            doc! { "$set": { "title": title, "updated_at": chrono::Utc::now().to_rfc3339() } }
        ).await?)
    }

    pub async fn delete_conversation(&self, id: ObjectId, user_id: ObjectId) -> Result<DeleteResult, AppError> {
        // also delete messages
        self.messages.delete_many(doc! { "conversation_id": id }).await?;
        Ok(self.conversations.delete_one(doc! { "_id": id, "user_id": user_id }).await?)
    }

    pub async fn add_message(&self, message: MessageDoc) -> Result<InsertOneResult, AppError> {
        let conv_id = message.conversation_id;
        let res = self.messages.insert_one(message).await?;
        
        // update conversation updated_at
        self.conversations.update_one(
            doc! { "_id": conv_id },
            doc! { "$set": { "updated_at": chrono::Utc::now().to_rfc3339() } }
        ).await?;
        
        Ok(res)
    }

    pub async fn get_messages(&self, conversation_id: ObjectId, limit: i64, skip: u64) -> Result<Vec<MessageDoc>, AppError> {
        let find_options = FindOptions::builder()
            .sort(doc! { "created_at": 1 })
            .limit(limit)
            .skip(skip)
            .build();
            
        let mut cursor = self.messages.find(doc! { "conversation_id": conversation_id }).with_options(find_options).await?;
        let mut docs = Vec::new();
        while let Some(doc) = cursor.try_next().await? {
            docs.push(doc);
        }
        Ok(docs)
    }
}
