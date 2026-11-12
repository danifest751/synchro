use crate::api::{Api, Balance, Model};
use crate::config::Settings;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[derive(Clone, Default)]
pub enum Fetch<T> {
    #[default]
    Idle,
    Loading,
    Ready(Result<T, String>, Instant),
}

pub struct ProviderState {
    provider: String,
    key: String,
    balance_key: String,
    changed: Instant,
    pub models: Arc<Mutex<Fetch<Vec<Model>>>>,
    pub balance: Arc<Mutex<Fetch<Balance>>>,
    pub search: String,
}

impl Default for ProviderState {
    fn default() -> Self {
        Self {
            provider: String::new(),
            key: String::new(),
            balance_key: String::new(),
            changed: Instant::now(),
            models: Default::default(),
            balance: Default::default(),
            search: String::new(),
        }
    }
}

impl ProviderState {
    pub fn sync(&mut self, settings: &Settings) {
        if self.provider != settings.provider {
            self.models = Default::default();
            self.search.clear();
        }
        if self.provider != settings.provider
            || self.key != settings.api_key.trim()
            || self.balance_key != settings.balance_key.trim()
        {
            // Old workers retain their old Arc, so a late result cannot appear under another account.
            self.balance = Default::default();
            self.provider = settings.provider.clone();
            self.key = settings.api_key.trim().into();
            self.balance_key = settings.balance_key.trim().into();
            self.changed = Instant::now();
        }
    }

    pub fn update(&mut self, settings: &Settings, api: Option<Api>) {
        self.sync(settings);
        if !matches!(settings.provider.as_str(), "kilo" | "openrouter") {
            return;
        }
        let Some(api) = api else { return };
        {
            let mut models = self.models.lock().unwrap();
            if matches!(*models, Fetch::Idle) {
                *models = Fetch::Loading;
                let (api, provider, output) =
                    (api.clone(), self.provider.clone(), self.models.clone());
                std::thread::spawn(move || {
                    let result = api.models(&provider).map_err(|e| e.to_string());
                    *output.lock().unwrap() = Fetch::Ready(result, Instant::now());
                });
            }
        }
        if self.key.len() < 16 || self.changed.elapsed() < Duration::from_secs(1) {
            return;
        }
        let mut balance = self.balance.lock().unwrap();
        let expired =
            matches!(&*balance, Fetch::Ready(Ok(_), at) if at.elapsed() >= Duration::from_secs(60));
        if matches!(*balance, Fetch::Idle) || expired {
            *balance = Fetch::Loading;
            let (settings, output) = (settings.clone(), self.balance.clone());
            std::thread::spawn(move || {
                let result = api.balance(&settings).map_err(|e| e.to_string());
                *output.lock().unwrap() = Fetch::Ready(result, Instant::now());
            });
        }
    }

    pub fn refresh(&mut self) {
        if !matches!(*self.models.lock().unwrap(), Fetch::Loading) {
            self.models = Default::default();
        }
        if !matches!(*self.balance.lock().unwrap(), Fetch::Loading) {
            self.balance = Default::default();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_change_discards_late_account_data_but_keeps_public_models() {
        let mut state = ProviderState::default();
        let mut settings = Settings {
            api_key: "first-key".into(),
            ..Default::default()
        };
        state.sync(&settings);
        let old_balance = state.balance.clone();
        let old_models = state.models.clone();
        settings.api_key = "second-key".into();
        state.sync(&settings);
        assert!(!Arc::ptr_eq(&old_balance, &state.balance));
        assert!(Arc::ptr_eq(&old_models, &state.models));
        *old_balance.lock().unwrap() = Fetch::Ready(Err("old response".into()), Instant::now());
        assert!(matches!(*state.balance.lock().unwrap(), Fetch::Idle));
        settings.provider = "kilo".into();
        state.sync(&settings);
        assert!(!Arc::ptr_eq(&old_models, &state.models));
    }
}
