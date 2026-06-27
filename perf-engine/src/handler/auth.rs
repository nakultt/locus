use axum::{extract::{Path, State}, Json};
use bson::oid::ObjectId;
use std::str::FromStr;
use serde::{Deserialize, Serialize};

use crate::error::AppError;
use crate::model::user::UserDoc;
use crate::state::SharedState;

#[derive(Deserialize)]
pub struct RegisterRequest {
    pub email: String,
    pub name: String,
    pub password: String,
}

#[derive(Deserialize)]
pub struct LoginRequest {
    pub email: String,
    pub password: String,
}

#[derive(Serialize)]
pub struct AuthResponse {
    pub id: String,
    pub email: String,
    pub name: String,
    pub token: String,
}

#[tracing::instrument(skip(state, payload))]
pub async fn register(
    State(state): State<SharedState>,
    Json(payload): Json<RegisterRequest>,
) -> Result<Json<AuthResponse>, AppError> {
    if state.db.get_user_by_email(&payload.email).await?.is_some() {
        return Err(AppError::BadRequest("User already exists".to_string()));
    }

    let password_hash = state.crypto.hash_password(&payload.password)?;

    let user_doc = UserDoc {
        email: payload.email.clone(),
        name: payload.name.clone(),
        password_hash,
        ..Default::default()
    };

    let result = state.db.create_user(user_doc).await?;
    let id_str = result.inserted_id.as_object_id().unwrap().to_hex();
    let token = state.crypto.create_jwt(&id_str, &payload.email)?;

    Ok(Json(AuthResponse {
        id: id_str,
        email: payload.email,
        name: payload.name,
        token,
    }))
}

#[derive(Deserialize)]
pub struct GoogleLoginRequest {
    pub email: String,
    pub name: String,
}

#[tracing::instrument(skip(state, payload))]
pub async fn google_login(
    State(state): State<SharedState>,
    Json(payload): Json<GoogleLoginRequest>,
) -> Result<Json<AuthResponse>, AppError> {
    let user_opt = state.db.get_user_by_email(&payload.email).await?;
    
    let user = match user_opt {
        Some(u) => u,
        None => {
            let user_doc = UserDoc {
                email: payload.email.clone(),
                name: payload.name.clone(),
                password_hash: String::new(), // Google users don't have a password
                ..Default::default()
            };
            let result = state.db.create_user(user_doc.clone()).await?;
            let id = result.inserted_id.as_object_id().unwrap();
            let mut u = user_doc;
            u.id = Some(id);
            u
        }
    };
    
    let id_str = user.id.unwrap().to_hex();
    let token = state.crypto.create_jwt(&id_str, &user.email)?;

    Ok(Json(AuthResponse {
        id: id_str,
        email: user.email,
        name: user.name,
        token,
    }))
}

#[tracing::instrument(skip(state, payload))]
pub async fn login(
    State(state): State<SharedState>,
    Json(payload): Json<LoginRequest>,
) -> Result<Json<AuthResponse>, AppError> {
    let user = state
        .db
        .get_user_by_email(&payload.email)
        .await?
        .ok_or(AppError::InvalidCredentials)?;

    if !state
        .crypto
        .verify_password(&payload.password, &user.password_hash)?
    {
        return Err(AppError::InvalidCredentials);
    }

    let id_str = user.id.unwrap().to_hex();
    let token = state.crypto.create_jwt(&id_str, &user.email)?;

    Ok(Json(AuthResponse {
        id: id_str,
        email: user.email,
        name: user.name,
        token,
    }))
}

#[derive(Deserialize)]
pub struct UpdateUserRequest {
    pub email: Option<String>,
    pub password: Option<String>,
    pub name: Option<String>,
}

#[tracing::instrument(skip(state, payload))]
pub async fn update_user(
    State(state): State<SharedState>,
    Path(id_str): Path<String>,
    Json(payload): Json<UpdateUserRequest>,
) -> Result<Json<AuthResponse>, AppError> {
    let user_id = ObjectId::from_str(&id_str).map_err(|_| AppError::Internal("Invalid user_id".into()))?;
    
    let mut password_hash = None;
    if let Some(ref pwd) = payload.password {
        password_hash = Some(state.crypto.hash_password(pwd)?);
    }
    
    state.db.update_user(user_id, payload.email, payload.name, password_hash).await?;
    
    let user = state.db.get_user_by_id(user_id).await?.ok_or_else(|| AppError::Internal("User not found".into()))?;
    let token = state.crypto.create_jwt(&id_str, &user.email)?;
    
    Ok(Json(AuthResponse {
        id: id_str,
        email: user.email,
        name: user.name,
        token,
    }))
}
