//! Plays translated speech in sync with mpv: the same rules as the extension's YouTube overlay.
//! A fetcher thread asks the engine for windows ahead of the picture; a scheduler thread drives mpv and the voice.
use crate::api::{Api, ApiError, Window};
use crate::config::Settings;
use crate::mpv::Mpv;
use crate::wav::{self, Pcm};
use base64::Engine as _;
use rodio::Source;
use serde_json::json;
use std::num::NonZero;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

/// Translation kept ahead of the picture, and needed before playback starts.
const LOOKAHEAD: f64 = 34.0;
const INITIAL_BUFFER: f64 = 10.0;

pub struct Cue {
    pub id: u64,
    pub start: f64,
    pub duration: f64,
    pub source_duration: f64,
    pub text: String,
    pub audio: Arc<Pcm>,
}

#[derive(Default)]
pub struct Shared {
    pub generation: u64,
    pub position: f64,
    pub duration: f64,
    pub cues: Vec<Cue>,
    pub ready: f64,
    pub finished: bool,
    pub error: Option<String>,
    pub stop: bool,
    pub status: String,
}

pub fn cue_at(cues: &[Cue], time: f64) -> Option<&Cue> {
    cues.iter()
        .find(|cue| cue.start <= time && time < cue.start + cue.source_duration)
}

/// Video speed that fits a phrase's speech into its source interval (slower for long Russian phrases).
pub fn video_rate(cue: Option<&Cue>) -> f64 {
    cue.map(|cue| (cue.source_duration / cue.duration.max(0.01)).clamp(0.0625, 16.0))
        .unwrap_or(1.0)
}

fn original_gain(volume: f32, ducked: bool) -> f64 {
    f64::from(volume.clamp(0.0, 1.0)) * if ducked { 0.5 } else { 1.0 }
}

fn mpv_volume(gain: f64) -> f64 {
    // mpv cubes its volume percentage; the UI and rodio both use linear gain.
    100.0 * gain.clamp(0.0, 1.0).cbrt()
}

/// Playback may start once the initial buffer (or the rest of a short video) is translated.
pub fn prepared(ready: f64, time: f64, duration: f64, finished: bool) -> bool {
    ready - time >= INITIAL_BUFFER.min(duration - time - 0.1) - 0.025
        || finished && ready - time > 0.1
}

pub fn starved(ready: f64, time: f64, finished: bool) -> bool {
    !finished && ready - time < 1.1
}

pub fn enough(ready: f64, time: f64, finished: bool) -> bool {
    if finished {
        ready - time > 0.05
    } else {
        ready - time > 1.25
    }
}

pub struct Player {
    shared: Arc<Mutex<Shared>>,
    threads: Vec<JoinHandle<()>>,
    video_id: u64,
}

impl Player {
    pub fn start(api: Api, mpv: PathBuf, file: PathBuf, settings: Arc<Mutex<Settings>>) -> Player {
        let api = api.for_video();
        let video_id = api.video_id();
        let shared = Arc::new(Mutex::new(Shared {
            generation: 1,
            status: "Preparing translation…".into(),
            ..Default::default()
        }));
        let fetcher = {
            let (shared, settings, file) = (
                shared.clone(),
                settings.clone(),
                file.to_string_lossy().into_owned(),
            );
            std::thread::spawn(move || fetch(api, file, settings, shared))
        };
        let scheduler = {
            let shared = shared.clone();
            std::thread::spawn(move || schedule(mpv, file, settings, shared))
        };
        Player {
            shared,
            threads: vec![fetcher, scheduler],
            video_id,
        }
    }

    pub fn video_id(&self) -> u64 {
        self.video_id
    }

    pub fn status(&self) -> (String, Option<String>) {
        let shared = self.shared.lock().unwrap();
        (shared.status.clone(), shared.error.clone())
    }

    /// Voice or language changed: translate again from the current position.
    pub fn restart(&self) {
        restart(&mut self.shared.lock().unwrap(), None);
    }

    pub fn done(&self) -> bool {
        self.threads.iter().all(|thread| thread.is_finished())
    }

    pub fn stop(&self) {
        self.shared.lock().unwrap().stop = true;
    }
}

fn restart(shared: &mut Shared, position: Option<f64>) {
    let position = position.unwrap_or(shared.position);
    shared.generation += 1;
    shared.position = position;
    shared.cues.clear();
    shared.ready = position;
    shared.finished = false;
    shared.error = None;
}

