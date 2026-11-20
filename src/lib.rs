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
    PlanSpeech {
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
    start_ms: u64,
    end_ms: u64,
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
        let start_ms = timestamp_ms(start).ok_or("invalid_subtitles")?;
        let end_ms = timestamp_ms(finish).ok_or("invalid_subtitles")?;
        if end_ms <= start_ms {
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
        cues.push(Cue {
            timing,
            start_ms,
            end_ms,
            text,
        });
    }
    if cues.is_empty() {
        return Err("invalid_subtitles");
    }
    Ok(cues)
}

fn timestamp_ms(value: &str) -> Option<u64> {
    let (hours, rest) = value.split_once(':')?;
    let (minutes, rest) = rest.split_once(':')?;
    let (seconds, milliseconds) = rest.split_once([',', '.'])?;
    let digits = |part: &str| !part.is_empty() && part.bytes().all(|byte| byte.is_ascii_digit());
    if !digits(hours)
        || minutes.len() != 2
        || seconds.len() != 2
        || milliseconds.len() != 3
        || ![minutes, seconds, milliseconds].into_iter().all(digits)
    {
        return None;
    }
    let minutes: u64 = minutes.parse().ok()?;
    let seconds: u64 = seconds.parse().ok()?;
    if minutes >= 60 || seconds >= 60 {
        return None;
    }
    let remainder = minutes * 60_000 + seconds * 1_000 + milliseconds.parse::<u64>().ok()?;
    hours
        .parse::<u64>()
        .ok()?
        .checked_mul(3_600_000)?
        .checked_add(remainder)
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
        Action::PlanSpeech { subtitles } => {
            let segments = read_cues(&subtitles)?
                .into_iter()
                .enumerate()
                .map(|(index, cue)| {
                    json!({
                        "cue": index + 1,
                        "startMillis": cue.start_ms,
                        "endMillis": cue.end_ms,
                        "text": cue.text,
                    })
                })
                .collect::<Vec<_>>();
            Ok(json!({ "segments": segments }))
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
    #[test]
    fn speech_plan_preserves_cue_windows_and_rejects_invalid_times() {
        let plan = |subtitles: &str| {
            invoke(
                &json!({
                    "action": "plan-speech", "input": {"subtitles": subtitles}
                })
                .to_string(),
            )
        };
        assert_eq!(
            plan(SOURCE),
            json!({"ok": true, "result": {"segments": [
                {"cue": 1, "startMillis": 125, "endMillis": 1900, "text": "Hello"},
                {"cue": 2, "startMillis": 2000, "endMillis": 3400, "text": "World"}
            ]}})
        );
        for invalid in [
            "00:00:00,125",
            "00:00:00,100",
            "00:60:01,900",
            "999999999999999:00:01,900",
        ] {
            assert_eq!(
                plan(&SOURCE.replace("00:00:01,900", invalid)),
                json!({"ok": false, "error": "invalid_subtitles"})
            );
        }
    }
}
