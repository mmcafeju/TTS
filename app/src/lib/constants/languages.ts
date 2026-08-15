/**
 * Supported languages for voice generation, per engine.
 *
 * Qwen3-TTS supports 10 languages.
 * Qwen CustomVoice supports 10 languages.
 * Supertonic supports 31 languages.
 */

/** All languages that any engine supports. */
export const ALL_LANGUAGES = {
  ar: 'Arabic',
  bg: 'Bulgarian',
  cs: 'Czech',
  da: 'Danish',
  de: 'German',
  el: 'Greek',
  en: 'English',
  es: 'Spanish',
  et: 'Estonian',
  fi: 'Finnish',
  fr: 'French',
  he: 'Hebrew',
  hi: 'Hindi',
  hr: 'Croatian',
  hu: 'Hungarian',
  id: 'Indonesian',
  it: 'Italian',
  ja: 'Japanese',
  ko: 'Korean',
  lt: 'Lithuanian',
  lv: 'Latvian',
  ms: 'Malay',
  nl: 'Dutch',
  no: 'Norwegian',
  pl: 'Polish',
  pt: 'Portuguese',
  ro: 'Romanian',
  ru: 'Russian',
  sk: 'Slovak',
  sl: 'Slovenian',
  sv: 'Swedish',
  sw: 'Swahili',
  tr: 'Turkish',
  uk: 'Ukrainian',
  vi: 'Vietnamese',
  zh: 'Chinese',
} as const;

export type LanguageCode = keyof typeof ALL_LANGUAGES;

/** Per-engine supported language codes. */
export const ENGINE_LANGUAGES: Record<string, readonly LanguageCode[]> = {
  qwen: ['zh', 'en', 'ja', 'ko', 'de', 'fr', 'ru', 'pt', 'es', 'it'],
  qwen_custom_voice: ['zh', 'en', 'ja', 'ko', 'de', 'fr', 'ru', 'pt', 'es', 'it'],
  supertonic: [
    'ar',
    'bg',
    'cs',
    'da',
    'de',
    'el',
    'en',
    'es',
    'et',
    'fi',
    'fr',
    'hi',
    'hr',
    'hu',
    'id',
    'it',
    'ja',
    'ko',
    'lt',
    'lv',
    'nl',
    'pl',
    'pt',
    'ro',
    'ru',
    'sk',
    'sl',
    'sv',
    'tr',
    'uk',
    'vi',
  ],
} as const;

/** Helper: get language options for a given engine. */
export function getLanguageOptionsForEngine(engine: string) {
  const codes = ENGINE_LANGUAGES[engine] ?? ENGINE_LANGUAGES.qwen;
  return codes.map((code) => ({
    value: code,
    label: ALL_LANGUAGES[code],
  }));
}

// ── Backwards-compatible exports used elsewhere ──────────────────────
export const SUPPORTED_LANGUAGES = ALL_LANGUAGES;
export const LANGUAGE_CODES = Object.keys(ALL_LANGUAGES) as LanguageCode[];
export const LANGUAGE_OPTIONS = LANGUAGE_CODES.map((code) => ({
  value: code,
  label: ALL_LANGUAGES[code],
}));
