use crate::i18n::Language;
use super::{App, CheckState, EngineState};
use crate::config::{LANGUAGES, PROVIDERS, VOICES, label};
use crate::provider::Fetch;
use eframe::egui::{self, Color32, FontId, RichText, Stroke, Vec2};

const BG: Color32 = Color32::from_rgb(22, 25, 28);
const SURFACE: Color32 = Color32::from_rgb(30, 34, 38);
const FIELD: Color32 = Color32::from_rgb(38, 43, 47);
const BORDER: Color32 = Color32::from_rgb(55, 62, 66);
const TEXT: Color32 = Color32::from_rgb(234, 238, 237);
const MUTED: Color32 = Color32::from_rgb(157, 169, 172);
const ACCENT: Color32 = Color32::from_rgb(137, 205, 177);
const INK: Color32 = Color32::from_rgb(23, 43, 35);
const ERROR: Color32 = Color32::from_rgb(242, 160, 151);
const OPEN_SHORTCUT: &str = if cfg!(target_os = "macos") { "⌘ O" } else { "Ctrl + O" };

pub fn icon() -> egui::IconData {
    let mut rgba = BG.to_array().repeat(64 * 64);
    for (index, height) in [20, 44, 30, 14].into_iter().enumerate() {
        for y in (64 - height) / 2..(64 + height) / 2 {
            for x in 12 + index * 12..16 + index * 12 {
                let pixel = (y * 64 + x) * 4;
                rgba[pixel..pixel + 4].copy_from_slice(&ACCENT.to_array());
            }
        }
    }
    egui::IconData {
        rgba,
        width: 64,
        height: 64,
    }
}

pub fn configure(ctx: &egui::Context) {
    let mut style = egui::Style {
        visuals: egui::Visuals::dark(),
        ..Default::default()
    };
    style.visuals.panel_fill = BG;
    style.visuals.window_fill = SURFACE;
    style.visuals.extreme_bg_color = FIELD;
    style.visuals.text_edit_bg_color = Some(FIELD);
    style.visuals.faint_bg_color = SURFACE;
    style.visuals.override_text_color = Some(TEXT);
    style.visuals.weak_text_color = Some(MUTED);
    style.visuals.selection.bg_fill = Color32::from_rgb(52, 87, 72);
    style.visuals.selection.stroke = Stroke::new(1.0, ACCENT);
    style.visuals.hyperlink_color = ACCENT;
    style.visuals.error_fg_color = ERROR;
    style.visuals.slider_trailing_fill = true;
    style.visuals.interact_cursor = Some(egui::CursorIcon::PointingHand);
    style.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, BORDER);
    for widget in [
        &mut style.visuals.widgets.inactive,
        &mut style.visuals.widgets.hovered,
        &mut style.visuals.widgets.active,
        &mut style.visuals.widgets.open,
    ] {
        widget.corner_radius = 7.into();
        widget.fg_stroke = Stroke::new(1.5, TEXT);
        widget.bg_stroke = Stroke::new(1.0, BORDER);
    }
    style.visuals.widgets.inactive.weak_bg_fill = FIELD;
    style.visuals.widgets.inactive.bg_fill = FIELD;
    style.visuals.widgets.hovered.weak_bg_fill = Color32::from_rgb(49, 59, 59);
    style.visuals.widgets.hovered.bg_fill = Color32::from_rgb(49, 59, 59);
    style.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, ACCENT);
    style.visuals.widgets.active.bg_fill = ACCENT;
    style.visuals.widgets.active.weak_bg_fill = Color32::from_rgb(55, 83, 70);
    style.spacing.item_spacing = Vec2::new(12.0, 8.0);
    style.spacing.button_padding = Vec2::new(14.0, 8.0);
    style.spacing.interact_size.y = 32.0;
    style.spacing.combo_height = 240.0;
    style.animation_time = 0.16;
    style
        .text_styles
        .insert(egui::TextStyle::Body, FontId::proportional(15.0));
    style
        .text_styles
        .insert(egui::TextStyle::Button, FontId::proportional(15.0));
    style
        .text_styles
        .insert(egui::TextStyle::Small, FontId::proportional(12.0));
    style
        .text_styles
        .insert(egui::TextStyle::Heading, FontId::proportional(26.0));
    ctx.set_theme(egui::ThemePreference::Dark);
    ctx.set_style_of(egui::Theme::Dark, style);
    // Use the platform font when available; egui's bundled fonts remain the fallback.
    let system_font = if cfg!(target_os = "macos") { "/System/Library/Fonts/SFNS.ttf" } else { "C:\\Windows\\Fonts\\segoeui.ttf" };
    if let Ok(bytes) = std::fs::read(system_font) {
        let mut fonts = egui::FontDefinitions::default();
        fonts
            .font_data
            .insert("system".into(), egui::FontData::from_owned(bytes).into());
        fonts
            .families
            .entry(egui::FontFamily::Proportional)
            .or_default()
            .insert(0, "system".into());
        ctx.set_fonts(fonts);
    }
}

