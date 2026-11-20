#![cfg(any(test, target_arch = "wasm32"))]

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({ world: "plugin" });

    struct Plugin;

    impl Guest for Plugin {
        fn invoke(input: String) -> String {
            super::invoke(&input).to_string()
        }
    }

    export!(Plugin);
}

#[derive(Deserialize)]
#[serde(tag = "action", content = "input", rename_all = "kebab-case")]
enum Action {
    ReadSubtitleCues {
        subtitles: String,
    },
    AssembleTranslatedSubtitles {
        subtitles: String,
        translations: Vec<Translation>,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Translation {
    cue: usize,
    text: String,
}

struct Cue<'a> {
    timing: &'a str,
    text: String,
}

fn read_cues(source: &str) -> Result<Vec<Cue<'_>>, &'static str> {
    let mut lines = source.trim_start_matches('\u{feff}').lines().peekable();
    let mut cues = Vec::new();
    while lines.peek().is_some() {
        if lines.next_if(|line| line.trim().is_empty()).is_some() {
            continue;
        }
        let index = lines.next().ok_or("invalid_subtitles")?;
        if index.trim().parse::<usize>().is_err() {
            return Err("invalid_subtitles");
        }
        let timing = lines.next().ok_or("invalid_subtitles")?.trim();
        let (start, finish) = timing.split_once(" --> ").ok_or("invalid_subtitles")?;
        if !valid_timestamp(start) || !valid_timestamp(finish) {
            return Err("invalid_subtitles");
        }
        let mut text = String::new();
        while let Some(line) = lines.next_if(|line| !line.trim().is_empty()) {
            if !text.is_empty() {
                text.push('\n');
            }
            text.push_str(line);
        }
        if !valid_text(&text) {
            return Err("invalid_subtitles");
        }
        cues.push(Cue { timing, text });
    }
    if cues.is_empty() {
        return Err("invalid_subtitles");
    }
    Ok(cues)
}

fn valid_timestamp(value: &str) -> bool {
    let mut parts = value.split([':', ',', '.']);
    let Some(hours) = parts.next() else {
        return false;
    };
    let (Some(minutes), Some(seconds), Some(milliseconds)) =
        (parts.next(), parts.next(), parts.next())
    else {
        return false;
    };
    !hours.is_empty()
        && hours.bytes().all(|byte| byte.is_ascii_digit())
        && [minutes, seconds].into_iter().all(|part| {
            part.len() == 2
                && part.bytes().all(|byte| byte.is_ascii_digit())
                && part.as_bytes()[0] <= b'5'
        })
        && milliseconds.len() == 3
        && milliseconds.bytes().all(|byte| byte.is_ascii_digit())
        && parts.next().is_none()
        && value.as_bytes()[hours.len()] == b':'
        && value.as_bytes()[hours.len() + 3] == b':'
        && matches!(value.as_bytes()[hours.len() + 6], b',' | b'.')
}

fn valid_text(value: &str) -> bool {
    !value.is_empty()
        && !value.contains(['\0', '\r'])
        && value.lines().all(|line| !line.trim().is_empty())
}

fn execute(action: Action) -> Result<Value, &'static str> {
    match action {
        Action::ReadSubtitleCues { subtitles } => {
            let cues = read_cues(&subtitles)?
                .into_iter()
                .enumerate()
                .map(|(index, cue)| Translation {
                    cue: index + 1,
                    text: cue.text,
                })
                .collect::<Vec<_>>();
            Ok(json!({ "cues": cues }))
        }
        Action::AssembleTranslatedSubtitles {
            subtitles,
            mut translations,
        } => {
            let cues = read_cues(&subtitles)?;
            if cues.len() != translations.len() {
                return Err("translation_coverage");
            }
            translations.sort_unstable_by_key(|item| item.cue);
            let mut output = String::new();
            for (index, (source, translation)) in cues.into_iter().zip(translations).enumerate() {
                let number = index + 1;
                let normalized = translation.text.replace("\r\n", "\n");
                let text = normalized.trim();
                if translation.cue != number || !valid_text(text) {
                    return Err("invalid_translation");
                }
                use std::fmt::Write;
                writeln!(output, "{number}\n{}\n{text}\n", source.timing)
                    .expect("writing to a String is infallible");
            }
            Ok(json!({ "subtitles": output }))
        }
    }
}

fn invoke(input: &str) -> Value {
    match serde_json::from_str(input)
        .map_err(|_| "invalid_request")
        .and_then(execute)
    {
        Ok(result) => json!({ "ok": true, "result": result }),
        Err(error) => json!({ "ok": false, "error": error }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SOURCE: &str = "\u{feff}8\r\n00:00:00,125 --> 00:00:01,900\r\nHello\r\n\r\n42\r\n00:00:02,000 --> 00:00:03,400\r\nWorld\r\n";

    #[test]
    fn translates_by_position_and_preserves_timing() {
        assert_eq!(
            invoke(
                &json!({"action":"read-subtitle-cues","input":{"subtitles":SOURCE}}).to_string()
            ),
            json!({"ok":true,"result":{"cues":[{"cue":1,"text":"Hello"},{"cue":2,"text":"World"}]}})
        );
        let assembled = invoke(&json!({"action":"assemble-translated-subtitles","input":{
            "subtitles":SOURCE,"translations":[{"cue":2,"text":"Mundo"},{"cue":1,"text":"Olá\namigo"}]
        }}).to_string());
        assert_eq!(
            assembled["result"]["subtitles"],
            "1\n00:00:00,125 --> 00:00:01,900\nOlá\namigo\n\n2\n00:00:02,000 --> 00:00:03,400\nMundo\n\n"
        );
    }

    #[test]
    fn rejects_missing_duplicate_and_injected_cues() {
        for (items, error) in [
            (json!([{"cue":1,"text":"Olá"}]), "translation_coverage"),
            (
                json!([{"cue":1,"text":"Olá"},{"cue":1,"text":"Mundo"}]),
                "invalid_translation",
            ),
            (
                json!([{"cue":1,"text":"Olá\n\n10\nnew cue"},{"cue":2,"text":"Mundo"}]),
                "invalid_translation",
            ),
        ] {
            let response = invoke(
                &json!({"action":"assemble-translated-subtitles","input":{
                    "subtitles":SOURCE,"translations":items
                }})
                .to_string(),
            );
            assert_eq!(response, json!({"ok":false,"error":error}));
        }
    }
}