fn decode(window: Window) -> Vec<Cue> {
    window
        .segments
        .into_iter()
        .filter_map(|segment| {
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(segment.wav)
                .ok()?;
            let audio = Arc::new(wav::decode(&bytes).ok()?);
            Some(Cue {
                id: segment.id,
                start: segment.start,
                duration: segment.duration,
                source_duration: segment.source_duration,
                text: segment.text,
                audio,
            })
        })
        .collect()
}

fn fetch(api: Api, file: String, settings: Arc<Mutex<Settings>>, shared: Arc<Mutex<Shared>>) {
    let (mut session, mut generation, mut ready, mut finished, mut failed) =
        (None::<String>, 0u64, 0.0, false, false);
    let mut heartbeat = Instant::now();
    loop {
        let (stop, wanted, position) = {
            let s = shared.lock().unwrap();
            (s.stop, s.generation, s.position)
        };
        if stop {
            break;
        }
        if wanted != generation {
            if let Some(id) = session.take() {
                api.close(&id);
            }
            generation = wanted;
            let body = settings.lock().unwrap().session();
            match api.open_file(&file, position, body) {
                Ok(opened) => {
                    (session, ready, finished, failed, heartbeat) = (
                        Some(opened.session_id),
                        opened.base,
                        false,
                        false,
                        Instant::now(),
                    );
                    let mut s = shared.lock().unwrap();
                    if s.generation == generation {
                        (s.ready, s.finished, s.duration) = (ready, false, opened.duration);
                    }
                }
                Err(error) => {
                    failed = true;
                    shared.lock().unwrap().error = Some(error.message);
                }
            }
            continue;
        }
        let Some(id) = session.as_deref().filter(|_| !failed) else {
            std::thread::sleep(Duration::from_millis(200));
            continue;
        };
        if !finished && ready < position + LOOKAHEAD {
            match retried(&shared, generation, || api.next(id, ready)) {
                Ok(window) => {
                    let (until, last) = (window.ready_until, window.finished);
                    let cues = decode(window);
                    let mut s = shared.lock().unwrap();
                    if s.generation == generation {
                        (ready, finished, heartbeat) = (until, last, Instant::now());
                        s.cues.extend(cues);
                        (s.ready, s.finished) = (ready, finished);
                    }
                }
                Err(error) => {
                    failed = true;
                    let mut s = shared.lock().unwrap();
                    if s.generation == generation {
                        s.error = Some(error.message);
                    }
                }
            }
        } else {
            // The engine closes sessions idle for two minutes, e.g. a long pause.
            if heartbeat.elapsed() > Duration::from_secs(15) {
                let _ = api.heartbeat(id);
                heartbeat = Instant::now();
            }
            std::thread::sleep(Duration::from_millis(200));
        }
    }
    if let Some(id) = session {
        api.close(&id);
    }
}

fn retried(
    shared: &Mutex<Shared>,
    generation: u64,
    mut call: impl FnMut() -> Result<Window, ApiError>,
) -> Result<Window, ApiError> {
    for delay in [2, 4, 6, 0] {
        match call() {
            Err(error) if error.transient() && delay > 0 => {
                let until = Instant::now() + Duration::from_secs(delay);
                while Instant::now() < until {
                    let s = shared.lock().unwrap();
                    if s.stop || s.generation != generation {
                        return Err(error);
                    }
                    drop(s);
                    std::thread::sleep(Duration::from_millis(100));
                }
            }
            result => return result,
        }
    }
    unreachable!()
}

struct Voice {
    id: u64,
    player: rodio::Player,
    started: Instant,
    offset: f64,
}

