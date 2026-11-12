//! English and Russian interface text, shared by Windows and macOS.
use serde::{Deserialize, Serialize};
use std::borrow::Cow;

#[derive(Clone, Copy, Default, Debug, PartialEq, Serialize, Deserialize)]
pub enum Language {
    #[serde(rename = "ru")]
    Russian,
    #[default]
    #[serde(rename = "en", other)]
    English,
}

impl Language {
    pub fn text(self, source: &str) -> &str {
        if self == Self::Russian {
            RUSSIAN.iter().find(|(english, _)| *english == source).map(|(_, russian)| *russian).unwrap_or(source)
        } else { source }
    }

    pub fn message(self, source: &str) -> Cow<'_, str> {
        let translated = self.text(source);
        if self == Self::English || translated != source { return Cow::Borrowed(translated); }
        for prefix in ["Error: ", "Translated to ", "Engine unreachable: ", "Engine error ",
            "Could not start mpv (", "Could not start the engine (",
            "The engine exited during startup; see ", "The engine did not start; see "] {
            if let Some(detail) = source.strip_prefix(prefix) {
                return Cow::Owned(format!("{}{}", self.text(prefix), self.message(detail)));
            }
        }
        if let Some((failure, reference)) = source.split_once(". Retry translation. Reference: ") {
            return Cow::Owned(format!("{}. {} {}", self.message(failure), self.text("Retry translation. Reference:"), reference));
        }
        if let Some((status, hint)) = source.split_once("; ") {
            return Cow::Owned(format!("{}; {}", self.message(status), self.message(hint)));
        }
        for name in ["OpenRouter", "Kilo Gateway", "OpenAI", "Custom endpoint"] {
            if let Some(detail) = source.strip_prefix(&format!("{name}: ")) {
                return Cow::Owned(format!("{}: {}", self.text(name), self.message(detail)));
            }
            if source == format!("{name} is unreachable or timed out") {
                return Cow::Owned(format!("{}: {}", self.text(name), self.text("Service unreachable or timed out")));
            }
        }
        // Provider diagnostics and file paths are preserved verbatim.
        Cow::Borrowed(source)
    }
}

