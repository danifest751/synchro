#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
//! Synchro desktop: watch local video files with Russian voiceover. Speech recognition and voices run on this
//! computer through the bundled engine; only text translation uses the provider configured below.
mod api;
mod config;
mod engine;
mod mpv;
mod player;
mod wav;

use config::{label, Settings, LANGUAGES, PROVIDERS, VOICES};
use eframe::egui;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

enum EngineState {
    Starting,
    Ready(api::Api),
    Failed(String),
}

struct App {
    settings: Arc<Mutex<Settings>>,
    edited: Settings,
    engine: Arc<Mutex<EngineState>>,
    mpv: Option<PathBuf>,
    player: Option<player::Player>,
    pending: Option<PathBuf>,
    check: Arc<Mutex<String>>,
}

impl App {
    fn new(file: Option<PathBuf>) -> App {
        let settings = Settings::load();
        let engine = Arc::new(Mutex::new(EngineState::Starting));
        let check: Arc<Mutex<String>> = Default::default();
        let mut mpv = None;
        match engine::Layout::find() {
            Ok(layout) => {
                mpv = Some(layout.mpv.clone());
                let (state, warm, session) = (engine.clone(), check.clone(), (!settings.api_key.trim().is_empty() || settings.provider == "custom").then(|| settings.session()));
                std::thread::spawn(move || {
                    let result = engine::Engine::start(&layout);
                    let api = result.as_ref().ok().map(|engine| engine.api.clone());
                    *state.lock().unwrap() = match result {
                        Ok(engine) => {
                            // The engine lives as long as the program; its job object ends it on exit.
                            std::mem::forget(engine);
                            EngineState::Ready(api.clone().unwrap())
                        }
                        Err(error) => EngineState::Failed(error),
                    };
                    // Load the models now so the first video starts in seconds, not half a minute.
                    if let (Some(api), Some(session)) = (api, session) {
                        *warm.lock().unwrap() = "Loading recognition and voice models…".into();
                        *warm.lock().unwrap() = match api.check(session) {
                            Ok(seconds) => format!("Models ready ({seconds:.0} s)"),
                            Err(error) => format!("Check failed: {error}"),
                        };
                    }
                });
            }
            Err(error) => *engine.lock().unwrap() = EngineState::Failed(error),
        }
        App { settings: Arc::new(Mutex::new(settings.clone())), edited: settings, engine, mpv, player: None, pending: file, check }
    }

    fn api(&self) -> Option<api::Api> {
        match &*self.engine.lock().unwrap() {
            EngineState::Ready(api) => Some(api.clone()),
            _ => None,
        }
    }

    fn open(&mut self, file: PathBuf) {
        let (Some(api), Some(mpv)) = (self.api(), self.mpv.clone()) else {
            self.pending = Some(file);
            return;
        };
        if let Some(player) = self.player.take() {
            player.stop();
        }
        self.player = Some(player::Player::start(api, mpv, file, self.settings.clone()));
    }

    fn check(&self) {
        let Some(api) = self.api() else { return };
        let (session, result) = (self.edited.session(), self.check.clone());
        *result.lock().unwrap() = "Loading recognition, translation and voice…".into();
        std::thread::spawn(move || {
            *result.lock().unwrap() = match api.check(session) {
                Ok(seconds) => format!("Ready: recognition, translation and voice work ({seconds:.1} s)"),
                Err(error) => format!("Check failed: {error}"),
            };
        });
    }

