//! The watch screen shares one surface between the picture, subtitles and playback controls.
use crate::{App, EngineState, ui};
use eframe::egui::{
    self, Align, Align2, Color32, FontId, Frame, Key, Layout, Rect, RichText, Sense, Stroke, Vec2,
};
use std::time::{Duration, Instant};

const CHROME: Color32 = Color32::from_rgb(20, 30, 27);
const WELL: Color32 = Color32::from_rgb(12, 19, 17);
const MINT: Color32 = Color32::from_rgb(159, 225, 192);
const SOFT: Color32 = Color32::from_rgb(175, 193, 184);

#[derive(Default)]
pub(crate) struct Theater {
    frame: Option<egui::TextureHandle>,
    pub voices_tab: bool,
    epoch: u64,
    scrub: Option<f64>,
    active: Option<Instant>,
}

fn timestamp(t: f64) -> String {
    let t = t.max(0.0) as u64;
    if t >= 3600 {
        format!("{}:{:02}:{:02}", t / 3600, t / 60 % 60, t % 60)
    } else {
        format!("{}:{:02}", t / 60, t % 60)
    }
}

fn section_frame() -> Frame {
    Frame::new()
        .fill(CHROME)
        .inner_margin(egui::Margin::symmetric(22, 9))
}

impl App {
    pub(crate) fn theater_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        let ctx = ui.ctx().clone();
        let full = ctx.input(|i| i.viewport().fullscreen.unwrap_or(false));
        let (time, duration, wanted, epoch, caption) =
            self.player.as_ref().map(|p| p.view()).unwrap_or_default();
        if let Some(p) = &self.player {
            ctx.request_repaint_after(Duration::from_millis(16));
            if self.theater.epoch != epoch {
                self.theater.epoch = epoch;
                self.theater.frame = None;
            }
            if let Some(image) = p.picture.take(epoch) {
                if let Some(texture) = &mut self.theater.frame {
                    texture.set(image, egui::TextureOptions::LINEAR);
                } else {
                    self.theater.frame =
                        Some(ctx.load_texture("video", image, egui::TextureOptions::LINEAR));
                }
            }
            let global_keys = ctx.memory(|m| m.focused().is_none());
            if global_keys && ctx.input_mut(|i| i.consume_key(egui::Modifiers::NONE, Key::Space)) {
                p.toggle();
            }
            if global_keys && ctx.input(|i| i.modifiers.is_none() && i.key_pressed(Key::ArrowLeft))
            {
                p.seek(time - 5.0);
            }
            if global_keys && ctx.input(|i| i.modifiers.is_none() && i.key_pressed(Key::ArrowRight))
            {
                p.seek(time + 5.0);
            }
            if ctx.input(|i| i.modifiers.is_none() && i.key_pressed(Key::Q)) {
                p.stop();
            }
            if ctx.input(|i| {
                i.modifiers.is_none() && i.key_pressed(Key::F) || full && i.key_pressed(Key::Escape)
            }) {
                ctx.send_viewport_cmd(egui::ViewportCommand::Fullscreen(!full));
            }
        }
        if ctx.input(|i| {
            i.pointer.delta() != Vec2::ZERO
                || i.pointer.any_down()
                || i.events
                    .iter()
                    .any(|e| matches!(e, egui::Event::Key { .. } | egui::Event::MouseWheel { .. }))
        }) {
            self.theater.active = Some(Instant::now());
        }
        let visible = !full
            || !wanted
            || self.playback_error.is_some()
            || self
                .theater
                .active
                .get_or_insert_with(Instant::now)
                .elapsed()
                < Duration::from_secs(3);

