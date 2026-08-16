---
name: Studiamo
description: Spaced Repetition & AI Learning Studio Design System
colors:
  primary: "#d97706"
  primary-hover: "#b45309"
  primary-bg: "#fef3c7"
  primary-border: "#fde68a"
  bg-main: "#f6f1e7"
  surface: "#ffffff"
  surface-2: "#fbf8f2"
  surface-deep: "#f3ebd9"
  border: "#e7dfd3"
  border-strong: "#dfd5c5"
  text-main: "#1c1917"
  text-muted: "#78716c"
  text-faint: "#a8a29e"
typography:
  display:
    fontFamily: "Outfit, Inter, sans-serif"
    fontWeight: 700
  body:
    fontFamily: "Outfit, Inter, sans-serif"
    fontWeight: 400
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  full: "9999px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.surface}"
    rounded: "{rounded.md}"
---

# Design System: Studiamo

## Overview

**Creative North Star: "The Warm Paper Codex"**

Studiamo is built around the tactile comfort of reading high-quality sepia paper rather than an aggressive digital screen. The design language prioritizes long-session reading ergonomics, high text contrast, clean spatial hierarchy, and inviting golden-amber accents for active recall triggers.

### Key Characteristics:
- Single permanent Warm Paper Sepia light theme (`#f6f1e7`).
- Warm stone text (`#1c1917` / `#78716c`) for maximum contrast and zero eye fatigue.
- Golden-amber primary action elements (`#d97706` / `#f59e0b`).
- Soft elevated surfaces (`#ffffff` & `#fbf8f2`) with subtle warm borders (`#e7dfd3`).

## Colors

The palette is derived from natural warm paper and ink tones paired with rich golden amber CTAs.

### Primary
- **Warm Golden Amber** (`#d97706`): Primary call-to-action buttons, active quiz triggers, key highlights, and active tab states.
- **Amber Glow Background** (`#fef3c7`): Soft highlight cards, badges, and notification callouts.

### Neutral
- **Paper Background** (`#f6f1e7`): The base canvas background for the entire application.
- **Card Surface** (`#ffffff`): Primary content cards, active study panels, and modals.
- **Secondary Surface** (`#fbf8f2`): Grouped list items, secondary containers, and sidebar surfaces.
- **Deep Surface** (`#f3ebd9`): Embedded studio panes, code/notes blocks, and footer accents.
- **Paper Border** (`#e7dfd3`): Card borders, list dividers, and subtle outlines.
- **Stone Ink (Main Text)** (`#1c1917`): High-contrast primary text for all headings, titles, and body content.
- **Muted Stone Ink** (`#78716c`): Subtitles, metadata, timestamps, and secondary labels.

### Named Rules
**The Single Light Theme Rule.** The app strictly runs on Warm Paper Sepia. Dark mode slate backgrounds (`bg-slate-900`, `bg-slate-800`) and blue/purple gradients are strictly prohibited.

## Typography

**Display Font:** Outfit (sans-serif)  
**Body Font:** Outfit / Inter (sans-serif)  

### Hierarchy
- **Display** (Bold, 36px–48px, line-height 1.15): Main page section titles and hero headlines.
- **Headline** (Bold, 20px–24px, line-height 1.2): Card titles, modal headers, and module section headers.
- **Title** (Semi-bold, 14px–16px, line-height 1.3): Item list titles, flashcard questions, and video names.
- **Body** (Regular, 13px–14px, line-height 1.5): Study notes, summaries, and descriptions.
- **Label** (Semi-bold, 10px–12px, uppercase tracking-wider): Badges, SRS stage indicators, and metadata tags.

## Layout

- **Container Bounds**: Max width 1280px (`max-w-7xl`) for dashboard layouts; central 600px–800px for quizzes & focus forms.
- **Spacing Rhythm**: 4px / 8px / 12px / 16px / 24px / 32px scale (`gap-4`, `p-5`, `space-y-4`).
- **Responsive Layout**: Desktop features a side-by-side Study Studio split view (42% video / 58% notes); mobile collapses cleanly into a single-pane vertical workflow.

## Elevation & Depth

Surfaces rely on tonal layering and crisp 1px borders (`#e7dfd3`) rather than heavy dark drop shadows.

### Shadow Vocabulary
- **Card Shadow** (`box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04)`): Subtle resting depth for white card containers.
- **CTA Button Shadow** (`box-shadow: 0 4px 12px rgba(217, 119, 6, 0.2)`): Soft amber glow under primary call-to-action buttons.

## Shapes

- **Card Radius**: 16px (`rounded-2xl`) for main containers, cards, and study modules.
- **Button & Input Radius**: 12px (`rounded-xl`) for interactive buttons, search fields, and form inputs.
- **Badge Radius**: 9999px (`rounded-full`) or 8px (`rounded-lg`) for compact metadata pills.

## Components

### Buttons
- **Primary CTA**: `bg-gradient-to-r from-[#f59e0b] to-[#d97706] text-[#1c1917] font-extrabold rounded-xl shadow-md`.
- **Secondary / Soft Button**: `bg-[#fef3c7] text-[#92400e] border border-[#fde68a] font-bold rounded-xl`.
- **Ghost / Outline Button**: `bg-[#fbf8f2] hover:bg-[#f3ebd9] text-[#1c1917] border border-[#e7dfd3] rounded-xl`.

### Cards & Containers
- **Primary Card**: White background (`#ffffff`), 1px paper border (`#e7dfd3`), 16px radius (`rounded-2xl`), 20px padding (`p-5`).
- **Secondary Item Card**: Soft cream background (`#fbf8f2`), 1px border (`#e7dfd3`), 12px radius (`rounded-xl`), 12px padding (`p-3`).

### Inputs
- **Text & Email Inputs**: Soft surface background (`#fcfaf6`), 1px border (`#e7dfd3`), stone text (`#1c1917`), 12px radius (`rounded-xl`), amber focus ring (`focus:border-[#d97706]`).
- **Range Sliders & Toggles**: Accent color forced to warm amber (`accent-color: #d97706`).

## Do's and Don'ts

### Do:
- **Do** maintain high contrast between text (`#1c1917` / `#44403c`) and paper backgrounds (`#f6f1e7` / `#ffffff`).
- **Do** use warm amber/gold for primary CTAs, active states, and important badges.
- **Do** keep cards crisp with 1px `#e7dfd3` borders and subtle tonal layering.

### Don't:
- **Don't** use dark mode slate backgrounds (`bg-slate-900`, `bg-slate-800`) or dark linear gradients.
- **Don't** use blue, indigo, or bright purple accent colors.
- **Don't** use white text (`text-white`) or low-contrast light grey (`text-slate-400`) on light surfaces.
