# NU Insights design system

The tokens and components live in `frontend/src/index.css`. This file explains them; if the two disagree, the CSS wins.

## Direction

A warm, quiet course tool. The landing page is one large headline, a "Start searching" button, and a single red orbital arc. The workspace has no decoration at all: cream surfaces, ink text, thin lines, and red used only as a small signal.

Avoid: logo-left nav bars, hero text paired with an image on the right, eyebrow labels, numbered step sections, feature-card grids, glass effects, glows, gradients, and "AI-powered" badges.

## Color

| Token | Value | Use |
| --- | --- | --- |
| `--canvas` | `#F3F0EE` | Page background |
| `--lifted` | `#FCFBFA` | Breakdowns window, row hover, nested surfaces |
| `--white` | `#FFFFFF` | Inputs, breakdown cards, settings panel |
| `--ink` / `--text` | `#141413` | Text, primary buttons, footer |
| `--text-soft` | `#3B3936` | Secondary text |
| `--text-muted` | `#5E5955` | Hints and metadata (6:1 on canvas) |
| `--line` / `--line-strong` | `#DDD6CF` / `#A9A098` | Dividers / control borders |
| `--accent` | `#C8102E` | Northeastern red: orbit arc, wordmark dot, selected-row bar, "One of" rule, list markers, links in settings, focus ring |
| `--danger` / `--danger-wash` | `#9F2316` / `#FBEBE8` | Error text / error background |

The red contrasts 5.3:1 with the canvas, so it can be used for text. Use it sparingly anyway. Buttons stay ink, not red, so red never reads as an error and errors always come with the wash background and a left rule. On the ink footer, focus rings use `--canvas`.

The red is used as a nod to the school, not an official mark. Do not imply that Northeastern endorses the app.

## Type

Sofia Sans from Google Fonts, falling back to Arial. Use one family and build hierarchy from size, weight, and tracking.

- Body: 17px, weight 450, line height 1.5.
- Headings: weight 650, tracking −0.02em. The landing headline (the app name) goes up to 200px at line height 0.92 and tracking −0.05em, with the tagline at up to 48px, weight 550.
- Small labels such as course codes: 13–15px, weight 700. No uppercase eyebrow labels.
- Reading text (descriptions, breakdowns): max width 66ch.

## Shape and depth

- Radii: `--r-chip` 6px (course chips, error blocks), `--r-control` 20px (buttons, breakdown cards), `--r-pill` (inputs, example chips).
- One shadow, `--shadow-lift`, used only by the settings panel. Everything else uses lines.

## Components

- **Buttons:** `.btn` with `.btn-ink` (primary), `.btn-outline`, or `.btn-quiet`; `.btn-sm` is a compact size. All are at least 44px tall.
- **Inputs:** `.input`, a pill shape with a 1.5px border. Labels use `.field-label` and help text uses `.hint`.
- **Placement list:** `.plan-list` shows the first five rows; a `.disclosure` button with a `.chevron` toggles "Show all (N)" / "Show less".
- **Prerequisite tree:** nested `.req-group` boxes labelled "All of" (solid ink rule) or "One of" (dashed red rule). The label carries the meaning; the rule style only reinforces it. Course codes appear as `.req-course` chips, and admission notes as italic `.req-note`.
- **Wordmark:** an ink ring with a red dot on its edge, followed by **NU** Insights. The favicon uses the same mark.

## Layout

- **Landing:** the name "NU Insights" as the headline, the tagline, a large ink "Start searching →" button (the arrow nudges right on hover and focus; it opens the workspace with the search field focused) with a muted "No account needed" line beside it, then "What you can do here": four term/description rows separated by thin lines (not cards, not numbered), and an ink footer with the non-affiliation and advisor caveat.
- **Workspace, 768px and up:** a header (wordmark that returns home, Model settings) above two windows. The left window starts with the optional major picker (a native datalist; Clear removes it), followed by campus-specific concentration selects and inline requirement disclosures. Program controls scroll within a bounded region so expanded requirements cannot hide course browsing. Results offer All courses / My major / My concentrations when applicable; concentration candidates are labeled with their current catalog year and remain separate from historical sample-plan courses. Selecting a course turns it into that course's detail view with "← Back to results". The query, scroll position, and selected row are kept, and focus returns to the selected row. The right window holds the breakdowns.
- **Workspace, under 768px:** a single column that scrolls as a page, with a sticky header; the breakdowns follow the left window.

## Accessibility

Use a visible 3px focus ring, touch targets of at least 44px, associated labels, and one status region per window instead of announcing the whole transcript. `prefers-reduced-motion` turns off the spinner and smooth scrolling. Hidden live regions sit inside positioned scroll containers so they cannot stretch the page.
