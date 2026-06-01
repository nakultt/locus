use mongodb::{Client, Collection};
use crate::config::AppConfig;
use crate::error::AppError;
use crate::model::user::UserDoc;
use crate::model::integration::IntegrationDoc;
use crate::model::conversation::{ConversationDoc, MessageDoc};

pub mod users;
pub mod integrations;
pub mod conversations;
pub mod settings;

#[derive(Clone)]
pub struct Database {
    pub users: Collection<UserDoc>,
    pub integrations: Collection<IntegrationDoc>,
    pub conversations: Collection<ConversationDoc>,
    pub messages: Collection<MessageDoc>,
    pub settings: Collection<crate::model::setting::SettingDoc>,
}

impl Database {
    pub async fn new(config: &AppConfig) -> Result<Self, AppError> {
        let client = Client::with_uri_str(&config.mongodb_uri).await?;
        let db = client.database(&config.mongodb_db);

        let users = db.collection::<UserDoc>("users");
        let integrations = db.collection::<IntegrationDoc>("integrations");
        let conversations = db.collection::<ConversationDoc>("conversations");
        let messages = db.collection::<MessageDoc>("messages");
        let settings = db.collection::<crate::model::setting::SettingDoc>("settings");

        Ok(Self {
            users,
            integrations,
            conversations,
            messages,
            settings,
        })
    }
}
