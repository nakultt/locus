use axum::{extract::State, Json};
use serde_json::{json, Value};
use crate::state::SharedState;
use crate::error::AppError;

pub async fn health_check(State(state): State<SharedState>) -> Result<Json<Value>, AppError> {
    // Optionally ping the database here to check DB health.
    // For now we just return OK.
    Ok(Json(json!({ "status": "ok" })))
}