fn schedule(
    mpv_path: PathBuf,
    file: PathBuf,
    settings: Arc<Mutex<Settings>>,
    shared: Arc<Mutex<Shared>>,
) {
    let title = format!(
        "Synchro — {}",
        file.file_name()
            .map(|n| n.to_string_lossy())
            .unwrap_or_default()
    );
    let mut mpv = match Mpv::open(&mpv_path, &file, &title) {
        Ok(mpv) => mpv,
        Err(error) => {
            let mut s = shared.lock().unwrap();
            (s.error, s.stop) = (Some(error), true);
            return;
        }
    };
    // A short plain-text journal for support: state changes only, never transcripts' audio.
    let started = Instant::now();
    let journal = std::sync::Mutex::new(
        std::fs::File::create(crate::engine::log_path().with_file_name("player.log")).ok(),
    );
    let log = |text: String| {
        use std::io::Write;
        if let Some(file) = journal.lock().unwrap().as_mut() {
            let _ = writeln!(file, "{:8.2} {text}", started.elapsed().as_secs_f64());
        }
    };
    log(format!("open {}", file.display()));
    // Without an audio device the picture still plays; there is just no voice.
    let device = rodio::DeviceSinkBuilder::open_default_sink().ok();
    if device.is_none() {
        log("no audio output device; voice disabled".into());
    }
    let mut voice: Option<Voice> = None;
    let (mut wanted, mut held, mut preparing, mut speed) = (true, true, true, 1.0);
    let (mut last, mut generation, mut caption) = (None::<(f64, Instant)>, 0u64, None::<u64>);
    let (mut volume, mut duck_until, mut last_mix, mut notice) =
        (-1.0f64, Instant::now(), Instant::now(), Instant::now());
    let mut last_original = None;
    let stop_voice = |voice: &mut Option<Voice>| {
        if let Some(v) = voice.take() {
            v.player.stop()
        }
    };
    while mpv.alive() && !shared.lock().unwrap().stop {
        let Some(time) = mpv.number("time-pos") else {
            std::thread::sleep(Duration::from_millis(50));
            continue;
        };
        let paused = mpv.flag("pause").unwrap_or(true);
        let seeking = mpv.flag("seeking").unwrap_or(false);
        let now = Instant::now();
        let config = settings.lock().unwrap().clone();
        let mut s = shared.lock().unwrap();
        // A user seek (or a restart from settings) translates again from the new position.
        let jumped = last.is_some_and(|(at, when)| {
            let expected = if paused {
                at
            } else {
                at + when.elapsed().as_secs_f64() * speed
            };
            seeking || (time - expected).abs() > 1.5
        });
        if jumped {
            log(format!("seek to {time:.1}"));
            restart(&mut s, Some(time));
        }
        if s.generation != generation {
            generation = s.generation;
            preparing = true;
            stop_voice(&mut voice);
        }
        last = Some((time, now));
        s.position = time;
        // mpv's own pause button: playback the user stopped stays stopped; a press while we hold resumes intent.
        if paused && !held && wanted {
            let end = mpv.flag("eof-reached").unwrap_or(false);
            log(if end {
                format!("end of video at {time:.1}")
            } else {
                format!("paused by the viewer at {time:.1}")
            });
            wanted = false;
        }
        if !paused && held {
            held = false;
            wanted = true;
        }
        let (ready, finished, duration) = (s.ready, s.finished, s.duration.max(time + 0.2));
        if preparing && prepared(ready, time, duration, finished) {
            preparing = false;
        }
        if wanted && !paused && (preparing || starved(ready, time, finished)) {
            log(format!(
                "waiting for translation at {time:.1} (ready to {ready:.1})"
            ));
            mpv.set("pause", json!(true));
            held = true;
            stop_voice(&mut voice);
        } else if wanted
            && paused
            && held
            && !preparing
            && enough(ready, time, finished)
            && s.error.is_none()
        {
            log(format!("playing from {time:.1} (ready to {ready:.1})"));
            mpv.set("pause", json!(false));
            held = false;
        }
        let cue = cue_at(&s.cues, time);
        let rate = video_rate(cue);
        if (rate - speed).abs() > 1e-4 {
            log(format!("video speed {rate:.2} at {time:.1}"));
            stop_voice(&mut voice);
            mpv.set("speed", json!(rate));
            speed = rate;
        }
        let running = wanted && !paused && !seeking && !preparing;
        if !running {
            stop_voice(&mut voice);
        } else if let (Some(cue), Some(device)) = (cue, &device) {
            let due = (time - cue.start) / rate;
            let in_sync = voice.as_ref().is_some_and(|v| {
                v.id == cue.id && (v.offset + v.started.elapsed().as_secs_f64() - due).abs() < 0.25
            });
            if !in_sync && voice.as_ref().is_some_and(|v| v.id == cue.id) {
                stop_voice(&mut voice);
            }
            if voice.is_none() && due < cue.duration - 0.05 {
                let player = rodio::Player::connect_new(device.mixer());
                let audio = &cue.audio;
                if let (Some(channels), Some(sample_rate)) =
                    (NonZero::new(audio.channels), NonZero::new(audio.rate))
                {
                    player.append(
                        rodio::buffer::SamplesBuffer::new(
                            channels,
                            sample_rate,
                            audio.samples.clone(),
                        )
                        .skip_duration(Duration::from_secs_f64(due.max(0.0))),
                    );
                    log(format!(
                        "voice {} at {time:.2} from {:.2} s of {:.2} s",
                        cue.id,
                        due.max(0.0),
                        cue.duration
                    ));
                    voice = Some(Voice {
                        id: cue.id,
                        player,
                        started: now,
                        offset: due.max(0.0),
                    });
                }
            }
        }
        if let Some(v) = &voice {
            v.player.set_volume(config.voice_volume);
        }
        // Lower the original while the voice speaks, and bring it back smoothly in pauses.
        let speaking =
            config.voice_volume > 0.0 && voice.as_ref().is_some_and(|v| !v.player.empty());
        if speaking {
            duck_until = now + Duration::from_millis(300);
        }
        let ducked = config.duck_original
            && config.voice_volume > 0.0
            && running
            && (speaking || now < duck_until);
        let target = original_gain(config.original_volume, ducked);
        let changed = last_original != Some((config.original_volume, config.duck_original));
        last_original = Some((config.original_volume, config.duck_original));
        let dt = now.duration_since(last_mix).as_secs_f64().min(1.0);
        last_mix = now;
        let mixed = if volume < 0.0 || changed || target == 0.0 {
            target
        } else {
            volume + (target - volume) * (1.0 - (-dt / if ducked { 0.06 } else { 0.25 }).exp())
        };
        if changed || (mixed - volume).abs() > 0.0001 {
            mpv.set("volume", json!(mpv_volume(mixed)));
            volume = mixed;
        }
        if config.captions && running {
            if let Some(cue) = cue.filter(|cue| caption != Some(cue.id)) {
                let remaining =
                    ((cue.start + cue.source_duration - time) / rate * 1000.0).max(300.0) as u64;
                mpv.show(&cue.text, remaining);
                caption = Some(cue.id);
            }
        }
        s.status = if let Some(error) = &s.error {
            format!("Error: {error}")
        } else if preparing || held && wanted {
            "Translating ahead…".into()
        } else {
            format!(
                "Translated to {}:{:02}",
                (ready / 60.0) as u64,
                (ready % 60.0) as u64
            )
        };
        if (preparing || held && wanted || s.error.is_some())
            && notice.elapsed() > Duration::from_millis(900)
        {
            let text = format!("Synchro: {}", s.status);
            notice = now;
            drop(s);
            mpv.show(&text, 1000);
        } else {
            s.cues
                .retain(|cue| cue.start + cue.source_duration >= time - 30.0);
            drop(s);
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    stop_voice(&mut voice);
    mpv.quit();
    shared.lock().unwrap().stop = true;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn original_volume_matches_linear_voice_gain_and_ducking_is_audible() {
        for gain in [0.0, 0.1, 0.5, 1.0] {
            assert!(((mpv_volume(gain) / 100.0).powi(3) - gain).abs() < 1e-9);
        }
        assert_eq!(original_gain(1.0, true), 0.5);
        assert_eq!(original_gain(1.0, false), 1.0);
        assert_eq!(original_gain(0.0, true), 0.0);
        assert!(mpv_volume(original_gain(0.5, true)) > 60.0);
    }

    fn cue(id: u64, start: f64, source: f64, voice: f64) -> Cue {
        Cue {
            id,
            start,
            duration: voice,
            source_duration: source,
            text: String::new(),
            audio: Arc::new(Pcm {
                samples: vec![],
                rate: 48000,
                channels: 1,
            }),
        }
    }

    #[test]
    fn long_phrases_slow_the_video_and_pauses_keep_normal_speed() {
        let cues = vec![cue(1, 10.0, 2.0, 4.0), cue(2, 13.0, 3.0, 3.0)];
        assert_eq!(cue_at(&cues, 11.0).map(|c| c.id), Some(1));
        assert!(cue_at(&cues, 12.5).is_none());
        assert_eq!(video_rate(cue_at(&cues, 11.0)), 0.5);
        assert_eq!(video_rate(cue_at(&cues, 12.5)), 1.0);
        assert_eq!(video_rate(Some(&cue(3, 0.0, 10.0, 0.1))), 16.0);
    }

    #[test]
    fn playback_waits_for_translation_ahead() {
        assert!(!prepared(5.0, 0.0, 600.0, false));
        assert!(prepared(10.0, 0.0, 600.0, false));
        assert!(prepared(4.0, 0.0, 4.0, true));
        assert!(starved(31.0, 30.0, false) && !starved(31.0, 30.0, true));
        assert!(!enough(31.0, 30.0, false) && enough(31.3, 30.0, false));
    }
}
