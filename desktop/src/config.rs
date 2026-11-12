use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::PathBuf;

#[derive(Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ProviderProfile {
    model: String,
    api_key: String,
    base_url: String,
    #[serde(skip)]
    balance_key: String,
}

pub const PROVIDERS: [(&str, &str); 4] = [
    ("openrouter", "OpenRouter"),
    ("kilo", "Kilo Gateway"),
    ("openai", "OpenAI"),
    ("custom", "OpenAI-compatible address"),
];
pub const VOICES: [(&str, &str); 5] = [
    ("albina", "Albina · female"),
    ("alfia", "Alfia · female"),
    ("roman", "Roman · male"),
    ("eduard", "Eduard · male"),
    ("alexandr", "Alexander · male"),
];
pub const LANGUAGES: [(&str, &str); 4] = [
    ("en", "English"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("ja", "Japanese"),
];

#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub provider: String,
    pub model: String,
    pub api_key: String,
    pub base_url: String,
    #[serde(skip)]
    pub balance_key: String,
    pub voice: String,
    pub language: String,
    pub voice_volume: f32,
    pub original_volume: f32,
    pub duck_original: bool,
    pub speaker_gender: String,
    pub match_voice: bool,
    pub female_voice: Option<String>,
    pub male_voice: Option<String>,
    pub captions: bool,
    pub profiles: BTreeMap<String, ProviderProfile>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            provider: "openrouter".into(),
            model: String::new(),
            api_key: String::new(),
            base_url: String::new(),
            balance_key: String::new(),
            voice: "albina".into(),
            language: "en".into(),
            voice_volume: 0.9,
            original_volume: 0.55,
            duck_original: true,
            speaker_gender: "auto".into(),
            match_voice: false,
            female_voice: None,
            male_voice: None,
            captions: true,
            profiles: BTreeMap::new(),
        }
    }
}

fn path() -> Option<PathBuf> {
    Some(dirs::config_dir()?.join("Synchro").join("settings.json"))
}

impl Settings {
    pub fn select_provider(&mut self, provider: String) {
        if self.provider == provider {
            return;
        }
        self.profiles.insert(
            self.provider.clone(),
            ProviderProfile {
                model: self.model.clone(),
                api_key: self.api_key.clone(),
                base_url: self.base_url.clone(),
                balance_key: self.balance_key.clone(),
            },
        );
        let profile = self.profiles.get(&provider).cloned().unwrap_or_default();
        self.provider = provider;
        (self.model, self.api_key, self.base_url) =
            (profile.model, profile.api_key, profile.base_url);
        self.balance_key = profile.balance_key;
    }

    pub fn load() -> Settings {
        path()
            .and_then(|p| std::fs::read(p).ok())
            .and_then(|data| serde_json::from_slice(&data).ok())
            .unwrap_or_default()
    }

    pub fn save(&self) -> Result<(), String> {
        // shortcut: the key is stored as plain JSON in the user's profile, like the extension's storage; use DPAPI if shared PCs matter.
        let p = path().ok_or("Windows settings folder is unavailable")?;
        std::fs::create_dir_all(p.parent().unwrap()).map_err(|e| e.to_string())?;
        let data = serde_json::to_vec_pretty(self).map_err(|e| e.to_string())?;
        std::fs::write(p, data).map_err(|e| e.to_string())
    }

    pub fn connection_error(&self) -> Option<&'static str> {
        if self.provider == "custom" {
            let valid = reqwest::Url::parse(self.base_url.trim()).is_ok_and(|url| {
                matches!(url.scheme(), "http" | "https") && url.host_str().is_some()
            });
            if !valid {
                return Some("Enter a valid server address starting with http:// or https://.");
            }
        } else if self.api_key.trim().is_empty() {
            return Some("Add your provider's API key to enable translation.");
        }
        None
    }

    /// Translation settings in the engine's API shape (cloud text translation; speech stays on this computer).
    pub fn translation(&self) -> Value {
        let mut value = json!({"provider": self.provider, "mode": "cloud_translation", "api_key": self.api_key.trim()});
        if !self.model.trim().is_empty() {
            value["model"] = json!(self.model.trim());
        }
        if self.provider == "custom" {
            value["base_url"] = json!(self.base_url.trim());
        }
        value
    }

    pub fn session(&self) -> Value {
        json!({"voice": self.voice, "language": self.language, "translation": self.translation(),
               "speaker_gender": self.speaker_gender, "match_voice": self.match_voice,
               "female_voice": self.female_voice, "male_voice": self.male_voice})
    }
}

