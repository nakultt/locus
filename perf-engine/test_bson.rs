use bson::{doc, oid::ObjectId};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize)]
pub struct SettingDoc {
    pub user_id: ObjectId,
    pub updated_at: DateTime<Utc>,
}

fn main() {
    let doc = doc! {
        "user_id": ObjectId::new(),
        "updated_at": bson::DateTime::from(chrono::Utc::now())
    };

    println!("Doc: {:?}", doc);

    match bson::from_document::<SettingDoc>(doc) {
        Ok(d) => println!("Success: {:?}", d),
        Err(e) => println!("Error: {}", e),
    }
}
