use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct IntegrationDoc {
    #[serde(rename = "_id", skip_serializing_if = "Option::is_none")]
    pub id: Option<ObjectId>,
    pub user_id: ObjectId,
    pub provider: String,
    pub credentials_encrypted: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
