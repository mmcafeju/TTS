import {
  AudioLines,
  BookOpen,
  Box,
  Captions,
  type LucideIcon,
  Mic,
  Radio,
  Repeat,
  ScrollText,
  Settings,
  Sparkles,
  Volume2,
  Wand2,
} from 'lucide-react';

/**
 * Help / tutorial content data for the Voicebox Web UI.
 *
 * Structure:
 *  - helpOverview:  App overview (differentiation + generation specs).
 *  - helpFeatures:  In-app tabs, each with a bilingual glossary and an
 *                   optional linked tutorial.
 *  - helpTutorials: Step-by-step tutorials (steps/specs text lives in i18n).
 *
 * Localized titles/descriptions live in i18n (`help.*`); this module owns the
 * structure, order, icons, tutorial routes, and terminology.
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

export interface HelpOverview {
  id: 'overview';
  titleKey: string;
  descriptionKey: string;
  icon: LucideIcon;
  specsKey: string;
  featuresKey: string;
  terms: HelpTerm[];
}

export interface HelpFeature {
  id: string;
  titleKey: string;
  descriptionKey: string;
  path: HelpFeaturePath;
  icon: LucideIcon;
  terms: HelpTerm[];
  tutorialId?: HelpTutorialId;
}

export interface HelpTutorial {
  id: HelpTutorialId;
  index: number;
  titleKey: string;
  subtitleKey: string;
  icon: LucideIcon;
  featureId: string;
  targetPath: HelpFeaturePath;
  terms: HelpTerm[];
  specsKey?: string;
  stepsKey: string;
}

export type HelpTutorialId =
  | 'voice-cloning'
  | 'repaint'
  | 'vc-tutorial'
  | 'instruct'
  | 'long-text'
  | 'qwen-guide'
  | 'supertonic-guide';

export const helpOverview: HelpOverview = {
  id: 'overview',
  titleKey: 'help.overview.title',
  descriptionKey: 'help.overview.description',
  icon: BookOpen,
  specsKey: 'help.overview.specs',
  featuresKey: 'help.overview.features',
  terms: [
    { ko: '로컬 실행', en: 'Local / Offline' },
    { ko: '보이스 클로닝', en: 'Voice Cloning' },
    { ko: '문장 단위 재생성', en: 'Chunk-level Repaint' },
    { ko: '에이전트 연동', en: 'MCP Agent Integration' },
  ],
};

export const helpFeatures: HelpFeature[] = [
  {
    id: 'generate',
    titleKey: 'help.features.generate.title',
    descriptionKey: 'help.features.generate.description',
    path: '/',
    icon: Volume2,
    tutorialId: 'repaint',
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
    tutorialId: 'voice-cloning',
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
    tutorialId: 'vc-tutorial',
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

export const helpTutorials: HelpTutorial[] = [
  {
    id: 'voice-cloning',
    index: 1,
    titleKey: 'help.tutorials.voice-cloning.title',
    subtitleKey: 'help.tutorials.voice-cloning.subtitle',
    icon: Mic,
    featureId: 'voices',
    targetPath: '/voices',
    specsKey: 'help.tutorials.voice-cloning.specs',
    stepsKey: 'help.tutorials.voice-cloning.steps',
    terms: [
      { ko: '음성 클로닝', en: 'Voice Cloning' },
      { ko: '샘플', en: 'Voice Sample' },
      { ko: '참조 텍스트', en: 'Reference Text' },
      { ko: '음성 프로필', en: 'Voice Profile' },
    ],
  },
  {
    id: 'repaint',
    index: 2,
    titleKey: 'help.tutorials.repaint.title',
    subtitleKey: 'help.tutorials.repaint.subtitle',
    icon: Repeat,
    featureId: 'generate',
    targetPath: '/',
    stepsKey: 'help.tutorials.repaint.steps',
    terms: [
      { ko: '청크', en: 'Chunk' },
      { ko: '구간 재생성', en: 'Regenerate' },
      { ko: '시드', en: 'Seed' },
      { ko: '크로스페이드', en: 'Crossfade' },
    ],
  },
  {
    id: 'vc-tutorial',
    index: 3,
    titleKey: 'help.tutorials.vc.title',
    subtitleKey: 'help.tutorials.vc.subtitle',
    icon: Radio,
    featureId: 'vc',
    targetPath: '/vc',
    stepsKey: 'help.tutorials.vc.steps',
    terms: [
      { ko: '음성 변환', en: 'Voice Conversion' },
      { ko: 'RVC', en: 'Retrieval-based Voice Conversion' },
      { ko: 'F0', en: 'Fundamental Frequency' },
      { ko: '에폭', en: 'Epoch' },
    ],
  },
  {
    id: 'instruct',
    index: 4,
    titleKey: 'help.tutorials.instruct.title',
    subtitleKey: 'help.tutorials.instruct.subtitle',
    icon: Sparkles,
    featureId: 'generate',
    targetPath: '/',
    specsKey: 'help.tutorials.instruct.specs',
    stepsKey: 'help.tutorials.instruct.steps',
    terms: [
      { ko: '전달 지시사항', en: 'Delivery Instruction' },
      { ko: '감정', en: 'Emotion' },
      { ko: '속도', en: 'Pace' },
      { ko: '톤', en: 'Tone' },
    ],
  },
  {
    id: 'long-text',
    index: 5,
    titleKey: 'help.tutorials.long-text.title',
    subtitleKey: 'help.tutorials.long-text.subtitle',
    icon: ScrollText,
    featureId: 'generate',
    targetPath: '/',
    specsKey: 'help.tutorials.long-text.specs',
    stepsKey: 'help.tutorials.long-text.steps',
    terms: [
      { ko: '장문', en: 'Long-form Text' },
      { ko: '청크 분할', en: 'Chunk Splitting' },
      { ko: '크로스페이드', en: 'Crossfade' },
      { ko: '문장 마커', en: 'Sentence Marker' },
    ],
  },
  {
    id: 'qwen-guide',
    index: 6,
    titleKey: 'help.tutorials.qwen-guide.title',
    subtitleKey: 'help.tutorials.qwen-guide.subtitle',
    icon: Sparkles,
    featureId: 'generate',
    targetPath: '/',
    stepsKey: 'help.tutorials.qwen-guide.steps',
    terms: [
      { ko: 'Qwen TTS', en: 'Qwen TTS' },
      { ko: 'Qwen CustomVoice', en: 'Qwen CustomVoice' },
      { ko: '표현 태그', en: 'Expression Tags' },
      { ko: '보이스 클로닝', en: 'Voice Cloning' },
    ],
  },
  {
    id: 'supertonic-guide',
    index: 7,
    titleKey: 'help.tutorials.supertonic-guide.title',
    subtitleKey: 'help.tutorials.supertonic-guide.subtitle',
    icon: Volume2,
    featureId: 'generate',
    targetPath: '/',
    stepsKey: 'help.tutorials.supertonic-guide.steps',
    terms: [
      { ko: 'Supertonic 3', en: 'Supertonic 3' },
      { ko: '프리셋 목소리', en: 'Preset Voice' },
      { ko: 'CPU 전용', en: 'CPU-only' },
      { ko: '다국어', en: 'Multilingual' },
    ],
  },
];

export function getHelpFeature(id: string): HelpFeature {
  return helpFeatures.find((f) => f.id === id) ?? helpFeatures[0];
}

export function getHelpTutorial(id: string): HelpTutorial | undefined {
  return helpTutorials.find((t) => t.id === id);
}

export type HelpMenuItemId =
  | HelpOverview['id']
  | HelpFeature['id']
  | HelpTutorial['id'];

export const helpMenuOrder: HelpMenuItemId[] = [
  'overview',
  ...helpFeatures.map((f) => f.id),
  ...helpTutorials.map((t) => t.id),
];
