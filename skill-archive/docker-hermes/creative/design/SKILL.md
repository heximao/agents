---
name: design
description: "Design process, taste, and token specs for web/product design artifacts."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, html, prototype, ux, ui, tokens, design-system, wcag, accessibility, tailwind]
    related_skills: [popular-web-designs, diagramming, p5js]
---

# Design

Two complementary design skills in one:

| Section | What it covers | Use when... |
|---------|---------------|-------------|
| **Design process** | How to scope a brief, produce variants, verify artifacts, avoid AI slop | Creating from-scratch designed artifacts (landing page, prototype, deck, component lab) |
| **DESIGN.md tokens** | Google's formal design-system spec format | Authoring a persistent, machine-readable design-system spec file |

**Also available:** `popular-web-designs` skill has 54 ready-to-paste brand design systems (Stripe, Linear, Vercel, etc.) for matching a known brand's look.

---

## Decision Table

| Skill | What it gives you | Use when the user wants... |
|-------|-------------------|---------------------------|
| **This skill — process** | Design process and taste | a from-scratch designed artifact with no specific brand dictated |
| **This skill — tokens** | DESIGN.md spec format | a formal, persistent design-system spec file |
| **popular-web-designs** | 54 brand design systems | "make it look like Stripe / Linear / Vercel" |

These compose: use `popular-web-designs` for visual vocabulary, this skill for process and tokens.

---

# Part 1: Design Process

Act as an expert designer. HTML is the default tool, but the medium changes by assignment: UX, interaction, visual, motion, deck, design-systems, or frontend prototyping.

## When To Use

- Landing pages, teaser pages, high-fidelity prototypes
- Interactive product mockups, visual option boards
- Component explorations, design-system previews
- HTML slide decks, motion studies, onboarding flows
- Dashboard concepts, settings, command palettes, modals, cards, forms
- Redesigns based on screenshots, repos, brand docs, or UI kits

**Do NOT use for:** pure DESIGN.md token authoring (use Part 2 below), or matching a known brand's look (use `popular-web-designs`).

## Core Principle: Start From Context, Not Vibes

Before designing, look for source context:
1. Brand docs, existing product screenshots, current repo components
2. Design tokens, UI kits, prior mockups, reference models
3. Copy docs, constraints from legal/product/engineering

If a repo is available, inspect actual source files before inventing UI: theme files, token files, global stylesheets, layout scaffolds, component files.

## Workflow

1. **Understand the brief** — What is being designed? For whom? What artifact at the end?
2. **Gather context** — Read supplied docs, screenshots, repo files, or design assets
3. **Define the design system** — colors, type, spacing, radii, shadows, motion, components
4. **Choose the right format** — static comparison, clickable prototype, HTML deck, component lab, motion study
5. **Build the artifact** — single self-contained HTML file, preserve prior versions
6. **Verify** — confirm file exists, check syntax, browser console errors, screenshots
7. **Report** — artifact path, what was created, caveats, next decision

## Artifact Format Rules

- Single self-contained `.html` file with embedded CSS/JS
- CSS variables for tokens, CSS grid for layout, container queries
- Responsive behavior unless intentionally fixed-size
- Real focus/hover states, `prefers-reduced-motion` handling
- Mobile hit targets at least 44px, print text at least 12pt
- For decks: 1920×1080, keyboard navigation, visible slide count

## Variation Rules

When exploring, default to at least three options:
1. **Conservative** — closest to existing patterns / lowest risk
2. **Strong-fit** — best interpretation of the brief
3. **Divergent** — more novel, useful for discovering taste boundaries

## Anti-Slop Rules

Avoid common AI design sludge:
- Aggressive gradient backgrounds, glassmorphism by default
- Emoji unless the brand uses them
- Generic SaaS cards with icons everywhere
- Left-border accent callout cards
- Fake dashboards filled with arbitrary numbers
- Stock-photo hero sections
- Oversized rounded rectangles as a substitute for hierarchy
- Rainbow palettes, vague labels ("Insights," "Growth," "Scale")
- Decorative SVG illustrations pretending to be product imagery

## Content Discipline

Do not add filler content. Every element must earn its place. Avoid fake metrics, decorative stats, generic feature grids, placeholder testimonials, AI-generated fluff sections.

## Typography

Use the existing type system if one exists. If not, choose deliberately:
- **Editorial:** serif or humanist headline with restrained sans body
- **Software/productivity:** precise sans with strong numeric treatment
- **Luxury/minimal:** fewer weights, more spacing discipline
- **Technical:** mono accents only, not mono everywhere
- **Deck:** large, clear, high contrast

## Color

Use brand/design-system colors first. If no palette exists:
- Define a small system with neutrals, surface, ink, muted text, border, accent
- Use one primary accent unless the assignment calls for more
- Prefer oklch for harmonious invented palettes
- Check contrast for important text and controls

## Deck Rules

- Fixed-size canvas (1920×1080, 16:9) scaled to viewport
- Keyboard navigation, visible slide count, localStorage persistence
- 1–2 background colors max, keep slides sparse
- Don't hand-wave as markdown bullets — create a designed artifact

## Prototype Rules

- Make the primary path clickable
- Include key states: default, hover/focus, loading, empty, error, success
- Expose variations with in-page controls when useful
- Design the flow, not just the first screen

## Verification

Before final response:
- File exists at stated path, HTML saved completely
- Open in browser, check console errors
- Test key interactions, light/dark variants, responsive breakpoints
- Never say "done" if the file was not actually written

---

# Part 2: DESIGN.md Token Spec

