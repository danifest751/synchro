#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
//! Synchro desktop: watch local video files with Russian voiceover. Speech recognition and voices run on this
//! computer through the bundled engine; only text translation uses the provider configured below.
mod api;
mod billing;
mod config;
mod engine;
mod mpv;
mod player;
mod provider;
mod ui;
mod wav;

use config::Settings;
use eframe::egui;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Clone, Default)]
enum CheckState {
    #[default]
    Idle,
    Running,
    Passed(f64),
    Failed(String),
}

#[derive(Default)]
struct CheckReport {
    session: serde_json::Value,
    state: CheckState,
}

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
    check: Arc<Mutex<CheckReport>>,
    translation_page: bool,
    current_file: Option<PathBuf>,
    playback_status: String,
    playback_error: Option<String>,
    notice: Option<String>,
    save_error: Option<String>,
    providers: provider::ProviderState,
    playback_id: Option<u64>,
    restart_after: Option<std::time::Instant>,
}

impl App {
    fn new(file: Option<PathBuf>) -> App {
        let settings = Settings::load();
        let translation_page = file.is_some() && settings.connection_error().is_some();
        let engine = Arc::new(Mutex::new(EngineState::Starting));
        let check: Arc<Mutex<CheckReport>> = Default::default();
        let mut mpv = None;
        match engine::Layout::find() {
            Ok(layout) => {
                mpv = Some(layout.mpv.clone());
                let (state, warm, session) = (
                    engine.clone(),
                    check.clone(),
                    settings
                        .connection_error()
                        .is_none()
                        .then(|| settings.session()),
                );
                std::thread::spawn(move || {
                    let result = engine::Engine::start(&layout);
                    let api = result.as_ref().ok().map(|engine| engine.api.clone());
                    if api.is_some()
                        && let Some(session) = &session
                    {
                        *warm.lock().unwrap() = CheckReport {
                            session: session.clone(),
                            state: CheckState::Running,
                        };
                    }
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
                        let checked = match api.check(session) {
                            Ok(seconds) => CheckState::Passed(seconds),
                            Err(error) => CheckState::Failed(error.to_string()),
                        };
                        warm.lock().unwrap().state = checked;
                    }
                });
            }
            Err(error) => *engine.lock().unwrap() = EngineState::Failed(error),
        }
        App {
            settings: Arc::new(Mutex::new(settings.clone())),
            edited: settings,
            engine,
            mpv,
            player: None,
            pending: file,
            check,
            translation_page,
            current_file: None,
            playback_status: String::new(),
            playback_error: None,
            notice: None,
            save_error: None,
            providers: Default::default(),
            playback_id: None,
            restart_after: None,
        }
    }

    fn api(&self) -> Option<api::Api> {
        match &*self.engine.lock().unwrap() {
            EngineState::Ready(api) => Some(api.clone()),
            _ => None,
        }
    }

    fn open(&mut self, file: PathBuf) {
        self.notice = None;
        self.pending = None;
        self.restart_after = None;
        if self.edited.connection_error().is_some() {
            self.pending = Some(file);
            self.translation_page = true;
            return;
        }
        let (Some(api), Some(mpv)) = (self.api(), self.mpv.clone()) else {
            self.pending = Some(file);
            self.translation_page = false;
            return;
        };
        self.save_settings();
        if let Some(player) = self.player.take() {
            player.stop();
        }
        self.current_file = Some(file.clone());
        self.playback_status = "Preparing translation…".into();
        self.playback_error = None;
        self.translation_page = false;
        self.player = Some(player::Player::start(api, mpv, file, self.settings.clone()));
        self.playback_id = self.player.as_ref().map(|player| player.video_id());
    }

    fn check(&self) {
        let Some(api) = self.api() else { return };
        if self.edited.connection_error().is_some() {
            return;
        }
        let (session, result) = (self.edited.session(), self.check.clone());
        {
            let mut report = result.lock().unwrap();
            if matches!(report.state, CheckState::Running) {
                return;
            }
            *report = CheckReport {
                session: session.clone(),
                state: CheckState::Running,
            };
        }
        std::thread::spawn(move || {
            let checked = match api.check(session) {
                Ok(seconds) => CheckState::Passed(seconds),
                Err(error) => CheckState::Failed(error.to_string()),
            };
            result.lock().unwrap().state = checked;
        });
    }

    fn pick_video(&mut self) {
        if let Some(file) = rfd::FileDialog::new()
            .set_title("Open a video with Synchro")
            .add_filter("Video files", VIDEO_EXTENSIONS)
            .pick_file()
        {
            self.open(file);
        }
    }

    fn save_settings(&mut self) {
        let mut saved = self.settings.lock().unwrap();
        if *saved != self.edited {
            let retranslate = saved.session() != self.edited.session();
            *saved = self.edited.clone();
            self.save_error = saved.save().err();
            drop(saved);
            if retranslate && self.player.is_some() {
                self.restart_after = Some(std::time::Instant::now() + Duration::from_millis(750));
            }
        }
    }
}