fn muted(ui: &mut egui::Ui, text: &str) {
    ui.label(RichText::new(text).color(MUTED));
}

fn section(ui: &mut egui::Ui, title: &str, description: &str) {
    ui.label(RichText::new(title).size(19.0).strong());
    muted(ui, description);
    ui.add_space(8.0);
}

fn primary(ui: &mut egui::Ui, text: &str) -> egui::Response {
    ui.add(
        egui::Button::new(RichText::new(text).color(INK).strong())
            .fill(ACCENT)
            .stroke(Stroke::NONE)
            .min_size(Vec2::new(154.0, 42.0)),
    )
}

fn select(ui: &mut egui::Ui, l: Language, id: &str, title: &str, value: &mut String, items: &[(&str, &str)]) {
    ui.label(title);
    egui::ComboBox::from_id_salt(id)
        .width(ui.available_width())
        .selected_text(l.text(label(items, value)))
        .show_ui(ui, |ui| {
            for (id, name) in items {
                ui.selectable_value(value, id.to_string(), l.text(name));
            }
        });
}

fn volume(ui: &mut egui::Ui, title: &str, value: &mut f32) {
    let height = ui.spacing().interact_size.y;
    ui.spacing_mut().interact_size.y = 20.0;
    ui.horizontal(|ui| {
        ui.label(title);
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.label(
                RichText::new(format!("{:.0}%", *value * 100.0))
                    .monospace()
                    .color(MUTED),
            );
        });
    });
    ui.spacing_mut().slider_width = ui.available_width();
    ui.add(egui::Slider::new(value, 0.0..=1.0).show_value(false))
        .on_hover_text(title)
        .widget_info(|| egui::WidgetInfo::labeled(egui::Role::Slider, true, title));
    ui.spacing_mut().interact_size.y = height;
}

fn badge(ui: &mut egui::Ui, text: &str, color: Color32) {
    ui.horizontal(|ui| {
        let (rect, _) = ui.allocate_exact_size(Vec2::splat(8.0), egui::Sense::hover());
        ui.painter().circle_filled(rect.center(), 3.0, color);
        ui.label(RichText::new(text).color(color).size(12.0));
    });
}

