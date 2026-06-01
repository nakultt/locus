use axum::{
    extract::{Path, Query, State},
    Json,
};
use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

use crate::error::AppError;
use crate::model::conversation::{ConversationDoc, MessageDoc};
use crate::state::SharedState;

#[derive(Deserialize)]
pub struct PaginationQuery {
    pub limit: Option<i64>,
    pub skip: Option<u64>,
}

#[derive(Deserialize)]
pub struct CreateConversationRequest {
    pub title: String,
}

#[derive(Serialize)]
pub struct ConversationResponse {
    pub id: String,
    pub title: String,
    pub created_at: String,
}

#[derive(Deserialize)]
pub struct AddMessageRequest {
    pub role: String,
    pub content: String,
    pub tools_used: Option<Vec<String>>,
}

#[derive(Serialize)]
pub struct MessageResponse {
    pub id: String,
    pub role: String,
    pub content: String,
    pub tools_used: Option<Vec<String>>,
    pub created_at: String,
}

pub async fn create_conversation(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
    Json(payload): Json<CreateConversationRequest>,
) -> Result<Json<ConversationResponse>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;

    let doc = ConversationDoc {
        id: None,
        user_id,
        title: payload.title.clone(),
        created_at: chrono::Utc::now(),
        updated_at: chrono::Utc::now(),
    };

    let result = state.db.create_conversation(doc.clone()).await?;
    let id_str = result.inserted_id.as_object_id().unwrap().to_hex();

    Ok(Json(ConversationResponse {
        id: id_str,
        title: doc.title,
        created_at: doc.created_at.to_rfc3339(),
    }))
}

pub async fn list_conversations(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
    Query(query): Query<PaginationQuery>,
) -> Result<Json<Vec<ConversationResponse>>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    
    let limit = query.limit.unwrap_or(20);
    let skip = query.skip.unwrap_or(0);

    let docs = state.db.get_conversations_by_user(user_id, limit, skip).await?;
    
    let res = docs.into_iter().map(|d| ConversationResponse {
        id: d.id.unwrap().to_hex(),
        title: d.title,
        created_at: d.created_at.to_rfc3339(),
    }).collect();

    Ok(Json(res))
}

pub async fn delete_conversation(
    State(state): State<SharedState>,
    Path((user_id_str, id_str)): Path<(String, String)>,
) -> Result<Json<()>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid id".into()))?;

    state.db.delete_conversation(id, user_id).await?;
    
    Ok(Json(()))
}

pub async fn add_message(
    State(state): State<SharedState>,
    Path((user_id_str, id_str)): Path<(String, String)>,
    Json(payload): Json<AddMessageRequest>,
) -> Result<Json<MessageResponse>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid id".into()))?;

    // verify conversation belongs to user
    state.db.get_conversation(id, user_id).await?.ok_or_else(|| AppError::Internal("Conversation not found".into()))?;

    let doc = MessageDoc {
        id: None,
        conversation_id: id,
        role: payload.role.clone(),
        content: payload.content.clone(),
        tools_used: payload.tools_used.clone(),
        created_at: chrono::Utc::now(),
    };

    let result = state.db.add_message(doc.clone()).await?;
    let msg_id = result.inserted_id.as_object_id().unwrap().to_hex();

    Ok(Json(MessageResponse {
        id: msg_id,
        role: doc.role,
        content: doc.content,
        tools_used: doc.tools_used,
        created_at: doc.created_at.to_rfc3339(),
    }))
}

pub async fn list_messages(
    State(state): State<SharedState>,
    Path((user_id_str, id_str)): Path<(String, String)>,
    Query(query): Query<PaginationQuery>,
) -> Result<Json<Vec<MessageResponse>>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid id".into()))?;

    // verify conversation belongs to user
    state.db.get_conversation(id, user_id).await?.ok_or_else(|| AppError::Internal("Conversation not found".into()))?;

    let limit = query.limit.unwrap_or(50);
    let skip = query.skip.unwrap_or(0);

    let docs = state.db.get_messages(id, limit, skip).await?;
    
    let res = docs.into_iter().map(|d| MessageResponse {
        id: d.id.unwrap().to_hex(),
        role: d.role,
        content: d.content,
        tools_used: d.tools_used,
        created_at: d.created_at.to_rfc3339(),
    }).collect();

    Ok(Json(res))
}
