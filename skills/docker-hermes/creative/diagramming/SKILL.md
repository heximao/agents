---
name: diagramming
description: "Create diagrams: Excalidraw (hand-drawn JSON), architecture (dark SVG/HTML), ASCII art."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [diagrams, Excalidraw, architecture, SVG, HTML, visualization, flowcharts, ASCII]
    related_skills: [ascii-art, p5js, claude-design]
---

# Diagramming

Three diagramming approaches — pick based on what you're making:

| Approach | Output | Best for |
|----------|--------|----------|
| **Excalidraw** | `.excalidraw` JSON → hand-drawn style | Flowcharts, architecture, sequence diagrams, concept maps. Editable at excalidraw.com |
| **Architecture diagram** | Standalone `.html` with dark SVG | Tech infrastructure, cloud architecture, microservice topology. Professional dark aesthetic |
| **ASCII art** | Text in terminal/file | Quick diagrams in terminal, documentation, README files |

## Decision Flow

1. **User wants editable diagram** → Excalidraw (drag-and-drop onto excalidraw.com)
2. **User wants polished tech/architecture diagram** → Architecture diagram (dark SVG)
3. **User wants quick terminal diagram** → ASCII art (see `ascii-art` skill)
4. **User wants interactive/generative visualization** → p5.js (see `p5js` skill)

---

# Excalidraw

Create diagrams by writing Excalidraw element JSON and saving as `.excalidraw` files. Drag-and-drop onto [excalidraw.com](https://excalidraw.com) for viewing/editing. No accounts, API keys, or rendering libraries needed.

## Workflow

1. Write elements JSON — an array of Excalidraw element objects
2. Wrap in standard envelope and save with `write_file`:
```json
{
  "type": "excalidraw",
  "version": 2,
  "source": "hermes-agent",
  "elements": [ ... ],
  "appState": { "viewBackgroundColor": "#ffffff" }
}
```
3. Optionally upload for shareable link: `python skills/creative/diagramming/scripts/upload.py diagram.excalidraw`

## Element Format

### Required Fields (all elements)
`type`, `id` (unique string), `x`, `y`, `width`, `height`

### Element Types

**Rectangle:**
```json
{ "type": "rectangle", "id": "r1", "x": 100, "y": 100, "width": 200, "height": 100,
  "roundness": { "type": 3 }, "backgroundColor": "#a5d8ff", "fillStyle": "solid",
  "boundElements": [{ "id": "t_r1", "type": "text" }] }
```

**Labeled shape** (container binding — required for text on shapes):
```json
{ "type": "text", "id": "t_r1", "x": 105, "y": 110, "width": 190, "height": 25,
  "text": "Hello", "fontSize": 20, "fontFamily": 1, "strokeColor": "#1e1e1e",
  "textAlign": "center", "verticalAlign": "middle",
  "containerId": "r1", "originalText": "Hello", "autoResize": true }
```

> **WARNING:** Do NOT use `"label": { "text": "..." }` on shapes — it's silently ignored. Always use container binding.

**Arrow with bindings:**
```json
{ "type": "arrow", "id": "a1", "x": 300, "y": 150, "width": 150, "height": 0,
  "points": [[0,0],[150,0]], "endArrowhead": "arrow",
  "startBinding": { "elementId": "r1", "fixedPoint": [1, 0.5] },
  "endBinding": { "elementId": "r2", "fixedPoint": [0, 0.5] } }
```

### Sizing Guidelines
- Minimum `fontSize`: 16 for body, 20 for titles, NEVER below 14
- Minimum shape size: 120x60 for labeled rectangles
- Leave 20-30px gaps between elements
- **Text contrast is CRITICAL** — never light gray on white. Minimum: `#757575`
- Do NOT use emoji — they don't render in Excalidraw's font

### Color Palette (Quick Reference)

| Use | Fill Color | Hex |
|-----|-----------|-----|
| Primary / Input | Light Blue | `#a5d8ff` |
| Success / Output | Light Green | `#b2f2bb` |
| Warning / External | Light Orange | `#ffd8a8` |
| Processing / Special | Light Purple | `#d0bfff` |
| Error / Critical | Light Red | `#ffc9c9` |
| Notes / Decisions | Light Yellow | `#fff3bf` |
| Storage / Data | Light Teal | `#c3fae8` |

### Drawing Order (z-order)
Array order = z-order (first = back, last = front). Emit progressively:
bg_zone → shape1 → text_for_shape1 → arrow1 → shape2 → text_for_shape2 → ...

For full details: `skill_view(name="diagramming", file_path="references/excalidraw-detail.md")`

---

# Architecture Diagrams

Generate professional, dark-themed technical architecture diagrams as standalone HTML with inline SVG. No external tools, no API keys, no rendering libraries.

## Workflow

1. User describes system architecture (components, connections, technologies)
2. Generate HTML following the design system
3. Save with `write_file` to a `.html` file
4. User opens in any browser — works offline, no dependencies

## Design System

### Color Palette (Semantic Mapping)

| Component Type | Fill (rgba) | Stroke (Hex) |
| :--- | :--- | :--- |
| **Frontend** | `rgba(8, 51, 68, 0.4)` | `#22d3ee` (cyan-400) |
| **Backend** | `rgba(6, 78, 59, 0.4)` | `#34d399` (emerald-400) |
| **Database** | `rgba(76, 29, 149, 0.4)` | `#a78bfa` (violet-400) |
| **AWS/Cloud** | `rgba(120, 53, 15, 0.3)` | `#fbbf24` (amber-400) |
| **Security** | `rgba(136, 19, 55, 0.4)` | `#fb7185` (rose-400) |
| **Message Bus** | `rgba(251, 146, 60, 0.3)` | `#fb923c` (orange-400) |
| **External** | `rgba(30, 41, 59, 0.5)` | `#94a3b8` (slate-400) |

### Typography & Background
- **Font:** JetBrains Mono (Monospace), Google Fonts
- **Background:** Slate-950 (`#020617`) with 40px grid pattern

### Implementation Details
- Components: rounded rectangles (`rx="6"`) with 1.5px strokes
- Double-rect masking: opaque background + semi-transparent styled rect
- Draw arrows early (behind component boxes)
- Security flows: dashed lines in rose color
- Legend: outside all boundary boxes, 20px below lowest boundary

### Output Requirements
- Single self-contained `.html` file
- No external dependencies (except Google Fonts)
- No JavaScript — pure CSS for animations

For the full HTML template: `skill_view(name="diagramming", file_path="templates/architecture-template.html")`

---

## Pitfalls

### Excalidraw
- Do NOT use `"label"` property on shapes — use container binding
- Always include `fontFamily: 1` on text elements
- Text `x`/`y`/`width`/`height` are approximate — Excalidraw recalculates on load
- `originalText` should match `text`
- Place bound text immediately after its container in the array

### Architecture Diagrams
- Legend MUST be outside all boundary boxes
- Use double-rect technique to prevent arrows showing through semi-transparent fills
- Message buses go in gaps between services, not overlapping
- Minimum 40px vertical gap between components