const VIDEO_EXTENSIONS: &[&str] = &[
    "mp4", "mkv", "avi", "mov", "webm", "m4v", "wmv", "flv", "ts", "mpg", "mpeg",
];

fn is_video(file: &std::path::Path) -> bool {
    file.extension().and_then(|s| s.to_str()).is_some_and(|s| {
        VIDEO_EXTENSIONS
            .iter()
            .any(|ext| s.eq_ignore_ascii_case(ext))
    })
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        ui.ctx().request_repaint_after(Duration::from_millis(250));
        // Keep the terminal status visible after the player threads finish, including errors.
        if let Some(player) = &self.player {
            (self.playback_status, self.playback_error) = player.status();
            if player.done() {
                if self.playback_error.is_none() {
                    self.playback_status = "Playback finished".into();
                }
                self.player = None;
            }
        }
        let dropped = ui
            .ctx()
            .input(|i| i.raw.dropped_files.first().map(|f| f.path().to_path_buf()));
        if let Some(file) = dropped {
            if is_video(&file) {
                self.open(file);
            } else {
                self.notice = Some(
                    "Choose a video file: MP4, MKV, AVI, MOV, WebM, or another supported format."
                        .into(),
                );
            }
        }
        if ui
            .ctx()
            .input_mut(|i| i.consume_key(egui::Modifiers::COMMAND, egui::Key::O))
        {
            self.pick_video();
        }
        self.draw(ui);
        self.providers.update(&self.edited, self.api());
        self.save_settings();
        if self
            .restart_after
            .is_some_and(|at| std::time::Instant::now() >= at)
            && self.edited.connection_error().is_none()
        {
            self.restart_after = None;
            if let Some(player) = &self.player {
                player.restart();
            }
        }
        if !self.translation_page
            && self.pending.is_some()
            && self.api().is_some()
            && self.edited.connection_error().is_none()
        {
            let file = self.pending.take().unwrap();
            self.open(file);
        }
    }
}

/// `Synchro --self-test <video>`: start the engine, translate two windows and report, without mpv or a window.
fn self_test(file: PathBuf) -> Result<String, String> {
    let layout = engine::Layout::find()?;
    let started = std::time::Instant::now();
    let engine = engine::Engine::start(&layout)?;
    let mut report = format!(
        "engine ready in {:.1} s
",
        started.elapsed().as_secs_f64()
    );
    let opened = engine
        .api
        .open_file(&file.to_string_lossy(), 0.0, Settings::load().session())
        .map_err(|e| e.to_string())?;
    report += &format!(
        "opened {:.0} s video in {:.1} s
",
        opened.duration,
        started.elapsed().as_secs_f64()
    );
    let mut ready = opened.base;
    for _ in 0..2 {
        let window = engine
            .api
            .next(&opened.session_id, ready)
            .map_err(|e| e.to_string())?;
        ready = window.ready_until;
        for segment in &window.segments {
            let audio =
                base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &segment.wav)
                    .map_err(|e| e.to_string())?;
            let pcm = wav::decode(&audio)?;
            report += &format!(
                "  {:6.1} s +{:.1} s voice {:.1} s ({} Hz): {}
",
                segment.start,
                segment.source_duration,
                pcm.samples.len() as f64 / pcm.rate as f64,
                pcm.rate,
                segment.text
            );
        }
        report += &format!(
            "translated to {ready:.0} s after {:.1} s
",
            started.elapsed().as_secs_f64()
        );
    }
    engine.api.close(&opened.session_id);
    Ok(report)
}

fn main() -> eframe::Result {
    let mut args = std::env::args_os().skip(1);
    let first = args.next();
    if first.as_deref() == Some(std::ffi::OsStr::new("--self-test")) {
        let result = args
            .next()
            .map(PathBuf::from)
            .ok_or("usage: Synchro --self-test <video>".to_string())
            .and_then(self_test);
        let text = result.unwrap_or_else(|error| {
            format!(
                "FAILED: {error}
"
            )
        });
        print!("{text}");
        let _ = std::fs::write(engine::log_path().with_file_name("self-test.txt"), text);
        return Ok(());
    }
    let file = first.map(PathBuf::from);
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1080.0, 780.0])
            .with_min_inner_size([680.0, 560.0])
            .with_icon(ui::icon())
            .with_title("Synchro"),
        ..Default::default()
    };
    eframe::run_native(
        "Synchro",
        options,
        Box::new(move |cc| {
            ui::configure(&cc.egui_ctx);
            Ok(Box::new(App::new(file)))
        }),
    )
}

