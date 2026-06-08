use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UserDoc {
    #[serde(rename = "_id", skip_serializing_if = "Option::is_none")]
    pub id: Option<ObjectId>,
    pub email: String,
    pub name: String,
    pub password_hash: String,
    #[serde(with = "crate::model::flexible_datetime")]
    pub created_at: DateTime<Utc>,
    #[serde(with = "crate::model::flexible_datetime")]
    pub updated_at: DateTime<Utc>,
}

impl Default for UserDoc {
    fn default() -> Self {
        let now = Utc::now();
        Self {
            id: None,
            email: String::new(),
            name: String::new(),
            password_hash: String::new(),
            created_at: now,
            updated_at: now,
        }
    }
}