        if !full {
            egui::Panel::top("theater_header")
                .frame(section_frame())
                .show(ui, |ui| {
                    ui.horizontal(|ui| {
                        let width = ui.available_width();
                        let (mark, _) =
                            ui.allocate_exact_size(egui::vec2(22.0, 28.0), Sense::hover());
                        for (i, height) in [11.0, 23.0, 16.0, 8.0].into_iter().enumerate() {
                            let x = mark.left() + 2.0 + i as f32 * 5.5;
                            let y = mark.center().y;
                            ui.painter().line_segment(
                                [
                                    egui::pos2(x, y - height / 2.0),
                                    egui::pos2(x, y + height / 2.0),
                                ],
                                Stroke::new(2.8, MINT),
                            );
                        }
                        ui.label(RichText::new("Synchro").size(22.0).strong());
                        ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                            if ui.button(l.text("Open video")).clicked() {
                                self.pick_video();
                            }
                        });
                        if let Some(path) = self.pending.as_ref().or(self.current_file.as_ref()) {
                            let center = ui.max_rect().center();
                            let rect = Rect::from_center_size(
                                center,
                                egui::vec2((width - 310.0).max(40.0), 32.0),
                            );
                            let name = path.file_name().unwrap_or_default().to_string_lossy();
                            ui.scope_builder(
                                egui::UiBuilder::new().max_rect(rect).layout(
                                    Layout::centered_and_justified(egui::Direction::LeftToRight),
                                ),
                                |ui| {
                                    ui.add(
                                        egui::Label::new(RichText::new(&*name).strong()).truncate(),
                                    )
                                    .on_hover_text(path.display().to_string());
                                },
                            );
                        }
                    });
                });
        }

        if !full {
            egui::Panel::bottom("transport")
                .frame(section_frame())
                .show(ui, |ui| self.transport(ui, time, duration, wanted, full));
        }
        egui::CentralPanel::default()
            .frame(Frame::new().fill(WELL))
            .show(ui, |ui| {
                let canvas = ui.max_rect();
                let has_player = self.player.is_some();
                let mut image_rect = canvas;
                if let Some(tex) = &self.theater.frame {
                    let size = tex.size_vec2();
                    image_rect = Rect::from_center_size(
                        canvas.center(),
                        size * (canvas.width() / size.x).min(canvas.height() / size.y),
                    );
                    ui.painter().image(
                        tex.id(),
                        image_rect,
                        Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
                        Color32::WHITE,
                    );
                }
                let controls_height = if full && visible { 140.0 } else { 0.0 };
                if has_player {
                    let video_hit = Rect::from_min_max(
                        canvas.min,
                        egui::pos2(canvas.right(), canvas.bottom() - controls_height),
                    );
                    let hit = ui.interact(video_hit, ui.scope_id().with("picture"), Sense::click());
                    if hit.double_clicked() {
                        ctx.send_viewport_cmd(egui::ViewportCommand::Fullscreen(!full));
                    }
                    if self.edited.captions
                        && let Some(text) = caption.filter(|s| !s.is_empty())
                    {
                        let p = ui.painter();
                        let galley = p.layout(
                            text,
                            FontId::proportional((canvas.width() / 49.0).clamp(17.0, 30.0)),
                            Color32::WHITE,
                            image_rect.width() * 0.84,
                        );
                        let bottom =
                            image_rect.bottom().min(canvas.bottom() - controls_height) - 22.0;
                        let rect = Align2::CENTER_BOTTOM
                            .anchor_size(egui::pos2(image_rect.center().x, bottom), galley.size());
                        p.rect_filled(
                            rect.expand2(egui::vec2(13.0, 7.0)),
                            5,
                            Color32::from_black_alpha(210),
                        );
                        p.galley(rect.min, galley, Color32::WHITE);
                    }
                    if self.theater.frame.is_none()
                        || self.playback_error.is_some()
                        || self.playback_status == "Translating ahead…"
                    {
                        let msg = self
                            .playback_error
                            .as_deref()
                            .unwrap_or(&self.playback_status);
                        let mut area = ui.new_child(
                            egui::UiBuilder::new()
                                .max_rect(canvas.shrink2(egui::vec2(20.0, 16.0)))
                                .layout(Layout::top_down(Align::Min)),
                        );
                        Frame::new()
                            .fill(Color32::from_black_alpha(210))
                            .inner_margin(8)
                            .corner_radius(5)
                            .show(&mut area, |ui| {
                                ui.label(l.message(msg));
                                if self.playback_error.is_some()
                                    && ui.button(l.text("Retry")).clicked()
                                    && let Some(p) = &self.player
                                {
                                    p.restart();
                                }
                            });
                    }
                } else {
                    let center = canvas.center();
                    let bounds = Rect::from_center_size(
                        center,
                        egui::vec2((canvas.width() - 38.0).min(550.0), 170.0),
                    );
                    let mut area = ui.new_child(
                        egui::UiBuilder::new()
                            .max_rect(bounds)
                            .layout(Layout::top_down(Align::Center)),
                    );
                    area.add_space(12.0);
                    area.label(
                        RichText::new(l.text("Watch with Russian voiceover"))
                            .size(25.0)
                            .strong(),
                    );
                    let error = match &*self.engine.lock().unwrap() {
                        EngineState::Failed(s) => Some(s.clone()),
                        _ => self.playback_error.clone(),
                    };
                    let hint = if let Some(error) = error.as_ref().or(self.notice.as_ref()) {
                        l.message(error)
                    } else if self.pending.is_some() {
                        l.text("Video selected · waiting to start").into()
                    } else if ctx.input(|i| !i.raw.hovered_files.is_empty()) {
                        l.text("Drop your video here").into()
                    } else {
                        l.text("Drop a video here, or choose a file to get started.")
                            .into()
                    };
                    area.label(RichText::new(hint).color(SOFT));
                    area.add_space(12.0);
                    if area
                        .add(
                            egui::Button::new(
                                RichText::new(l.text("Open video")).strong().color(WELL),
                            )
                            .fill(MINT)
                            .min_size(egui::vec2(148.0, 40.0)),
                        )
                        .clicked()
                    {
                        self.pick_video();
                    }
                    if self.edited.connection_error().is_some()
                        && area.link(l.text("Set up translation")).clicked()
                    {
                        self.translation_page = true;
                    }
                }
                if full && visible {
                    let panel = Rect::from_min_max(
                        egui::pos2(canvas.left(), canvas.bottom() - controls_height),
                        canvas.max,
                    );
                    let mut overlay = ui.new_child(egui::UiBuilder::new().max_rect(panel));
                    section_frame().show(&mut overlay, |ui| {
                        self.transport(ui, time, duration, wanted, full)
                    });
                } else if full {
                    ctx.set_cursor_icon(egui::CursorIcon::None);
                }
            });
    }

    fn transport(&mut self, ui: &mut egui::Ui, time: f64, duration: f64, wanted: bool, full: bool) {
        let l = self.edited.interface_language;
        let mut position = self.theater.scrub.unwrap_or(time);
        ui.spacing_mut().slider_width = ui.available_width();
        ui.spacing_mut().interact_size.y = 23.0;
        let bar = ui
            .scope(|ui| {
                ui.visuals_mut().selection.bg_fill = MINT;
                ui.add_enabled(
                    duration > 0.0,
                    egui::Slider::new(&mut position, 0.0..=duration.max(0.01)).show_value(false),
                )
                .on_hover_text(l.text("Seek"))
            })
            .inner;
        if bar.dragged() {
            self.theater.scrub = Some(position);
        }
        if bar.drag_stopped() || bar.changed() && !bar.dragged() {
            if let Some(p) = &self.player {
                p.seek(position);
            }
            self.theater.scrub = None;
        }
        ui.horizontal(|ui| {
            let label = if wanted {
                l.text("Pause")
            } else {
                l.text("Play")
            };
            if ui
                .add_enabled(self.player.is_some(), egui::Button::new(label))
                .clicked()
                && let Some(p) = &self.player
            {
                p.toggle();
            }
            ui.monospace(format!("{} / {}", timestamp(position), timestamp(duration)));
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui
                    .add_enabled(
                        self.player.is_some(),
                        egui::Button::new(if full {
                            l.text("Exit full screen")
                        } else {
                            l.text("Full screen")
                        }),
                    )
                    .clicked()
                {
                    ui.ctx()
                        .send_viewport_cmd(egui::ViewportCommand::Fullscreen(!full));
                    self.theater.active = Some(Instant::now());
                }
                ui.toggle_value(&mut self.edited.captions, l.text("Subtitles"));
                if let Some(p) = &self.player
                    && ui.button(l.text("Close video")).clicked()
                {
                    p.stop();
                }
            });
        });
        ui.separator();
        ui.horizontal_top(|ui| {
            let slider_width = ((ui.available_width() - 220.0) / 2.0 - 22.0).clamp(125.0, 210.0);
            for (label, value) in [
                (l.text("Original audio"), &mut self.edited.original_volume),
                (l.text("Voiceover"), &mut self.edited.voice_volume),
            ] {
                ui.allocate_ui_with_layout(
                    Vec2::new(slider_width, 0.0),
                    Layout::top_down(Align::Min),
                    |ui| {
                        ui.visuals_mut().selection.bg_fill = MINT;
                        ui::volume(ui, label, value);
                    },
                );
            }
            ui.with_layout(Layout::right_to_left(Align::Center), |ui| {
                if ui.button(l.text("Voices & translation")).clicked() {
                    self.theater.voices_tab = self.edited.connection_error().is_none();
                    if full {
                        ui.ctx()
                            .send_viewport_cmd(egui::ViewportCommand::Fullscreen(false));
                    }
                    self.translation_page = true;
                }
            });
        });
    }
}
