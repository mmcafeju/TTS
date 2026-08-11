---
title: Voicebox
created: 2026-08-11
tags:
  - project
  - tts
  - voicebox
---

# Voicebox

> 오픈소스 AI 음성 스튜디오 — 로컬에서 실행되는 음성 I/O 스택

- **생성일자**: 2026-08-11
- **타입**: 데스크톱 앱 + 로컬 서버 (Tauri + FastAPI)
- **핵심 스택**: React · TypeScript · Rust(Tauri) · Python(FastAPI) · MLX/PyTorch

## 프로젝트 개요

- 7개 TTS 엔진 (Qwen3-TTS, Qwen CustomVoice, LuxTTS, Chatterbox, TADA, Kokoro)
- 음성 클로닝, 프리셋 음성, 23개 언어 지원
- STT(Whisper), 글로벌 받아쓰기, MCP 에이전트 음성 출력
- SQLite 기반 로컬 저장, 로컬 우선(Local-first) 설계

## 디렉터리 구조

```
app/        공유 React 프론트엔드
tauri/      데스크톱 앱 (Tauri + Rust)
web/        웹 배포
backend/    Python FastAPI 서버
landing/    마케팅 사이트
scripts/    빌드 & 릴리스 스크립트
```

## 개발 메모

### 로그

- **2026-08-11** — 프로젝트 초기화. Git 저장소 생성, .gitignore 및 README 작성.

### 개발 노트

> 여기에 진행 중인 작업, 결정 사항, 트러블슈팅 기록을 추가한다.

### 할 일

- [ ] 추가 예정

### 참고 자료

- [Voicebox 공식 문서](https://docs.voicebox.sh)
- [TTS 엔진 통합 가이드](docs/content/docs/developer/tts-engines.mdx)