pub fn label<'a>(items: &[(&'a str, &'a str)], id: &str) -> &'a str {
    items
        .iter()
        .find(|(key, _)| *key == id)
        .map(|(_, name)| *name)
        .unwrap_or("")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assigned_voices_are_saved_and_retained_in_single_voice_mode() {
        let settings = Settings {
            voice: "alexandr".into(),
            match_voice: true,
            female_voice: Some("alfia".into()),
            male_voice: Some("eduard".into()),
            ..Default::default()
        };
        let mut saved: Settings =
            serde_json::from_value(serde_json::to_value(&settings).unwrap()).unwrap();
        assert_eq!(saved.session()["female_voice"], "alfia");
        assert_eq!(saved.session()["male_voice"], "eduard");
        saved.match_voice = false;
        assert_eq!(saved.session()["voice"], "alexandr");
        saved.match_voice = true;
        assert_eq!(saved.female_voice.as_deref(), Some("alfia"));
        assert_eq!(saved.male_voice.as_deref(), Some("eduard"));
    }

    #[test]
    fn old_settings_keep_credentials_and_receive_new_defaults() {
        let saved: Settings = serde_json::from_value(
            json!({"provider":"kilo", "api_key":"existing-key", "original_volume":0.8}),
        )
        .unwrap();
        assert_eq!(saved.api_key, "existing-key");
        assert_eq!(saved.original_volume, 0.8);
        assert!(saved.duck_original && !saved.match_voice);
        assert_eq!(saved.speaker_gender, "auto");
        assert!(saved.profiles.is_empty());
    }

    #[test]
    fn switching_provider_never_sends_the_previous_providers_key() {
        let mut settings = Settings {
            api_key: "openrouter-private-key".into(),
            model: "chosen/model".into(),
            ..Default::default()
        };
        settings.balance_key = "management-only-key".into();
        assert!(
            !settings
                .session()
                .to_string()
                .contains("management-only-key")
        );
        settings.select_provider("kilo".into());
        assert!(settings.api_key.is_empty() && settings.model.is_empty());
        assert!(settings.balance_key.is_empty());
        settings.api_key = "kilo-private-key".into();
        settings.select_provider("openrouter".into());
        assert_eq!(settings.api_key, "openrouter-private-key");
        assert_eq!(settings.model, "chosen/model");
        assert_eq!(settings.balance_key, "management-only-key");
        let persisted = serde_json::to_value(&settings).unwrap();
        assert!(!persisted.to_string().contains("management-only-key"));
        let mut restored: Settings = serde_json::from_value(persisted).unwrap();
        restored.select_provider("kilo".into());
        assert_eq!(restored.api_key, "kilo-private-key");
    }

    #[test]
    fn custom_endpoint_and_default_model_are_mapped() {
        let mut settings = Settings {
            provider: "custom".into(),
            base_url: " http://127.0.0.1:1234/v1 ".into(),
            model: "qwen".into(),
            ..Default::default()
        };
        assert_eq!(
            settings.translation()["base_url"],
            "http://127.0.0.1:1234/v1"
        );
        settings.provider = "kilo".into();
        settings.model.clear();
        let translation = settings.translation();
        assert!(translation.get("base_url").is_none() && translation.get("model").is_none());
        assert_eq!(settings.session()["language"], "en");
    }

    #[test]
    fn connection_requires_a_key_or_a_valid_custom_server() {
        let mut settings = Settings::default();
        assert!(settings.connection_error().is_some());
        settings.api_key = "   ".into();
        assert!(settings.connection_error().is_some());
        settings.api_key = "test-key".into();
        assert_eq!(settings.connection_error(), None);
        settings.provider = "custom".into();
        settings.api_key.clear();
        for address in ["", "localhost:1234", "file:///video", "ftp://localhost"] {
            settings.base_url = address.into();
            assert!(settings.connection_error().is_some(), "{address}");
        }
        settings.base_url = " http://127.0.0.1:1234/v1 ".into();
        assert_eq!(settings.connection_error(), None);
    }
}
