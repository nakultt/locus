use axum::{
    extract::{Path, State},
    Json,
};
use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

use crate::error::AppError;
use crate::state::SharedState;

#[derive(Deserialize)]
pub struct UpdateSettingsRequest {
    pub gemini_key: String,
}

#[derive(Serialize)]
pub struct SettingsResponse {
    pub has_gemini_key: bool,
}

#[derive(Serialize)]
pub struct GeminiKeyResponse {
    pub key: String,
}

pub async fn update_settings(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
    Json(payload): Json<UpdateSettingsRequest>,
) -> Result<Json<()>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    
    let encrypted = state.crypto.encrypt(&payload.gemini_key)?;
    state.db.update_gemini_key(user_id, &encrypted).await?;

    Ok(Json(()))
}

pub async fn get_settings(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
) -> Result<Json<SettingsResponse>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;

    let doc = state.db.get_settings(user_id).await?;
    let has_key = doc.and_then(|d| d.gemini_key_encrypted).is_some();

    Ok(Json(SettingsResponse {
        has_gemini_key: has_key,
    }))
}

// Internal route for gateway to fetch the decrypted key
pub async fn get_gemini_key(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
) -> Result<Json<GeminiKeyResponse>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;

    let doc = state.db.get_settings(user_id).await?.ok_or_else(|| AppError::Internal("Settings not found".into()))?;
    let encrypted = doc.gemini_key_encrypted.ok_or_else(|| AppError::Internal("Gemini key not set".into()))?;
    
    let decrypted = state.crypto.decrypt(&encrypted)?;

    Ok(Json(GeminiKeyResponse {
        key: decrypted,
    }))
}
