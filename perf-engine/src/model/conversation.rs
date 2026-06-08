use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ConversationDoc {
    #[serde(rename = "_id", skip_serializing_if = "Option::is_none")]
    pub id: Option<ObjectId>,
    pub user_id: ObjectId,
    pub title: String,
    #[serde(with = "crate::model::flexible_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(with = "crate::model::flexible_datetime")]
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MessageDoc {
    #[serde(rename = "_id", skip_serializing_if = "Option::is_none")]
    pub id: Option<ObjectId>,
    pub conversation_id: ObjectId,
    pub role: String,
    pub content: String,
    pub tools_used: Option<Vec<String>>,
    #[serde(with = "crate::model::flexible_datetime")]
    pub created_at: DateTime<Utc>,
}
