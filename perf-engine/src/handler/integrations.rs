use axum::{
    extract::{Path, State},
    Json,
};
use bson::oid::ObjectId;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

use crate::error::AppError;
use crate::model::integration::IntegrationDoc;
use crate::state::SharedState;

#[derive(Deserialize)]
pub struct CreateIntegrationRequest {
    pub user_id: String,
    pub provider: String,
    pub credentials_json: String, // unencrypted JSON of credentials
}

#[derive(Serialize)]
pub struct IntegrationResponse {
    pub id: String,
    pub provider: String,
}

#[derive(Serialize)]
pub struct IntegrationDetailResponse {
    pub id: String,
    pub provider: String,
    pub credentials_json: String, // decrypted JSON
}

pub async fn create_integration(
    State(state): State<SharedState>,
    Json(payload): Json<CreateIntegrationRequest>,
) -> Result<Json<IntegrationResponse>, AppError> {
    let user_id = ObjectId::from_str(&payload.user_id).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let encrypted_creds = state.crypto.encrypt(&payload.credentials_json)?;

    let mut doc = IntegrationDoc {
        id: None,
        user_id,
        provider: payload.provider.clone(),
        credentials_encrypted: encrypted_creds,
        created_at: chrono::Utc::now(),
        updated_at: chrono::Utc::now(),
    };

    if let Some(existing) = state.db.get_integration_by_provider(user_id, &payload.provider).await? {
        state.db.update_integration(existing.id.unwrap(), user_id, &doc.credentials_encrypted).await?;
        return Ok(Json(IntegrationResponse {
            id: existing.id.unwrap().to_hex(),
            provider: payload.provider,
        }));
    }

    let result = state.db.create_integration(doc).await?;
    let id_str = result.inserted_id.as_object_id().unwrap().to_hex();

    Ok(Json(IntegrationResponse {
        id: id_str,
        provider: payload.provider,
    }))
}

pub async fn list_integrations(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
) -> Result<Json<Vec<IntegrationResponse>>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let docs = state.db.get_integrations_by_user(user_id).await?;
    
    let res = docs.into_iter().map(|d| IntegrationResponse {
        id: d.id.unwrap().to_hex(),
        provider: d.provider,
    }).collect();

    Ok(Json(res))
}

pub async fn get_all_integration_credentials(
    State(state): State<SharedState>,
    Path(user_id_str): Path<String>,
) -> Result<Json<serde_json::Value>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let docs = state.db.get_integrations_by_user(user_id).await?;
    
    let mut configs = serde_json::Map::new();
    for doc in docs {
        if let Ok(decrypted) = state.crypto.decrypt(&doc.credentials_encrypted) {
            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(&decrypted) {
                configs.insert(doc.provider, parsed);
            }
        }
    }

    Ok(Json(serde_json::Value::Object(configs)))
}

pub async fn get_integration(
    State(state): State<SharedState>,
    Path((user_id_str, id_str)): Path<(String, String)>,
) -> Result<Json<IntegrationDetailResponse>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid id".into()))?;

    let doc = state.db.get_integration(id, user_id).await?.ok_or_else(|| AppError::Internal("Integration not found".into()))?;
    let decrypted = state.crypto.decrypt(&doc.credentials_encrypted)?;

    Ok(Json(IntegrationDetailResponse {
        id: doc.id.unwrap().to_hex(),
        provider: doc.provider,
        credentials_json: decrypted,
    }))
}

pub async fn delete_integration(
    State(state): State<SharedState>,
    Path((user_id_str, id_str)): Path<(String, String)>,
) -> Result<Json<()>, AppError> {
    let user_id = ObjectId::from_str(&user_id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    let id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid id".into()))?;

    state.db.delete_integration(id, user_id).await?;
    
    Ok(Json(()))
}
