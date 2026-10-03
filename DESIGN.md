# PlaceIntel Design System

Last updated: 2026-07-11 - production trust hardening

This file owns the durable visual and interaction rules for PlaceIntel. Product
flows and system boundaries live in `docs/architecture.md`; feature-specific
acceptance criteria live in `tasks/` PRDs.

## Product Character

PlaceIntel is a private operational intelligence tool. It should feel calm,
exact, evidence-first, and ready for repeated work. It is not a travel magazine,
map browser, marketing site, or decorative AI demo.

Design priorities, in order:

1. Evidence and current state are easy to scan.
2. The next action is obvious and recoverable.
3. Dense information remains quiet and ordered.
4. Keyboard, mobile, light, and dark modes are first-class.
5. Visual personality comes from typography, rules, and data hierarchy, not
   decoration.

## Visual Foundation

The current CSS tokens are authoritative. Do not replace them with a generic
dashboard palette.

| Token role | Current direction | Use |
| --- | --- | --- |
| Paper | warm near-white / deep neutral in dark mode | page and tool surfaces |
| Ink | near-black / high-contrast near-white | primary content |
| Accent | muted red | primary command, focus, selected state |
| Success | restrained green | verified healthy state only |
| Danger | red distinct from accent | destructive and failed state |
| Rules | cool neutral grays | borders, separators, skeletons |

The `ui-ux-pro-max` 2026-07-11 recommendation correctly identified a
data-dense drill-down product and WCAG requirements. Its dark slate/green palette
and Lora/Raleway pairing were rejected because they conflict with the existing
PlaceIntel identity, the project palette constraints, and local system-font
performance. Keep the existing `--serif`, `--sans`, and `--mono` stacks.

## Layout

- The top bar owns brand, language, theme, model, and system access.
- The four top-level work modes remain `Scout`, `Shop`, `Library`, and `Ask`.
- Top-level sections are unframed page bands, not floating cards.
- Cards are only for repeated places, evidence items, and true modal content.
- Never put a card inside another card.
- Standard corner radius is 8px or less for new elements. Existing 12px legacy
  shells may remain until the owning component is intentionally revised.
- Touch targets are at least 44px. Fixed-format controls use stable dimensions.
- Body text is at least 16px on mobile. No viewport-scaled font sizes.

## Typography

- Use system sans for controls, metadata, and working text.
- Use the existing restrained serif for true page statements and report titles,
  never for compact operational labels.
- Use mono for job ids, model ids, hashes, and machine evidence.
- Letter spacing is `0`; never compress labels with negative tracking.
- Long identifiers wrap or truncate with an accessible full-value affordance.

## Interaction

- Commands use text or icon plus text when the action is not universally known.
- Familiar icon-only controls need an accessible name and visible tooltip.
- Primary buttons disable while submitting and retain stable width/height.
- Errors appear beside the failing control, use `role="alert"`, and include a
  concrete next action.
- Loading, empty, setup-required, queued, running, interrupted, failed, and done
  are distinct states.
- Enter transitions use 150-300ms ease-out; exits use ease-in. No layout-shifting
  scale hover effects.
- Respect `prefers-reduced-motion`; job and evidence content updates stay instant.

## Auth Gate

The selected image-generated design reference was reviewed in three iterations
on 2026-07-11. The chosen direction is a landscape app entry, not a marketing
page:

- `PLACEINTEL` remains a first-viewport brand signal in the top-left.
- Exact headline: `Walk in informed.`
- Supporting line: `Private place intelligence for invited members.`
- A compact, unframed sign-in form is no wider than 420px.
- Email, password, sign-in, and Google controls are at least 44px high.
- The focus field uses the existing red accent and an obvious focus ring.
- `Invite-only access` and `System ready` are visible but subordinate.
- Language and theme remain available before login.
- Below the fold, only subdued Scout/Shop/Library/Ask skeletons may appear.
  Never expose cached names, reviews, addresses, reports, jobs, or questions.
- Reserve fixed error/status height so validation does not shift the form.

The generated bitmap was a design reference only. The shipped auth gate is
native HTML/CSS and must not depend on a generated image.

## Evidence UI

- Every AI finding displays confidence and one or more source-review references.
- A source reference is a button/link, not decorative text; activating it opens
  or focuses the matching raw review.
- Unsupported findings are not presented as normal grounded findings.
- Original and translated evidence remain visually distinguishable.
- Coverage statements name rows, text-bearing rows, and processed content; never
  imply unread text was analyzed.

## Operations UI

- Queue state belongs in the existing job timeline, not a new dashboard card.
- System status shows only non-secret counts, budgets, queue depth, and health.
- Healthy/failed information always includes text or an icon, not color alone.
- Raw queries, review text, questions, credentials, paths, and user identifiers
  never appear in telemetry summaries.

## Responsive and Accessibility Gate

Verify at 375px, 768px, 1024px, and 1440px:

- no horizontal scroll;
- no clipped controls or labels;
- focus order follows visual order;
- tab and dialog keyboard contracts remain intact;
- light and dark contrast meet WCAG AA;
- form errors are announced;
- motion reduction is honored;
- the dossier focus trap and opener restoration still pass.

## Change Rule

Update `DESIGN.md` in the same change when an intentional visual token,
top-level layout, shared component state, responsive rule, auth surface, or
evidence interaction changes. Feature PRDs may add page-specific rules, but they
must point back here rather than create a second global design system.