const RUSSIAN: &[(&str, &str)] = &[
    ("Custom endpoint", "Свой сервер"),
    ("Service unreachable or timed out", "Сервис недоступен или не ответил вовремя"),
    ("Retry translation. Reference:", "Повторите перевод. Код обращения:"),
    ("check the API key", "проверьте API-ключ"),
    ("check account credits", "проверьте баланс аккаунта"),
    ("check account access and the server outbound network route", "проверьте доступ к аккаунту и подключение сервера к интернету"),
    ("request limit reached", "достигнут лимит запросов"),
    ("check the model and structured-output support", "проверьте модель и поддержку структурированного ответа"),
    ("try again later", "повторите попытку позже"),
    ("translation exceeded the output token limit", "перевод превысил лимит выходных токенов"),
    ("translation was blocked by the provider content filter", "перевод заблокирован фильтром сервиса"),
    ("provider returned an empty translation", "сервис вернул пустой перевод"),
    ("provider returned an invalid translation", "сервис вернул некорректный перевод"),
    ("translation timed out after 60 seconds", "сервис перевода не ответил за 60 секунд"),
    ("The video file was not found", "Видеофайл не найден"),
    ("This file has no readable audio track", "В этом файле нет доступной звуковой дорожки"),
    ("Position beyond the end of the video", "Позиция за пределами видео"),
    ("Could not warm up models. Check the server services", "Не удалось подготовить модели. Проверьте речевой движок"),
    ("Could not prepare audio or models", "Не удалось подготовить звук или модели"),
    ("Translation check failed; check the model service", "Проверка перевода не удалась; проверьте сервис модели"),
    ("Audio translation timed out after 105 seconds", "Перевод звука не завершился за 105 секунд"),
    ("Local model error; check the server services", "Ошибка локальной модели; проверьте речевой движок"),
    ("Watch", "Просмотр"),
    ("Translation", "Перевод"),
    ("Engine starting", "Запуск движка"),
    ("Preparing speech", "Подготовка речи"),
    ("Engine ready", "Движок готов"),
    ("Engine unavailable", "Движок недоступен"),
    ("Settings could not be saved", "Не удалось сохранить настройки"),
    ("Retry", "Повторить"),
    ("Settings save automatically", "Настройки сохраняются автоматически"),
    ("Desktop", "Приложение"),
    ("Language", "Язык"),
    ("Interface language", "Язык интерфейса"),
    ("The speech engine could not start.", "Не удалось запустить речевой движок."),
    ("Show details", "Подробности"),
    ("Dismiss", "Скрыть"),
    ("Watch with Russian voiceover", "Просмотр с русской озвучкой"),
    ("Your videos, with synchronized Russian voiceover.", "Ваши видео с синхронной русской озвучкой."),
    ("Open a video to begin", "Откройте видео для начала"),
    ("Video selected · waiting to start", "Видео выбрано · ожидание запуска"),
    ("Playing in the video window", "Воспроизведение в окне видео"),
    ("Video closed", "Видео закрыто"),
    ("Drop your video here", "Отпустите видео здесь"),
    ("Drop a video here, or choose a file to get started.", "Перетащите видео сюда или выберите файл."),
    ("Open another video", "Открыть другое видео"),
    ("Open video", "Открыть видео"),
    ("Choose a local video file", "Выбрать видео на компьютере"),
    ("MP4 · MKV · AVI · MOV · WebM + more", "MP4 · MKV · AVI · MOV · WebM и другие"),
    ("One quick setup before you watch", "Настройка перед первым просмотром"),
    ("Connect a translation provider or a local model.", "Подключите сервис перевода или локальную модель."),
    ("Set up translation", "Настроить перевод"),
    ("Stop video", "Остановить видео"),
    ("Translation configured", "Перевод настроен"),
    ("Playback shortcuts", "Управление видео"),
    ("Space", "Пробел"),
    ("Pause / play", "Пауза / воспроизведение"),
    ("Left / Right", "← / →"),
    ("Seek 5 seconds", "Перемотка на 5 секунд"),
    ("F / double-click", "F / двойной клик"),
    ("Full screen", "Полный экран"),
    ("Close video", "Закрыть видео"),
    ("Use these shortcuts in the video window.", "Эти клавиши работают в окне видео."),
    ("Voiceover", "Озвучка"),
    ("Video language", "Язык видео"),
    ("Voice mode", "Режим голосов"),
    ("One voice", "Один голос"),
    ("By speaker", "По говорящему"),
    ("Use one selected voice for all speakers. Speaker grammar can still follow the original voices.", "Один голос для всех. Грамматический род перевода по-прежнему может определяться по исходному голосу."),
    ("Assign a separate voice for female and male speakers.", "Назначьте отдельные голоса для женщин и мужчин."),
    ("Female speaker", "Женский голос"),
    ("Male speaker", "Мужской голос"),
    ("Uncertain speakers use", "Если голос не определён, используется"),
    ("Russian voice", "Русский голос"),
    ("Speaker grammar", "Род в переводе"),
    ("Auto · from voice", "Авто · по голосу"),
    ("Feminine", "Женский род"),
    ("Masculine", "Мужской род"),
    ("Use text only", "Только по тексту"),
    ("Acoustic cues guide first-person grammar. For ambiguous voices, choose Feminine or Masculine.", "Род фраз от первого лица определяется по голосу. При ошибках выберите женский или мужской род вручную."),
    ("Changes apply while you watch.", "Настройки применяются во время просмотра."),
    ("Changing the voice or video language restarts translation from the current position.", "При смене голоса или языка видео перевод начинается заново с текущей позиции."),
    ("Voiceover volume", "Громкость озвучки"),
    ("Original audio", "Исходный звук"),
    ("Volume changes apply immediately.", "Громкость меняется сразу."),
    ("Lower original during voiceover", "Приглушать оригинал при озвучке"),
    ("Keeps half the selected original volume during translated speech. Turn off to keep the original at full selected volume.", "Во время озвучки исходный звук становится вдвое тише. Отключите, чтобы сохранить выбранную громкость."),
    ("Show translated captions", "Показывать перевод в субтитрах"),
    ("Choose where the original speech is translated.", "Выберите сервис для перевода исходной речи."),
    ("Model", "Модель"),
    ("Provider default", "По умолчанию"),
    ("Search models", "Поиск моделей"),
    ("Name or model ID", "Название или ID модели"),
    ("No matching models. Try another search.", "Модели не найдены. Измените запрос."),
    ("Per 1M tokens", "За 1 млн токенов"),
    ("input", "вход"),
    ("output", "выход"),
    ("Retry model catalog", "Загрузить каталог снова"),
    ("Loading compatible models…", "Загрузка совместимых моделей…"),
    ("Enter a model ID manually", "Ввести ID модели вручную"),
    ("Model ID", "ID модели"),
    ("Leave blank for the provider default", "Оставьте пустым для модели по умолчанию"),
    ("With HY-MT2, speaker grammar uses an additional Gemma request. Its cost is included in spending.", "С HY-MT2 род уточняется отдельным запросом к Gemma. Его стоимость включена в расходы."),
    ("This video · reported spend", "Это видео · учтённые расходы"),
    ("This run · reported spend", "Этот запуск · учтённые расходы"),
    ("Requests with no confirmed cost", "Запросы без подтверждённой стоимости"),
    ("Total may be higher.", "Итоговая сумма может быть выше."),
    ("This is a partial total.", "Это неполная сумма."),
    ("Account & spending", "Баланс и расходы"),
    ("Amounts are in USD.", "Суммы указаны в долларах США."),
    ("Account balance", "Баланс аккаунта"),
    ("Key allowance remaining", "Остаток лимита ключа"),
    ("Key total spent", "Расходы по ключу"),
    ("Account total spent", "Всего потрачено в аккаунте"),
    ("Updated", "Обновлено"),
    ("s ago", "с назад"),
    ("Balance unavailable", "Баланс недоступен"),
    ("Refreshing balance…", "Обновление баланса…"),
    ("Add an API key to retrieve your balance.", "Укажите API-ключ для получения баланса."),
    ("This provider · app run", "Этот сервис · за запуск приложения"),
    ("Includes checks, retries, translation, grammar and alignment.", "Включает проверки, повторы, перевод, уточнение рода и выравнивание фраз."),
    ("Refresh account & models", "Обновить баланс и модели"),
    ("Connection", "Подключение"),
    ("Use a cloud provider or a model on your computer.", "Подключите облачный сервис или модель на своём компьютере."),
    ("Translation provider", "Сервис перевода"),
    ("Server address", "Адрес сервера"),
    ("OpenAI-compatible API address, including /v1.", "Адрес API, совместимого с OpenAI, включая /v1."),
    ("API key", "API-ключ"),
    ("Optional for a local server", "Необязательно для локального сервера"),
    ("Paste your provider's key", "Вставьте ключ сервиса"),
    ("Stored in your user profile. Sent only to your translation provider.", "Хранится в вашем профиле. Отправляется только выбранному сервису перевода."),
    ("Account balance key (optional)", "Ключ для баланса аккаунта (необязательно)"),
    ("OpenRouter management key", "Ключ управления OpenRouter"),
    ("Kept in memory for this app run; used only for balance. Without it, key usage and allowance are shown.", "Хранится только в памяти до закрытия приложения и используется для баланса. Без него показываются расходы и лимит ключа."),
    ("Enter your model ID", "Введите ID модели"),
    ("Use the model ID reported by your server.", "Укажите ID модели, который сообщает ваш сервер."),
    ("Leave blank to use the provider's default model.", "Оставьте пустым для модели сервиса по умолчанию."),
    ("Checking connection…", "Проверка подключения…"),
    ("Check connection", "Проверить подключение"),
    ("The speech engine must be ready before checking the connection.", "Дождитесь запуска речевого движка перед проверкой подключения."),
    ("Loading speech models and checking translation…", "Загрузка речевых моделей и проверка перевода…"),
    ("The first check can take about 30 seconds.", "Первая проверка может занять около 30 секунд."),
    ("Connection verified · ready in", "Подключение проверено · готово за"),
    ("s", "с"),
    ("Connection check failed", "Не удалось проверить подключение"),
    ("Settings changed. Check the connection again.", "Настройки изменились. Проверьте подключение ещё раз."),
    ("Continue to video", "Перейти к видео"),
    ("Cancel", "Отмена"),
    ("Your video stays yours", "Ваше видео остаётся у вас"),
    ("Recognition and voice generation run on this computer.", "Распознавание и синтез речи работают на этом компьютере."),
    ("Video & audio", "Видео и звук"),
    ("Processed locally. Never uploaded to the translation provider.", "Обрабатываются локально и не отправляются сервису перевода."),
    ("Recognized text", "Распознанный текст"),
    ("Sent to the provider you choose to create the translation.", "Отправляется выбранному сервису для перевода."),
    ("Prefer to stay offline?", "Хотите работать без интернета?"),
    ("Connect a local model through an OpenAI-compatible server.", "Подключите локальную модель через сервер с API, совместимым с OpenAI."),
    ("OpenAI-compatible address", "Совместимый с OpenAI адрес"),
    ("Albina · female", "Альбина · женский"),
    ("Alfia · female", "Альфия · женский"),
    ("Roman · male", "Роман · мужской"),
    ("Eduard · male", "Эдуард · мужской"),
    ("Alexander · male", "Александр · мужской"),
    ("English", "Английский"),
    ("Chinese", "Китайский"),
    ("Korean", "Корейский"),
    ("Japanese", "Японский"),
    ("Preparing translation…", "Подготовка перевода…"),
    ("Playback finished", "Воспроизведение завершено"),
    ("Translating ahead…", "Перевод следующих фрагментов…"),
    ("Open a video with Synchro", "Открыть видео в Synchro"),
    ("Video files", "Видеофайлы"),
    ("Choose a video file: MP4, MKV, AVI, MOV, WebM, or another supported format.", "Выберите видео: MP4, MKV, AVI, MOV, WebM или другой поддерживаемый формат."),
    ("Enter a valid server address starting with http:// or https://.", "Укажите адрес сервера, начинающийся с http:// или https://."),
    ("Add your provider's API key to enable translation.", "Укажите API-ключ сервиса, чтобы включить перевод."),
    ("The settings folder is unavailable", "Папка настроек недоступна"),
    ("Synchro engine files were not found next to the program", "Не найдены файлы движка Synchro рядом с приложением"),
    ("mpv did not open its control channel", "mpv не открыл канал управления"),
    ("mpv closed", "mpv закрыт"),
    ("Account balance requires a separate management key. The key allowance is not the account balance.", "Для баланса аккаунта нужен отдельный ключ управления. Лимит ключа не является балансом аккаунта."),
    ("Provider returned invalid account or catalog data", "Сервис вернул некорректные данные аккаунта или каталога"),
    ("Provider returned an invalid model catalog", "Сервис вернул некорректный каталог моделей"),
    ("No compatible translation models found in the provider catalog", "В каталоге сервиса нет совместимых моделей перевода"),
    ("OpenRouter key usage is unavailable", "Расходы по ключу OpenRouter недоступны"),
    ("Provider balance is unavailable; no balance was assumed", "Баланс сервиса недоступен; сумма не определена"),
    ("A custom endpoint needs a model ID and translates text only", "Для своего сервера укажите ID модели. Поддерживается только перевод текста"),
    ("Use a model ID, not a URL", "Укажите ID модели вместо URL"),
    ("A valid cloud API key is required", "Укажите действующий API-ключ сервиса"),
    ("Invalid API key", "Недействительный API-ключ"),
    ("Error: ", "Ошибка: "),
    ("Translated to ", "Переведено до "),
    ("Engine unreachable: ", "Движок недоступен: "),
    ("Engine error ", "Ошибка движка "),
    ("Log: ", "Журнал: "),
    ("Selected: ", "Выбрано: "),
    ("Could not start mpv (", "Не удалось запустить mpv ("),
    ("Could not start the engine (", "Не удалось запустить движок ("),
    ("The engine exited during startup; see ", "Движок завершился при запуске; журнал: "),
    ("The engine did not start; see ", "Движок не запустился; журнал: "),
];
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_ui_key_has_a_translation_and_catalog_has_no_duplicates() {
        let mut seen = std::collections::HashSet::new();
        for &(english, russian) in RUSSIAN {
            assert!(seen.insert(english), "Duplicate key: {english}");
            assert!(!russian.is_empty());
            assert_eq!(Language::English.text(english), english);
        }
        for source in [include_str!("ui.rs"), include_str!("main.rs")] {
            for tail in source.split("l.text(\"").skip(1) {
                let key = tail.split('"').next().unwrap();
                assert!(seen.contains(key), "Missing Russian UI key: {key}");
            }
        }
    }

    #[test]
    fn statuses_errors_and_diagnostics_switch_without_changing_data() {
        let ru = Language::Russian;
        assert_eq!(ru.message("Translated to 12:34"), "Переведено до 12:34");
        assert_eq!(ru.message("Error: OpenRouter: HTTP 401; check the API key"), "Ошибка: OpenRouter: HTTP 401; проверьте API-ключ");
        assert_eq!(ru.message("Kilo Gateway is unreachable or timed out. Retry translation. Reference: abc123"), "Kilo Gateway: Сервис недоступен или не ответил вовремя. Повторите перевод. Код обращения: abc123");
        let path = "D:\\Videos\\English film 日本語.mkv";
        assert_eq!(ru.message(path), path);
        assert_eq!(Language::English.message("Translated to 12:34"), "Translated to 12:34");
        assert_eq!(ru.message("Unexpected provider diagnostic 123"), "Unexpected provider diagnostic 123");
    }
}