    fn settings_ui(&mut self, ui: &mut egui::Ui) {
        let edited = &mut self.edited;
        egui::Grid::new("settings").num_columns(2).spacing([12.0, 8.0]).show(ui, |ui| {
            ui.label("Translation provider");
            egui::ComboBox::from_id_salt("provider").selected_text(label(&PROVIDERS, &edited.provider)).show_ui(ui, |ui| {
                for (id, name) in PROVIDERS {
                    ui.selectable_value(&mut edited.provider, id.to_string(), name);
                }
            });
            ui.end_row();
            if edited.provider == "custom" {
                ui.label("Server address");
                ui.add(egui::TextEdit::singleline(&mut edited.base_url).hint_text("http://127.0.0.1:1234/v1"));
                ui.end_row();
            }
            ui.label("Model");
            let hint = match edited.provider.as_str() { "kilo" => "tencent/hy-mt2-1.8b", "openai" => "gpt-4.1-mini", "custom" => "model ID", _ => "google/gemma-4-26b-a4b-it" };
            ui.add(egui::TextEdit::singleline(&mut edited.model).hint_text(hint));
            ui.end_row();
            ui.label("API key");
            ui.add(egui::TextEdit::singleline(&mut edited.api_key).password(true).hint_text(if edited.provider == "custom" { "optional" } else { "required" }));
            ui.end_row();
            ui.label("Voice");
            egui::ComboBox::from_id_salt("voice").selected_text(label(&VOICES, &edited.voice)).show_ui(ui, |ui| {
                for (id, name) in VOICES {
                    ui.selectable_value(&mut edited.voice, id.to_string(), name);
                }
            });
            ui.end_row();
            ui.label("Video language");
            egui::ComboBox::from_id_salt("language").selected_text(label(&LANGUAGES, &edited.language)).show_ui(ui, |ui| {
                for (id, name) in LANGUAGES {
                    ui.selectable_value(&mut edited.language, id.to_string(), name);
                }
            });
            ui.end_row();
            ui.label("Voiceover volume");
            ui.add(egui::Slider::new(&mut edited.voice_volume, 0.0..=1.0).show_value(false));
            ui.end_row();
            ui.label("Original volume");
            ui.add(egui::Slider::new(&mut edited.original_volume, 0.0..=1.0).show_value(false));
            ui.end_row();
            ui.label("Captions");
            ui.checkbox(&mut edited.captions, "Show the translation on screen");
            ui.end_row();
        });
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        ui.ctx().request_repaint_after(Duration::from_millis(250));
        if self.pending.is_some() && self.api().is_some() {
            let file = self.pending.take().unwrap();
            self.open(file);
        }
        if self.player.as_ref().is_some_and(|player| player.done()) {
            self.player = None;
        }
        ui.heading("Synchro");
        let engine = match &*self.engine.lock().unwrap() {
            EngineState::Starting => "Starting the speech engine…".to_string(),
            EngineState::Ready(_) => "Speech engine ready".to_string(),
            EngineState::Failed(error) => format!("Engine failed: {error}"),
        };
        ui.label(engine);
        ui.separator();
        self.settings_ui(ui);
        // Settings take effect immediately; voice and language changes translate again from the current position.
        let mut saved = self.settings.lock().unwrap();
        if *saved != self.edited {
            let retranslate = saved.voice != self.edited.voice || saved.language != self.edited.language;
            *saved = self.edited.clone();
            saved.save();
            drop(saved);
            if retranslate {
                if let Some(player) = &self.player {
                    player.restart();
                }
            }
        } else {
            drop(saved);
        }
        ui.separator();
        ui.horizontal(|ui| {
            let ready = self.api().is_some();
            if ui.add_enabled(ready, egui::Button::new("Open video…")).clicked() {
                let picked = rfd::FileDialog::new()
                    .add_filter("Video", &["mp4", "mkv", "avi", "mov", "webm", "m4v", "wmv", "flv", "ts", "mpg", "mpeg"])
                    .pick_file();
                if let Some(file) = picked {
                    self.open(file);
                }
            }
            if ui.add_enabled(ready, egui::Button::new("Check translation")).clicked() {
                self.check();
            }
            if let Some(player) = &self.player {
                if ui.button("Stop").clicked() {
                    player.stop();
                }
            }
        });
        let check = self.check.lock().unwrap().clone();
        if !check.is_empty() {
            ui.label(check);
        }
        if let Some(player) = &self.player {
            let (status, error) = player.status();
            ui.label(error.map(|error| format!("Error: {error}")).unwrap_or(status));
        }
    }
}

/// `Synchro --self-test <video>`: start the engine, translate two windows and report, without mpv or a window.
fn self_test(file: PathBuf) -> Result<String, String> {
    let layout = engine::Layout::find()?;
    let started = std::time::Instant::now();
    let engine = engine::Engine::start(&layout)?;
    let mut report = format!("engine ready in {:.1} s
", started.elapsed().as_secs_f64());
    let opened = engine.api.open_file(&file.to_string_lossy(), 0.0, Settings::load().session()).map_err(|e| e.to_string())?;
    report += &format!("opened {:.0} s video in {:.1} s
", opened.duration, started.elapsed().as_secs_f64());
    let mut ready = opened.base;
    for _ in 0..2 {
        let window = engine.api.next(&opened.session_id, ready).map_err(|e| e.to_string())?;
        ready = window.ready_until;
        for segment in &window.segments {
            let audio = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &segment.wav).map_err(|e| e.to_string())?;
            let pcm = wav::decode(&audio)?;
            report += &format!("  {:6.1} s +{:.1} s voice {:.1} s ({} Hz): {}
", segment.start, segment.source_duration,
                               pcm.samples.len() as f64 / pcm.rate as f64, pcm.rate, segment.text);
        }
        report += &format!("translated to {ready:.0} s after {:.1} s
", started.elapsed().as_secs_f64());
    }
    engine.api.close(&opened.session_id);
    Ok(report)
}

fn main() -> eframe::Result {
    let mut args = std::env::args_os().skip(1);
    let first = args.next();
    if first.as_deref() == Some(std::ffi::OsStr::new("--self-test")) {
        let result = args.next().map(PathBuf::from).ok_or("usage: Synchro --self-test <video>".to_string()).and_then(self_test);
        let text = result.unwrap_or_else(|error| format!("FAILED: {error}
"));
        print!("{text}");
        let _ = std::fs::write(engine::log_path().with_file_name("self-test.txt"), text);
        return Ok(());
    }
    let file = first.map(PathBuf::from);
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([460.0, 470.0]).with_title("Synchro"),
        ..Default::default()
    };
    eframe::run_native("Synchro", options, Box::new(move |_| Ok(Box::new(App::new(file)))))
}