DESIGN.md is Google's open spec (Apache-2.0) for describing a visual identity to coding agents. One file combines YAML front matter (machine-readable tokens) and Markdown body (human-readable rationale).

## When to use

- User asks for a DESIGN.md file, design tokens, or a design system spec
- User wants consistent UI/brand across multiple projects
- User pastes an existing DESIGN.md and asks to lint, diff, export, or extend it
- User wants WCAG accessibility validation on their color palette

## File anatomy

```md
---
version: alpha
name: Heritage
description: Architectural minimalism meets journalistic gravitas.
colors:
  primary: "#1A1C1E"
  secondary: "#6C7278"
  tertiary: "#B8422E"
  neutral: "#F7F5F2"
typography:
  h1:
    fontFamily: Public Sans
    fontSize: 3rem
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
rounded:
  sm: 4px
  md: 8px
  lg: 16px
spacing:
  sm: 8px
  md: 16px
  lg: 24px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.sm}"
    padding: 12px
---

## Overview
Architectural Minimalism meets Journalistic Gravitas...

## Colors
- **Primary (#1A1C1E):** Deep ink for headlines and core text.
...
```

## Token types

| Type | Format | Example |
|------|--------|---------|
| Color | `#` + hex (sRGB) | `"#1A1C1E"` |
| Dimension | number + unit | `48px`, `-0.02em` |
| Token reference | `{path.to.token}` | `{colors.primary}` |
| Typography | object with fontFamily, fontSize, etc. | see above |

Component property whitelist: `backgroundColor`, `textColor`, `typography`, `rounded`, `padding`, `size`, `height`, `width`. Variants are separate entries (`button-primary-hover`), not nested.

## Canonical section order

1. Overview (alias: Brand & Style)
2. Colors
3. Typography
4. Layout (alias: Layout & Spacing)
5. Elevation & Depth
6. Shapes
7. Components
8. Do's and Don'ts

## CLI Commands

```bash
# Validate structure + token references + WCAG contrast
npx -y @google/design.md lint DESIGN.md

# Compare two versions, fail on regression
npx -y @google/design.md diff DESIGN.md DESIGN-v2.md

# Export to Tailwind theme JSON
npx -y @google/design.md export --format tailwind DESIGN.md > tailwind.theme.json

# Export to W3C DTCG JSON
npx -y @google/design.md export --format dtcg DESIGN.md > tokens.json
```

## Pitfalls

- Don't nest component variants. `button-primary.hover` is wrong; `button-primary-hover` as sibling is right.
- Hex colors must be quoted strings. Negative dimensions too.
- Section order is enforced.
- Token references resolve by dotted path. `{colors.primary}` works; `{primary}` does not.

---

## Quick Design Sketches (Throwaway Mockups)

When the user wants to **see a design direction before committing** — exploring a UI/UX idea as disposable HTML mockups — use this workflow. Generate 2-3 interactive variants so the user can compare visual directions side-by-side.

### When to sketch vs design

| Intent | Approach |
|--------|----------|
| "Sketch this screen", "show me what X could look like" | Sketch (below) — quick, disposable, comparative |
| "Build me a landing page", "design a deck" | Full design process (above) — polished, single direction |
| "Make it look like Stripe" | `popular-web-designs` skill — brand-specific templates |

### Sketch Workflow

1. **Intake** — Get three things (one question at a time):
   - **Feel:** "What should this feel like?" (adjectives, emotions, vibe)
   - **References:** "What apps/sites capture the feel you're imagining?"
   - **Core action:** "What's the single most important thing a user does on this screen?"

2. **Build 2-3 variants** — Each takes a DIFFERENT design stance, not different pixel values:
   - **Density:** compact / airy / ultra-dense (pick two contrasting poles)
   - **Emphasis:** content-first / action-first / tool-first
   - **Aesthetic:** editorial / utilitarian / playful
   - **Layout:** single-column / sidebar / split-pane

3. **Each variant is a single self-contained HTML file:**
   - Inline `<style>`, system fonts or one Google Font
   - Realistic fake content (not "Lorem ipsum")
   - Interactive: links clickable, hovers real, at least one state transition
   - Verify with `browser_vision` — don't just hope it renders

4. **Head-to-head comparison** — Present as a table, opinionate:

```markdown
| Dimension | Calm editorial | Utilitarian dense | Playful split |
|-----------|----------------|-------------------|---------------|
| Density   | Low            | High              | Medium        |
| Feel      | Calm, trusted  | Sharp, tool-like  | Inviting      |
```

Let the user pick a winner, combine two into a hybrid, or ask for another round.

### Output Structure

```
sketches/
├── 001-calm-editorial/
│   ├── index.html
│   └── README.md       # Design stance, key choices, trade-offs
├── 001-utilitarian-dense/
│   ├── index.html
│   └── README.md
└── 001-playful-split/
    ├── index.html
    └── README.md
```

### Interactivity Bar

A sketch is interactive enough when the user can:
1. Click a primary action and something visible happens
2. See one meaningful state transition (filter, toggle, open/close)
3. Hover recognizable affordances

More than that is over-engineering a throwaway. Less than that is a screenshot.

---

## Rules for Hermes Agents

1. Gather context before designing — don't start from vibes
2. Produce at least 3 variants for exploratory work
3. Verify artifacts exist and render without errors
4. Never claim verification unless it actually happened
5. Use `popular-web-designs` when the user wants a known brand's look
6. Use DESIGN.md tokens when the deliverable is a formal spec file
7. Keep final responses short: path, contents, verification status, next step