#[cfg(test)]
mod ui_tests {
    use super::*;

    fn app() -> App {
        App {
            settings: Arc::new(Mutex::new(Settings::default())),
            edited: Settings::default(),
            engine: Arc::new(Mutex::new(EngineState::Starting)),
            mpv: None,
            player: None,
            pending: None,
            check: Default::default(),
            translation_page: false,
            current_file: None,
            playback_status: String::new(),
            playback_error: None,
            notice: None,
            save_error: None,
            providers: Default::default(),
            playback_id: None,
            restart_after: None,
        }
    }

    #[test]
    fn selected_video_survives_setup_and_engine_startup() {
        let mut app = app();
        let file = PathBuf::from("a video.mkv");
        app.open(file.clone());
        assert!(app.translation_page);
        assert_eq!(app.pending.as_ref(), Some(&file));
        assert!(app.player.is_none());
        app.edited.api_key = "test-key".into();
        app.open(file.clone());
        assert!(!app.translation_page);
        assert_eq!(app.pending.as_ref(), Some(&file));
        assert!(app.player.is_none());
    }

    #[test]
    fn connection_checks_cannot_overlap() {
        let mut app = app();
        app.edited.api_key = "test-key".into();
        *app.engine.lock().unwrap() =
            EngineState::Ready(api::Api::new("http://127.0.0.1:1".into(), "test".into()));
        app.check.lock().unwrap().state = CheckState::Running;
        app.check();
        assert!(matches!(
            app.check.lock().unwrap().state,
            CheckState::Running
        ));
    }

    #[test]
    fn screens_render_without_horizontal_overflow() {
        for size in [[680.0, 560.0], [1080.0, 780.0]] {
            for page in [
                "watch", "cloud", "custom", "pending", "error", "catalog", "paired",
            ] {
                let mut app = app();
                app.translation_page = page != "watch";
                if page == "paired" {
                    app.translation_page = false;
                    app.edited.match_voice = true;
                    app.edited.female_voice = Some("alfia".into());
                    app.edited.male_voice = Some("eduard".into());
                }
                if page == "custom" {
                    app.edited.provider = "custom".into();
                }
                if page == "catalog" {
                    app.edited.model = "provider/model-with-a-long-version-id".into();
                    app.providers.sync(&app.edited);
                    *app.providers.models.lock().unwrap() = provider::Fetch::Ready(Ok(vec![api::Model {
                        id: app.edited.model.clone(), name: "A provider model name with a very long description and release version for a narrow window".into(),
                        input_price: Some(0.000001), output_price: Some(0.000002),
                    }]), std::time::Instant::now());
                    *app.providers.balance.lock().unwrap() = provider::Fetch::Ready(
                        Ok(api::Balance {
                            balance_usd: Some(0.0),
                            total_spent_usd: Some(0.0),
                            ..Default::default()
                        }),
                        std::time::Instant::now(),
                    );
                }
                if page == "pending" {
                    app.pending = Some(PathBuf::from(
                        "A video selected before setting up translation.mkv",
                    ));
                }
                if page == "error" {
                    app.translation_page = false;
                    app.edited.api_key = "test-key".into();
                    app.current_file = Some(PathBuf::from(
                        "A very long video filename with spaces and more information about the video.mkv",
                    ));
                    app.playback_error = Some("The translation provider is unavailable. Check your connection and try opening the video again.".into());
                    *app.engine.lock().unwrap() = EngineState::Failed("Could not start the speech engine. The runtime or model files may be missing.".into());
                }
                let ctx = egui::Context::default();
                ui::configure(&ctx);
                let screen =
                    egui::Rect::from_min_size(egui::Pos2::ZERO, egui::vec2(size[0], size[1]));
                for pass in 0..3 {
                    let mut output = ctx.run_ui(
                        egui::RawInput {
                            screen_rect: Some(screen),
                            ..Default::default()
                        },
                        |ui| app.draw(ui),
                    );
                    output.textures_delta.clear();
                    if pass < 2 {
                        continue;
                    }
                    for shape in &output.shapes {
                        if let egui::Shape::Text(text) = &shape.shape {
                            let bounds = text.visual_bounding_rect();
                            if bounds.intersects(shape.clip_rect) {
                                assert!(
                                    bounds.left() >= -1.0 && bounds.right() <= screen.right() + 1.0,
                                    "{page} at {size:?}: {:?} at {bounds:?}",
                                    text.galley.job.text
                                );
                            }
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn dropped_video_extensions_are_case_insensitive() {
        assert!(is_video(std::path::Path::new("Film.MKV")));
        assert!(is_video(std::path::Path::new("clip.mp4")));
        assert!(!is_video(std::path::Path::new("settings.json")));
        assert!(!is_video(std::path::Path::new("no-extension")));
    }
}
