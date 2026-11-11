use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::PathBuf;

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
pub const LANGUAGES: [(&str, &str); 4] = [("en", "English"), ("zh", "Chinese"), ("ko", "Korean"), ("ja", "Japanese")];

#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub provider: String,
    pub model: String,
    pub api_key: String,
    pub base_url: String,
    pub voice: String,
    pub language: String,
    pub voice_volume: f32,
    pub original_volume: f32,
    pub captions: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            provider: "openrouter".into(),
            model: String::new(),
            api_key: String::new(),
            base_url: String::new(),
            voice: "albina".into(),
            language: "en".into(),
            voice_volume: 0.9,
            original_volume: 0.55,
            captions: true,
        }
    }
}

fn path() -> Option<PathBuf> {
    Some(dirs::config_dir()?.join("Synchro").join("settings.json"))
}

impl Settings {
    pub fn load() -> Settings {
        path().and_then(|p| std::fs::read(p).ok()).and_then(|data| serde_json::from_slice(&data).ok()).unwrap_or_default()
    }

    pub fn save(&self) {
        // shortcut: the key is stored as plain JSON in the user's profile, like the extension's storage; use DPAPI if shared PCs matter.
        if let Some(p) = path() {
            let _ = std::fs::create_dir_all(p.parent().unwrap());
            let _ = std::fs::write(p, serde_json::to_vec_pretty(self).unwrap_or_default());
        }
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
        json!({"voice": self.voice, "language": self.language, "translation": self.translation()})
    }
}

pub fn label<'a>(items: &[(&'a str, &'a str)], id: &str) -> &'a str {
    items.iter().find(|(key, _)| *key == id).map(|(_, name)| *name).unwrap_or("")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn custom_endpoint_and_default_model_are_mapped() {
        let mut settings = Settings { provider: "custom".into(), base_url: " http://127.0.0.1:1234/v1 ".into(), model: "qwen".into(), ..Default::default() };
        assert_eq!(settings.translation()["base_url"], "http://127.0.0.1:1234/v1");
        settings.provider = "kilo".into();
        settings.model.clear();
        let translation = settings.translation();
        assert!(translation.get("base_url").is_none() && translation.get("model").is_none());
        assert_eq!(settings.session()["language"], "en");
    }
}
