# Ops Hub Brand System

Ops Hub is the parent platform for operational tools used by appliance repair teams. The product family should feel practical, durable, structured, and field-service aware. The visual language is built around command centers, routing, handoffs, inventory flow, and reliable execution.

## Product Family

| Product | Role | Visual idea | Accent |
| --- | --- | --- | --- |
| Ops Hub | Command center and umbrella platform | central coordination hub | cyan `#22d3c5` |
| RouteDesk | Dispatch, triage, and route planning | route nodes and movement | amber `#f59e0b` |
| FieldDesk | Technician app and field execution | shield, location, on-site reliability | teal `#14b8a6` |
| PartsDesk | Parts, inventory, and recommendation flow | organized package flow | sky `#38bdf8` |

## Palette

Foundation:
- `#07111f` deep operations ink
- `#0b1626` dark panel base
- `#142338` raised surface
- `#203149` control surface

Text:
- `#f6f8fb` primary text
- `#d9e3ef` secondary text
- `#96a6ba` muted text

Signals:
- `#22d3c5` operational cyan
- `#f59e0b` amber action
- `#38bdf8` parts flow
- `#14b8a6` field teal
- `#ef4444` error
- `#22c55e` success

Use dark navy/slate as the default. Use cyan for ecosystem/coordination signals. Use amber for route urgency or action. Use each product accent sparingly in marks, active tabs, buttons, and focus states.

## Typography

Use `Inter` first, then `IBM Plex Sans`, then system UI fallbacks. Keep headings strong, compact, and operational. Body text should remain readable at dashboard density.

Rules:
- Do not use decorative display fonts.
- Do not use negative letter spacing.
- Keep product lockups clean and horizontal.
- Favor concise product copy over marketing language.

## Shape And Layout

The shared UI system uses:
- Radius: `8px` max for cards, panels, buttons, and controls.
- Borders: low-contrast slate/cyan mix.
- Shadows: deep navy, soft, functional.
- Backgrounds: dark operational grid plus restrained signal glow.
- Components: panels, cards, tabs, badges, tables, and forms share the same token names across apps.

## Logo System

The logos use one construction language:
- 64x64 icon grid
- dark navy structural stroke
- product accent fill
- cyan secondary signal
- simple geometric nodes, paths, shields, or packages
- horizontal lockups for headers
- icon-only marks for app icons, favicons, and compact nav

Avoid literal appliances, sports marks, crypto/cybersecurity visual tropes, and unrelated icon styles.

Assets live in [`docs/brand/assets`](brand/assets).

## Frontend Tokens

RouteDesk and PartsDesk currently consume local CSS token files:
- `dispatch-app/src/brand/tokens.css`
- `parts-app/src/brand/tokens.css`

Future web frontends should copy the token contract first, then override only:
- `--product-accent`
- `--product-accent-contrast`
- `--product-signal`

Shared token names such as `--panel-bg`, `--card-bg`, `--text-main`, `--accent`, `--panel-border`, and `--radius-xl` should remain stable so reusable components can move between apps.

## Usage Guidance

Do:
- Use one product accent per app.
- Keep Ops Hub links and ecosystem status in cyan/slate.
- Use amber for dispatch urgency and route actions.
- Use sky/cyan for parts evidence, inventory flow, and recommendations.
- Keep FieldDesk durable and high-contrast for outdoor/mobile use.

Do not:
- Add new gradients for each page.
- Introduce one-off card treatments.
- Add appliance illustrations to logos.
- Mix unrelated icon stroke weights.
- Use large rounded SaaS cards or playful imagery.
