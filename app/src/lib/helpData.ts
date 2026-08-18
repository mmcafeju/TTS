import {
  AudioLines,
  Box,
  Captions,
  type LucideIcon,
  Mic,
  Radio,
  Settings,
  Volume2,
  Wand2,
} from 'lucide-react';

/**
 * Help / tutorial content data for the Voicebox Web UI.
 *
 * Each feature links to its in-app tab (tutorial target) and carries a small
 * bilingual glossary so technical terms show their English original next to
 * the localized menu name (용어 병기).
 *
 * Localized titles/descriptions live in i18n (`help.features.<id>.*`); this
 * module owns the structure, order, icons, tutorial routes, and terminology.
 */

export type HelpFeaturePath =
  | '/'
  | '/stories'
  | '/captures'
  | '/voices'
  | '/vc'
  | '/effects'
  | '/models'
  | '/settings';

export interface HelpTerm {
  ko: string;
  en: string;
}

export interface HelpFeature {
  id: string;
  titleKey: string;
  descriptionKey: string;
  path: HelpFeaturePath;
  icon: LucideIcon;
  terms: HelpTerm[];
}

export const helpFeatures: HelpFeature[] = [
  {
    id: 'generate',
    titleKey: 'help.features.generate.title',
    descriptionKey: 'help.features.generate.description',
    path: '/',
    icon: Volume2,
    terms: [
      { ko: '음성 합성', en: 'Text-to-Speech (TTS)' },
      { ko: '음성 프로필', en: 'Voice Profile' },
      { ko: '시드', en: 'Seed' },
      { ko: '청크', en: 'Chunk' },
      { ko: '출력 형식', en: 'Output Format' },
    ],
  },
  {
    id: 'stories',
    titleKey: 'help.features.stories.title',
    descriptionKey: 'help.features.stories.description',
    path: '/stories',
    icon: AudioLines,
    terms: [
      { ko: '스토리', en: 'Stories' },
      { ko: '내레이션', en: 'Narration' },
      { ko: '트랙', en: 'Track' },
      { ko: '캐릭터 음성', en: 'Character Voice' },
    ],
  },
  {
    id: 'captures',
    titleKey: 'help.features.captures.title',
    descriptionKey: 'help.features.captures.description',
    path: '/captures',
    icon: Captions,
    terms: [
      { ko: '오디오 캡처', en: 'Audio Capture' },
      { ko: '단축키', en: 'Hotkey / Shortcut' },
      { ko: '받아쓰기', en: 'Dictation' },
      { ko: '전사', en: 'Transcription' },
    ],
  },
  {
    id: 'voices',
    titleKey: 'help.features.voices.title',
    descriptionKey: 'help.features.voices.description',
    path: '/voices',
    icon: Mic,
    terms: [
      { ko: '음성 프로필', en: 'Voice Profile' },
      { ko: '샘플', en: 'Voice Sample' },
      { ko: '음성 클로닝', en: 'Voice Cloning' },
      { ko: '가져오기/내보내기', en: 'Import / Export' },
    ],
  },
  {
    id: 'vc',
    titleKey: 'help.features.vc.title',
    descriptionKey: 'help.features.vc.description',
    path: '/vc',
    icon: Radio,
    terms: [
      { ko: '음성 변환', en: 'Voice Conversion (VC)' },
      { ko: '타임스탬프', en: 'Timestamp' },
      { ko: '탐지 임계값', en: 'Detection Threshold' },
      { ko: '피치 이동', en: 'Pitch Shift' },
    ],
  },
  {
    id: 'effects',
    titleKey: 'help.features.effects.title',
    descriptionKey: 'help.features.effects.description',
    path: '/effects',
    icon: Wand2,
    terms: [
      { ko: '오디오 효과', en: 'Audio Effects' },
      { ko: '프리셋', en: 'Preset' },
      { ko: '이퀄라이저', en: 'Equalizer (EQ)' },
      { ko: '리버브', en: 'Reverb' },
    ],
  },
  {
    id: 'models',
    titleKey: 'help.features.models.title',
    descriptionKey: 'help.features.models.description',
    path: '/models',
    icon: Box,
    terms: [
      { ko: 'TTS 모델', en: 'TTS Model' },
      { ko: '모델 다운로드', en: 'Model Download' },
      { ko: 'GPU 가속', en: 'GPU Acceleration' },
    ],
  },
  {
    id: 'settings',
    titleKey: 'help.features.settings.title',
    descriptionKey: 'help.features.settings.description',
    path: '/settings',
    icon: Settings,
    terms: [
      { ko: '설정', en: 'Settings' },
      { ko: '서버 URL', en: 'Server URL' },
      { ko: '언어', en: 'Language' },
      { ko: '테마', en: 'Theme' },
    ],
  },
];

export function getHelpFeature(id: string): HelpFeature {
  return helpFeatures.find((f) => f.id === id) ?? helpFeatures[0];
}