impl App {
    pub(super) fn draw(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        egui::Panel::top("header")
            .frame(
                egui::Frame::new()
                    .fill(SURFACE)
                    .inner_margin(egui::Margin::symmetric(28, 14)),
            )
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    let (rect, _) =
                        ui.allocate_exact_size(Vec2::new(29.0, 29.0), egui::Sense::hover());
                    for (i, height) in [12.0, 24.0, 17.0, 8.0].iter().enumerate() {
                        let x = rect.left() + 3.0 + i as f32 * 7.0;
                        ui.painter().line_segment(
                            [
                                egui::pos2(x, rect.center().y - height / 2.0),
                                egui::pos2(x, rect.center().y + height / 2.0),
                            ],
                            Stroke::new(3.0, ACCENT),
                        );
                    }
                    ui.label(RichText::new("Synchro").size(23.0).strong());
                    ui.add_space(14.0);
                    if ui
                        .add(egui::Button::new(l.text("Watch")).selected(!self.translation_page))
                        .clicked()
                    {
                        self.translation_page = false;
                    }
                    if ui
                        .add(egui::Button::new(l.text("Translation")).selected(self.translation_page))
                        .clicked()
                    {
                        self.translation_page = true;
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        let (text, color) = match &*self.engine.lock().unwrap() {
                            EngineState::Starting => (l.text("Engine starting"), MUTED),
                            EngineState::Ready(_)
                                if matches!(
                                    self.check.lock().unwrap().state,
                                    CheckState::Running
                                ) =>
                            {
                                (l.text("Preparing speech"), MUTED)
                            }
                            EngineState::Ready(_) => (l.text("Engine ready"), ACCENT),
                            EngineState::Failed(_) => (l.text("Engine unavailable"), ERROR),
                        };
                        let (rect, _) =
                            ui.allocate_exact_size(Vec2::splat(8.0), egui::Sense::hover());
                        ui.painter().circle_filled(rect.center(), 3.0, color);
                        ui.label(RichText::new(text).color(color).size(12.0));
                    });
                });
            });

        egui::Panel::bottom("footer")
            .frame(
                egui::Frame::new()
                    .fill(BG)
                    .inner_margin(egui::Margin::symmetric(28, 10)),
            )
            .show(ui, |ui| {
                ui.horizontal_wrapped(|ui| {
                    ui.label(l.text("Language"));
                    egui::ComboBox::from_id_salt("interface_language")
                        .width(90.0)
                        .selected_text(match self.edited.interface_language {
                            Language::English => "English",
                            Language::Russian => "Русский",
                        })
                        .show_ui(ui, |ui| {
                            ui.selectable_value(&mut self.edited.interface_language, Language::English, "English");
                            ui.selectable_value(&mut self.edited.interface_language, Language::Russian, "Русский");
                        }).response.on_hover_text(l.text("Interface language"));
                    if let Some(error) = &self.save_error {
                        ui.colored_label(ERROR, l.text("Settings could not be saved"))
                            .on_hover_text(l.message(error));
                        if ui.small_button(l.text("Retry")).clicked() {
                            self.save_error = self.edited.save().err();
                        }
                    } else {
                        ui.label(
                            RichText::new(l.text("Settings save automatically"))
                                .small()
                                .color(MUTED),
                        );
                    }
                    ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                        ui.label(
                            RichText::new(format!("{} {}", l.text("Desktop"), env!("CARGO_PKG_VERSION")))
                                .small()
                                .color(MUTED),
                        );
                    });
                });
            });

        egui::CentralPanel::default()
            .frame(egui::Frame::new().fill(BG).inner_margin(28))
            .show(ui, |ui| {
                egui::ScrollArea::vertical()
                    .id_salt("workspace")
                    .auto_shrink([false, false])
                    .show(ui, |ui| {
                        ui.set_width(ui.available_width());
                        let engine_error = match &*self.engine.lock().unwrap() {
                            EngineState::Failed(e) => Some(e.clone()),
                            _ => None,
                        };
                        if let Some(error) = engine_error {
                            ui.colored_label(ERROR, l.text("The speech engine could not start."));
                            egui::CollapsingHeader::new(l.text("Show details")).show(ui, |ui| {
                                ui.label(l.message(&error));
                                ui.label(format!("{}{}", l.text("Log: "), crate::engine::log_path().display()));
                            });
                            ui.add_space(12.0);
                        }
                        if let Some(notice) = self.notice.clone() {
                            ui.horizontal_wrapped(|ui| {
                                ui.colored_label(ERROR, l.message(&notice));
                                if ui.small_button(l.text("Dismiss")).clicked() {
                                    self.notice = None;
                                }
                            });
                            ui.add_space(12.0);
                        }
                        if self.translation_page {
                            self.translation_ui(ui);
                        } else {
                            self.watch_ui(ui);
                        }
                    });
            });
    }

    fn watch_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        ui.heading(l.text("Watch with Russian voiceover"));
        muted(ui, l.text("Your videos, with synchronized Russian voiceover."));
        ui.add_space(18.0);
        if ui.available_width() >= 850.0 {
            let left = ui.available_width() - 320.0;
            ui.horizontal_top(|ui| {
                ui.spacing_mut().item_spacing.x = 20.0;
                ui.allocate_ui_with_layout(
                    Vec2::new(left, 0.0),
                    egui::Layout::top_down(egui::Align::Min),
                    |ui| {
                        self.video_ui(ui);
                    },
                );
                ui.allocate_ui_with_layout(
                    Vec2::new(300.0, 0.0),
                    egui::Layout::top_down(egui::Align::Min),
                    |ui| {
                        self.playback_ui(ui);
                    },
                );
            });
        } else {
            self.video_ui(ui);
            ui.add_space(18.0);
            self.playback_ui(ui);
        }
    }

    fn video_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        let hovered = ui.ctx().input(|i| !i.raw.hovered_files.is_empty());
        let compact = ui.available_width() < 650.0;
        egui::Frame::new()
            .fill(SURFACE)
            .stroke(Stroke::new(1.0, if hovered { ACCENT } else { BORDER }))
            .corner_radius(14)
            .inner_margin(24)
            .show(ui, |ui| {
                ui.set_width((ui.available_width()).max(100.0));
                ui.vertical_centered(|ui| {
                    ui.add_space(if compact { 4.0 } else { 22.0 });
                    let (rect, _) = ui.allocate_exact_size(
                        Vec2::new(68.0, if compact { 44.0 } else { 56.0 }),
                        egui::Sense::hover(),
                    );
                    let painter = ui.painter();
                    painter.rect_stroke(
                        rect.shrink(2.0),
                        9,
                        Stroke::new(1.5, MUTED),
                        egui::StrokeKind::Inside,
                    );
                    let c = rect.center();
                    painter.add(egui::Shape::convex_polygon(
                        vec![
                            c + egui::vec2(-5.0, -10.0),
                            c + egui::vec2(10.0, 0.0),
                            c + egui::vec2(-5.0, 10.0),
                        ],
                        ACCENT,
                        Stroke::NONE,
                    ));
                    ui.add_space(14.0);
                    let file = self.pending.as_ref().or(self.current_file.as_ref());
                    let title = file
                        .and_then(|p| p.file_name())
                        .map(|s| s.to_string_lossy().into_owned());
                    ui.add(
                        egui::Label::new(
                            RichText::new(title.as_deref().unwrap_or(l.text("Open a video to begin")))
                                .size(20.0)
                                .strong(),
                        )
                        .wrap(),
                    );
                    if let Some(file) = file {
                        ui.add(
                            egui::Label::new(
                                RichText::new(if self.pending.is_some() {
                                    l.text("Video selected · waiting to start")
                                } else if self.player.is_some() {
                                    l.text("Playing in the video window")
                                } else {
                                    l.text("Video closed")
                                })
                                .color(MUTED),
                            )
                            .wrap(),
                        )
                        .on_hover_text(file.display().to_string());
                    } else {
                        muted(
                            ui,
                            if hovered {
                                l.text("Drop your video here")
                            } else {
                                l.text("Drop a video here, or choose a file to get started.")
                            },
                        );
                    }
                    ui.add_space(14.0);
                    if primary(
                        ui,
                        if self.current_file.is_some() {
                            l.text("Open another video")
                        } else {
                            l.text("Open video")
                        },
                    )
                    .on_hover_text(format!("{} · {OPEN_SHORTCUT}", l.text("Choose a local video file")))
                    .clicked()
                    {
                        self.pick_video();
                    }
                    ui.label(RichText::new(OPEN_SHORTCUT).small().color(MUTED));
                    if !compact {
                        ui.add_space(12.0);
                        ui.label(
                            RichText::new(l.text("MP4 · MKV · AVI · MOV · WebM + more"))
                                .small()
                                .color(MUTED),
                        );
                    }
                    ui.add_space(8.0);
                });
            });
        ui.add_space(14.0);
        if self.edited.connection_error().is_some() {
            ui.label(RichText::new(l.text("One quick setup before you watch")).strong());
            muted(ui, l.text("Connect a translation provider or a local model."));
            if ui.button(l.text("Set up translation")).clicked() {
                self.translation_page = true;
            }
        } else if self.current_file.is_some() {
            ui.horizontal_wrapped(|ui| {
                ui.label(RichText::new(l.message(&self.playback_status)).color(
                    if self.playback_error.is_some() {
                        ERROR
                    } else {
                        ACCENT
                    },
                ));
                if let Some(player) = &self.player
                    && ui.button(l.text("Stop video")).clicked()
                {
                    player.stop();
                }
            });
            if let Some(error) = &self.playback_error {
                ui.colored_label(ERROR, l.message(error.as_ref()));
            }
        } else {
            badge(ui, l.text("Translation configured"), ACCENT);
        }
        ui.add_space(18.0);
        self.spending_ui(ui);
        egui::CollapsingHeader::new(l.text("Playback shortcuts")).show(ui, |ui| {
            for (key, action) in [
                (l.text("Space"), l.text("Pause / play")),
                (l.text("Left / Right"), l.text("Seek 5 seconds")),
                (l.text("F / double-click"), l.text("Full screen")),
                ("Q", l.text("Close video")),
            ] {
                ui.horizontal(|ui| {
                    ui.add_sized(
                        [145.0, 20.0],
                        egui::Label::new(RichText::new(l.text(key)).color(TEXT)),
                    );
                    muted(ui, l.text(action));
                });
            }
            muted(ui, l.text("Use these shortcuts in the video window."));
        });
    }

    fn playback_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        egui::Frame::new().fill(SURFACE).stroke(Stroke::new(1.0, BORDER)).corner_radius(14).inner_margin(22).show(ui, |ui| {
            ui.spacing_mut().item_spacing.y = 6.0;
            ui.label(RichText::new(l.text("Voiceover")).size(19.0).strong());
            ui.add_space(6.0);
            select(ui, l, "language", l.text("Video language"), &mut self.edited.language, &LANGUAGES);
            ui.label(l.text("Voice mode"));
            ui.horizontal_wrapped(|ui| {
                ui.radio_value(&mut self.edited.match_voice, false, l.text("One voice"))
                    .on_hover_text(l.text("Use one selected voice for all speakers. Speaker grammar can still follow the original voices."));
                ui.radio_value(&mut self.edited.match_voice, true, l.text("By speaker"))
                    .on_hover_text(l.text("Assign a separate voice for female and male speakers."));
            });
            if self.edited.match_voice {
                let female = VOICES[..2].iter().any(|(id, _)| *id == self.edited.voice);
                let female_default = if female { self.edited.voice.clone() } else { "albina".into() };
                let male_default = if female { "roman".into() } else { self.edited.voice.clone() };
                select(ui, l, "female_voice", l.text("Female speaker"), self.edited.female_voice.get_or_insert(female_default), &VOICES[..2]);
                select(ui, l, "male_voice", l.text("Male speaker"), self.edited.male_voice.get_or_insert(male_default), &VOICES[2..]);
                ui.label(RichText::new(format!("{} {}.", l.text("Uncertain speakers use"), l.text(label(&VOICES, &self.edited.voice)))).small().color(MUTED));
            } else {
                select(ui, l, "voice", l.text("Russian voice"), &mut self.edited.voice, &VOICES);
            }
            egui::CollapsingHeader::new(l.text("Speaker grammar")).show(ui, |ui| {
                select(ui, l, "speaker_gender", l.text("Speaker grammar"), &mut self.edited.speaker_gender,
                    &[("auto", l.text("Auto · from voice")), ("female", l.text("Feminine")), ("male", l.text("Masculine")), ("off", l.text("Use text only"))]);
                ui.label(RichText::new(l.text("Acoustic cues guide first-person grammar. For ambiguous voices, choose Feminine or Masculine.")).small().color(MUTED));
            });
            ui.label(RichText::new(l.text("Changes apply while you watch.")).small().color(MUTED))
                .on_hover_text(l.text("Changing the voice or video language restarts translation from the current position."));
            ui.separator();
            volume(ui, l.text("Voiceover volume"), &mut self.edited.voice_volume);
            volume(ui, l.text("Original audio"), &mut self.edited.original_volume);
            ui.label(RichText::new(l.text("Volume changes apply immediately.")).small().color(MUTED));
            ui.checkbox(&mut self.edited.duck_original, l.text("Lower original during voiceover"))
                .on_hover_text(l.text("Keeps half the selected original volume during translated speech. Turn off to keep the original at full selected volume."));
            ui.separator();
            ui.checkbox(&mut self.edited.captions, l.text("Show translated captions"));
        });
    }

    fn translation_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        ui.heading(l.text("Translation"));
        muted(ui, l.text("Choose where the original speech is translated."));
        ui.add_space(18.0);
        let wide = ui.available_width() >= 850.0;
        if wide {
            let left = ui.available_width() - 320.0;
            ui.horizontal_top(|ui| {
                ui.spacing_mut().item_spacing.x = 20.0;
                ui.allocate_ui_with_layout(
                    Vec2::new(left, 0.0),
                    egui::Layout::top_down(egui::Align::Min),
                    |ui| {
                        self.connection_ui(ui);
                    },
                );
                ui.allocate_ui_with_layout(
                    Vec2::new(300.0, 0.0),
                    egui::Layout::top_down(egui::Align::Min),
                    |ui| {
                        self.account_ui(ui);
                        ui.add_space(16.0);
                        privacy_ui(ui, l);
                    },
                );
            });
        } else {
            self.connection_ui(ui);
            ui.add_space(18.0);
            self.account_ui(ui);
            ui.add_space(18.0);
            privacy_ui(ui, l);
        }
    }

    fn models_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        ui.label(l.text("Model"));
        let models = self.providers.models.lock().unwrap().clone();
        match models {
            Fetch::Ready(Ok(models), _) => {
                let selected = models.iter().find(|model| model.id == self.edited.model);
                egui::ComboBox::from_id_salt("catalog_model")
                    .width(ui.available_width())
                    .selected_text(selected.map(|m| m.name.as_str()).unwrap_or(
                        if self.edited.model.is_empty() {
                            l.text("Provider default")
                        } else {
                            &self.edited.model
                        },
                    ))
                    .show_ui(ui, |ui| {
                        ui.label(l.text("Search models"));
                        ui.add(
                            egui::TextEdit::singleline(&mut self.providers.search)
                                .hint_text(l.text("Name or model ID"))
                                .desired_width(ui.available_width()),
                        );
                        let query = self.providers.search.trim().to_lowercase();
                        if ui
                            .selectable_label(self.edited.model.is_empty(), l.text("Provider default"))
                            .clicked()
                        {
                            self.edited.model.clear();
                            ui.close();
                        }
                        let mut found = false;
                        egui::ScrollArea::vertical()
                            .max_height(220.0)
                            .show(ui, |ui| {
                                for model in models.iter().filter(|model| {
                                    model.id.to_lowercase().contains(&query)
                                        || model.name.to_lowercase().contains(&query)
                                }) {
                                    found = true;
                                    if ui
                                        .selectable_label(
                                            self.edited.model == model.id,
                                            &model.name,
                                        )
                                        .on_hover_text(&model.id)
                                        .clicked()
                                    {
                                        self.edited.model = model.id.clone();
                                        ui.close();
                                    }
                                }
                            });
                        if !found {
                            muted(ui, l.text("No matching models. Try another search."));
                        }
                    });
                if let Some(model) = models.iter().find(|m| m.id == self.edited.model) {
                    ui.label(RichText::new(&model.id).small().color(MUTED));
                    if let (Some(input), Some(output)) = (model.input_price, model.output_price) {
                        ui.label(
                            RichText::new(format!(
                                "{}: ${:.3} {} · ${:.3} {}",
                                l.text("Per 1M tokens"), input * 1e6, l.text("input"),
                                output * 1e6, l.text("output")
                            ))
                            .small()
                            .color(MUTED),
                        );
                    }
                }
            }
            Fetch::Ready(Err(error), _) => {
                ui.colored_label(ERROR, l.message(error.as_ref()));
                if ui.button(l.text("Retry model catalog")).clicked() {
                    self.providers.refresh();
                }
            }
            _ => {
                muted(ui, l.text("Loading compatible models…"));
            }
        }
        egui::CollapsingHeader::new(l.text("Enter a model ID manually")).show(ui, |ui| {
            ui.label(l.text("Model ID"));
            ui.add(
                egui::TextEdit::singleline(&mut self.edited.model)
                    .desired_width(f32::INFINITY)
                    .hint_text(l.text("Leave blank for the provider default")),
            );
        });
        if self.edited.speaker_gender != "off"
            && (self.edited.model.starts_with("tencent/hy-mt2-")
                || self.edited.provider == "kilo" && self.edited.model.is_empty())
        {
            ui.label(RichText::new(l.text("With HY-MT2, speaker grammar uses an additional Gemma request. Its cost is included in spending.")).small().color(MUTED));
        }
    }

    fn spending_ui(&self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        if let Some(api) = self.api() {
            let usage = api.usage(&self.edited, self.playback_id);
            if self.playback_id.is_some()
                || usage.reported_cost_usd > 0.0
                || usage.unpriced_requests > 0
            {
                ui.label(
                    RichText::new(format!(
                        "{}: ${:.6}",
                        if self.playback_id.is_some() {
                            l.text("This video · reported spend")
                        } else {
                            l.text("This run · reported spend")
                        },
                        usage.reported_cost_usd
                    ))
                    .color(MUTED),
                );
                if usage.unpriced_requests > 0 {
                    ui.label(
                        RichText::new(format!(
                            "{}: {}. {}", l.text("Requests with no confirmed cost"),
                            usage.unpriced_requests, l.text("Total may be higher.")
                        ))
                        .small()
                        .color(MUTED),
                    );
                }
            }
        }
    }

    fn account_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        if !matches!(self.edited.provider.as_str(), "kilo" | "openrouter") {
            return;
        }
        self.providers.sync(&self.edited);
        egui::Frame::new()
            .fill(SURFACE)
            .stroke(Stroke::new(1.0, BORDER))
            .corner_radius(14)
            .inner_margin(20)
            .show(ui, |ui| {
                section(ui, l.text("Account & spending"), l.text("Amounts are in USD."));
                match self.providers.balance.lock().unwrap().clone() {
                    Fetch::Ready(Ok(balance), at) => {
                        if let Some(balance) = balance.balance_usd {
                            ui.label(l.text("Account balance"));
                            ui.label(
                                RichText::new(format!("${balance:.4}"))
                                    .size(24.0)
                                    .color(ACCENT),
                            );
                        }
                        if let Some(remaining) = balance.key_limit_remaining_usd {
                            muted(ui, &format!("{}: ${remaining:.4}", l.text("Key allowance remaining")));
                        }
                        if let Some(spent) = balance.key_spent_usd {
                            muted(ui, &format!("{}: ${spent:.4}", l.text("Key total spent")));
                        }
                        if let Some(note) = balance.balance_note {
                            ui.label(RichText::new(l.message(&note)).small().color(MUTED));
                        }
                        if let Some(spent) = balance.total_spent_usd {
                            muted(ui, &format!("{}: ${spent:.4}", l.text("Account total spent")));
                        }
                        ui.label(
                            RichText::new(format!("{} {} {}", l.text("Updated"), at.elapsed().as_secs(), l.text("s ago")))
                                .small()
                                .color(MUTED),
                        );
                    }
                    Fetch::Ready(Err(error), _) => {
                        ui.colored_label(ERROR, l.text("Balance unavailable"));
                        muted(ui, &l.message(&error));
                    }
                    Fetch::Loading => {
                        muted(ui, l.text("Refreshing balance…"));
                    }
                    Fetch::Idle => {
                        muted(ui, l.text("Add an API key to retrieve your balance."));
                    }
                }
                if let Some(api) = self.api() {
                    let spent = api.usage(&self.edited, None);
                    muted(
                        ui,
                        &format!("{}: ${:.6}", l.text("This provider · app run"), spent.reported_cost_usd),
                    );
                    ui.label(
                        RichText::new(
                            l.text("Includes checks, retries, translation, grammar and alignment."),
                        )
                        .small()
                        .color(MUTED),
                    );
                    if spent.unpriced_requests > 0 {
                        ui.label(
                            RichText::new(format!(
                                "{}: {}. {}", l.text("Requests with no confirmed cost"),
                                spent.unpriced_requests, l.text("This is a partial total.")
                            ))
                            .small()
                            .color(MUTED),
                        );
                    }
                }
                if ui.button(l.text("Refresh account & models")).clicked() {
                    self.providers.refresh();
                }
            });
    }

    fn connection_ui(&mut self, ui: &mut egui::Ui) {
        let l = self.edited.interface_language;
        egui::Frame::new()
            .fill(SURFACE)
            .stroke(Stroke::new(1.0, BORDER))
            .corner_radius(14)
            .inner_margin(24)
            .show(ui, |ui| {
                section(
                    ui,
                    l.text("Connection"),
                    l.text("Use a cloud provider or a model on your computer."),
                );
                let mut provider = self.edited.provider.clone();
                select(ui, l,
                    "provider",
                    l.text("Translation provider"),
                    &mut provider,
                    &PROVIDERS,
                );
                self.edited.select_provider(provider);
                if self.edited.provider == "custom" {
                    ui.label(l.text("Server address"));
                    ui.add(
                        egui::TextEdit::singleline(&mut self.edited.base_url)
                            .desired_width(f32::INFINITY)
                            .hint_text("http://127.0.0.1:1234/v1"),
                    );
                    ui.label(
                        RichText::new(l.text("OpenAI-compatible API address, including /v1."))
                            .small()
                            .color(MUTED),
                    );
                }
                ui.label(l.text("API key"));
                ui.add(
                    egui::TextEdit::singleline(&mut self.edited.api_key)
                        .password(true)
                        .desired_width(f32::INFINITY)
                        .hint_text(if self.edited.provider == "custom" {
                            l.text("Optional for a local server")
                        } else {
                            l.text("Paste your provider's key")
                        }),
                );
                ui.label(
                    RichText::new(
                        l.text("Stored in your user profile. Sent only to your translation provider."),
                    )
                    .small()
                    .color(MUTED),
                );
                self.providers.sync(&self.edited);
                if self.edited.provider == "openrouter" {
                    egui::CollapsingHeader::new(l.text("Account balance key (optional)")).show(ui, |ui| {
                        ui.label(l.text("OpenRouter management key"));
                        ui.add(egui::TextEdit::singleline(&mut self.edited.balance_key).password(true).desired_width(f32::INFINITY));
                        ui.label(RichText::new(l.text("Kept in memory for this app run; used only for balance. Without it, key usage and allowance are shown.")).small().color(MUTED));
                    });
                }
                if matches!(self.edited.provider.as_str(), "kilo" | "openrouter") {
                    self.models_ui(ui);
                } else {
                    ui.label(l.text("Model"));
                    let hint = match self.edited.provider.as_str() {
                        "kilo" => "tencent/hy-mt2-1.8b",
                        "openai" => "gpt-4.1-mini",
                        "custom" => l.text("Enter your model ID"),
                        _ => "google/gemma-4-26b-a4b-it",
                    };
                    ui.add(
                        egui::TextEdit::singleline(&mut self.edited.model)
                            .desired_width(f32::INFINITY)
                            .hint_text(l.text(hint)),
                    );
                    ui.label(
                        RichText::new(if self.edited.provider == "custom" {
                            l.text("Use the model ID reported by your server.")
                        } else {
                            l.text("Leave blank to use the provider's default model.")
                        })
                        .small()
                        .color(MUTED),
                    );
                }
                ui.add_space(10.0);
                let invalid = self.edited.connection_error();
                let (state, current) = {
                    let report = self.check.lock().unwrap();
                    (
                        report.state.clone(),
                        report.session == self.edited.session(),
                    )
                };
                let running = matches!(state, CheckState::Running);
                let enabled = self.api().is_some() && invalid.is_none() && !running;
                ui.add_enabled_ui(enabled, |ui| {
                    if primary(
                        ui,
                        if running {
                            l.text("Checking connection…")
                        } else {
                            l.text("Check connection")
                        },
                    )
                    .clicked()
                    {
                        self.check();
                    }
                });
                if self.api().is_none() {
                    muted(
                        ui,
                        l.text("The speech engine must be ready before checking the connection."),
                    );
                }
                if let Some(error) = invalid {
                    ui.colored_label(ERROR, l.message(error.as_ref()));
                }
                if running {
                    ui.add(
                        egui::ProgressBar::new(0.0)
                            .animate(true)
                            .corner_radius(3)
                            .desired_width(ui.available_width()),
                    );
                    muted(ui, l.text("Loading speech models and checking translation…"));
                    ui.label(
                        RichText::new(l.text("The first check can take about 30 seconds."))
                            .small()
                            .color(MUTED),
                    );
                } else if current {
                    match state {
                        CheckState::Passed(seconds) => {
                            ui.colored_label(
                                ACCENT,
                                format!("{} {seconds:.1} {}", l.text("Connection verified · ready in"), l.text("s")),
                            );
                        }
                        CheckState::Failed(error) => {
                            ui.colored_label(ERROR, l.text("Connection check failed"));
                            ui.label(l.message(&error));
                        }
                        _ => {}
                    }
                } else if !matches!(state, CheckState::Idle) {
                    muted(ui, l.text("Settings changed. Check the connection again."));
                }
            });
        if let Some(file) = self.pending.clone() {
            ui.add_space(16.0);
            ui.label(
                RichText::new(format!(
                    "{}{}", l.text("Selected: "),
                    file.file_name().unwrap_or_default().to_string_lossy()
                ))
                .strong(),
            );
            ui.horizontal(|ui| {
                ui.add_enabled_ui(self.edited.connection_error().is_none(), |ui| {
                    if primary(ui, l.text("Continue to video")).clicked() {
                        self.save_settings();
                        self.pending = None;
                        self.open(file);
                    }
                });
                if ui.button(l.text("Cancel")).clicked() {
                    self.pending = None;
                }
            });
        }
    }
}

fn privacy_ui(ui: &mut egui::Ui, l: Language) {
    egui::Frame::new()
        .inner_margin(egui::Margin::symmetric(16, 18))
        .show(ui, |ui| {
            section(
                ui,
                l.text("Your video stays yours"),
                l.text("Recognition and voice generation run on this computer."),
            );
            for (title, description) in [
                (
                    l.text("Video & audio"),
                    l.text("Processed locally. Never uploaded to the translation provider."),
                ),
                (
                    l.text("Recognized text"),
                    l.text("Sent to the provider you choose to create the translation."),
                ),
                (
                    l.text("Prefer to stay offline?"),
                    l.text("Connect a local model through an OpenAI-compatible server."),
                ),
            ] {
                ui.label(RichText::new(l.text(title)).strong());
                muted(ui, l.text(description));
                ui.add_space(14.0);
            }
        });
}
