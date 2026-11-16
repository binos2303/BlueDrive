# BlueDrive technical UI audit — 2026-11-07

Method: independent Assessment B, isolated from Assessment A. Source audit of `frontend/app` and `frontend/components`; no application source edits.

## Evidence and limits

The detector ran exactly once, with `impeccable.cmd detect --json frontend/app frontend/components`, exited **0**, and returned **`[]`**. The raw output is preserved in `docs/UI_AUDIT_DETECTOR_2026-11-07.json`. There are **0 reported rules, 0 reported locations, and 0 false positives to adjudicate**. The empty result is a limited automated signal; it does not establish keyboard, contrast, or behavioral correctness. Manual findings below are independent of that result.

Manual review covered shared primitives and the auth, Drive, account, workspace, organization, and platform administration surfaces. An inventory of all 140 non-test TS/TSX/CSS files in the requested directories appears below. Route wrappers were traced to their shared implementations. Review emphasis was user-facing JSX, CSS, state transitions, event handlers, asynchronous request ownership, and underlying formatting functions where they affect behavior.

**No rendered UI was inspected by this assessment.** The parent reports that browser control was unavailable and the native fallback was stopped before an app view rendered. Layouts, synthesized touch gestures, physical-device behavior, 200% zoom, actual accessibility-tree output, interaction timings, frame rate, and pixel contrast remain unverified. Contrast results below are calculations from current source values, not sampled pixels. No overlay was injected, no detector live server was started by B, and B created no temporary browser files. Parent-reported current ESLint and TypeScript checks passed; these are not accessibility or visual tests. Historical UI_REFINEMENT reports were not treated as current evidence.

## Implementation integrity verdict

**Fail the release-quality gate, while preserving the existing system.** BlueDrive has a coherent product-specific foundation: route-aware workspaces, real access-management flows, protected destructive actions, reusable controls, and semantic theme variables. The failures are repeated departures from those existing solutions: hand-built modal overlays alongside a working native `Dialog`, pale hard-coded backgrounds mixed with dark-theme status colors, and pointer-oriented file selection alongside partial keyboard support.

Recommendation: repair and reuse the existing primitives, then apply the same interaction contracts across file views and administration. Replacing the visual system would increase work without addressing these defects. It is like a building with a sound floor plan whose rooms use different locks: standardize the locks before rebuilding the house.

## Audit health score

Scores are provisional implementation scores, not a claim of rendered WCAG compliance.

| Dimension | Score | Evidence determining the score |
|---|---:|---|
| Accessibility | 2/4 | Labels, native dialogs, focus styles and live feedback exist; modal, file selection and contrast failures remain. |
| Performance | 3/4 | Lean dependency list, memoized sort/filter, bounded uploads and cancellation; file selection still scales with every rendered item. Runtime speed was not measured. |
| Theming | 2/4 | Strong light/dark semantic tokens; fixed light surfaces and white CTA text undermine dark-theme combinations. |
| Responsive design | 2/4 | Real breakpoints, container queries and scroll containment; custom modal height and inconsistent touch control sizes remain. No viewport was rendered. |
| Implementation integrity | 2/4 | Repeated modal, formatting and request-ownership drift despite reusable equivalents. |
| **Total** | **11/20** | **Acceptable — significant work needed** |

## Priorities

**16 findings: P0 0 · P1 7 · P2 8 · P3 1.** No whole-task blocker was confirmed without running the application. Prioritize the modal and file-selection contracts, then fix source-proven contrast combinations. Next address date sorting, error placement and stale organization-member requests. Keep responsive/performance risks explicit until exercised in a browser.

### T01 — [P1] Several modal flows omit the existing modal behavior

- **Location:** `frontend/components/drive/browser/DriveCreateFolderDialog.tsx:19`, `DriveMoveDialog.tsx:29`, `DriveShareDialog.tsx:25`; `frontend/components/admin/QuotaManagement.tsx:175`; `QuotaPlanPolicies.tsx:146` and `:157`.
- **Category:** Accessibility / Implementation integrity.
- **Source fact:** These are conditional fixed overlays. They do not use native `showModal`, inert the background, trap or restore focus, or handle Escape. Create/share autofocus an input; move/quota do not establish initial focus. The bulk-share form also lacks a dialog role. Global selection Escape handling recognizes `dialog[open]`, not these overlays (`useDriveSelection.ts:62`).
- **Impact:** Keyboard focus can escape behind a modal; move/quota opening can leave focus at the obscured trigger. Screen-reader users receive an `aria-modal` claim without corresponding behavior. Exact traversal was not browser-tested.
- **Standard:** WCAG 2.1.1, 2.4.3, 4.1.2; modal dialog interaction expectations.
- **Recommendation/trade-off:** Migrate these shells to `frontend/components/ui/Dialog.tsx:31`, which already calls `showModal` and handles cancel. Keep their business state and content. Extending the shared shell is smaller and more sustainable than independently implementing six focus managers. Like using the same door closer on every fire door, the common mechanism supplies the behavior consistently.
- **Suggested command:** `$impeccable harden`.

### T02 — [P1] List view cannot select items using the keyboard

- **Location:** `frontend/components/drive/browser/DriveListTable.tsx:129`; `frontend/components/drive/browser/useDriveSelection.ts:71` and `:96`; `DriveFileBrowser.tsx:599`.
- **Category:** Accessibility.
- **Source fact:** Rows only select on click and open on double-click. They have no checkbox, focus target, or keyboard selection handler. Nested controls expose drag, star and actions; the context menu includes Open but no Select. `aria-selected` is applied to an ordinary table row without an interactive grid selection model.
- **Impact:** A keyboard user can open a single item via Actions, but cannot reach the selection state needed for list-view bulk operations. Switching to grid supplies a workaround, so this is not classified as a universal P0.
- **Standard:** WCAG 2.1.1 and 4.1.2.
- **Recommendation:** Add explicit named selection checkboxes and share one selection-state contract across list and grid, or implement a complete grid pattern. Prefer checkboxes for the smallest native solution. It is the difference between providing a marked basket for picking files and requiring people to point at them.
- **Suggested command:** `$impeccable harden`.

### T03 — [P1] Grid child controls also trigger the card keyboard action

- **Location:** `frontend/components/drive/browser/DriveGrid.tsx:50`, `:52`, `:84`, `:123`, `:125`, `:158`.
- **Category:** Accessibility / Implementation integrity.
- **Source fact:** Each article has `role="button"`, `tabIndex=0`, and an Enter/Space handler, while containing native drag/star/menu buttons. The handler does not check `event.target === event.currentTarget`. Child click/pointer handlers stop propagation, but child key events are not stopped. Selection is only styled; the card exposes no pressed/selected state.
- **Impact:** Enter on a nested star/menu/drag control bubbles into `onOpen(item)`; Space can toggle the card selection as well as activate the child. This follows directly from the event handlers; the sequence has not been replayed in a browser.
- **Standard:** WCAG 2.1.1, 4.1.2.
- **Recommendation:** Separate the card's open/selection target from sibling action buttons; expose selection state. As an interim containment fix, handle only key events originating on the card itself. Like keeping a doorbell separate from the front-door handle, each target should do one thing.
- **Suggested command:** `$impeccable harden`.

### T04 — [P1] Dark-theme status text is placed on fixed light backgrounds

- **Location:** `frontend/components/ui/Toast.tsx:13`; `frontend/components/ui/Badge.tsx:12`; `frontend/components/drive/UploadManager.tsx:673`; `frontend/components/account/AccountProfilePanel.tsx:82`; `frontend/app/account/support/page.tsx:23`; `frontend/app/account/upgrade/page.tsx:40`; dark colors at `frontend/app/globals.css:50`.
- **Category:** Theming / Accessibility.
- **Source fact:** Status foregrounds change to bright dark-theme colors while `bg-green-50`, `bg-amber-50`, and `bg-rose-50` remain pale. Calculated ratios: dark success on green-50 **1.66:1**, warning on amber-50 **1.48:1**, danger on rose-50 **2.45:1**. Tailwind background definitions were read from the installed `frontend/node_modules/tailwindcss/theme.css:34`, `:70`, `:202` and converted from OKLCH to linear sRGB.
- **Impact:** Important errors, warning text and duplicate-resolution instructions lose text legibility in dark mode. These are source-derived values, not rendered samples. Badge currently has no observed call site, but Toast and the listed page states do.
- **Standard:** WCAG 1.4.3, normal text minimum 4.5:1.
- **Recommendation:** Add paired semantic status surface/foreground/border tokens and use them together. Retain the present status meanings. Like choosing ink and paper as a pair, changing only the ink cannot preserve readability.
- **Suggested command:** `$impeccable colorize`.

### T05 — [P1] Some sign-in and support CTAs bypass the dark-theme on-accent token

- **Location:** `frontend/components/workspaces/WorkspaceInviteAcceptance.tsx:83`, `:97`; `frontend/app/(auth)/admin-invite/page.tsx:41`; `frontend/app/account/support/page.tsx:18`; `frontend/components/ui/Tooltip.tsx:23`; tokens at `frontend/app/globals.css:36` and `:40`.
- **Category:** Theming / Accessibility.
- **Source fact:** These CTA links use `bg-brand-contrast text-white`; dark brand-contrast is `#a8b6ff`, yielding **1.94:1** against white. The shared Button correctly uses `text-on-accent` (`Button.tsx:11`). Tooltip uses white on dark-theme brand-dark `#e7ebff`, **1.18:1**; no Tooltip call site was found in the requested directories, so that part is a latent primitive defect.
- **Impact:** Invitation acceptance and configured support actions can be difficult to read in the app's dark theme.
- **Standard:** WCAG 1.4.3.
- **Recommendation:** Reuse the shared button/link style with on-accent text; give Tooltip a dedicated foreground/surface pair. Like a uniform's matching name badge, the label must change with its background.
- **Suggested command:** `$impeccable colorize`.

### T06 — [P1] Primary brand color is used for small light-theme links

- **Location:** `frontend/app/(admin)/admin/permissions/page.tsx:129` and `:130`; brand at `frontend/app/globals.css:4`.
- **Category:** Accessibility / Theming.
- **Source fact:** Small semibold links use `text-brand` (`#7288fa`) on the white surface. Calculated contrast is **3.17:1**. The existing brand-contrast token is intended for readable foreground use; white on light brand-contrast measures 5.47:1.
- **Impact:** The links to manage platform users and browse workspaces fall below normal-text AA contrast.
- **Standard:** WCAG 1.4.3.
- **Recommendation:** Use brand-contrast for text and reserve brand for appropriate non-text accents. Like using high-visibility lettering on a sign, the decorative paint is not automatically suitable for directions.
- **Suggested command:** `$impeccable colorize`.

### T07 — [P1] The custom Drive scrollbar removes its only visible focus treatment

- **Location:** `frontend/components/drive/DriveFileBrowser.tsx:905`–`:920`.
- **Category:** Accessibility.
- **Source fact:** The custom scrollbar is keyboard-focusable and handles scrolling keys, but applies `focus-visible:outline-none`; opacity is already 100%, including at rest, so `focus-visible:opacity-100` supplies no change. No focus ring/background is provided.
- **Impact:** Users tabbing through Drive cannot identify when this control has focus. Source establishes the missing focus difference; forced-colors rendering was not inspected.
- **Standard:** WCAG 2.4.7.
- **Recommendation:** Restore the shared focus ring and retain keyboard scrolling. Like illuminating the currently selected elevator button, focus should show which control receives the next key press.
- **Suggested command:** `$impeccable harden`.

### T08 — [P2] Date sorting sorts localized labels instead of timestamps

- **Location:** `frontend/components/drive/browser/drive-display-utils.ts:36`; formatting at `frontend/lib/drive-service.ts:230`–`:231`.
- **Category:** Implementation integrity.
- **Source fact:** `modifiedAt` retains the original timestamp, but sort uses `first.modified.localeCompare(second.modified, ..., {numeric:true})` after converting `modified` into a localized medium date string. A direct Node execution of the current sort returned **Newer, Older** for ascending `Dec 31, 2025` versus `Jan 1, 2024`.
- **Impact:** Ascending/descending Date modified does not reliably mean chronological order and loses time-of-day differences.
- **Recommendation:** Compare parsed `modifiedAt` timestamps with a safe missing-date policy; keep formatting only for display. Like sorting receipts by the printed month name instead of the actual date, the label should not determine chronology.
- **Suggested command:** `$impeccable harden`.

### T09 — [P2] Shared admin tabs expose an incomplete tab interaction model

- **Location:** `frontend/components/admin/AdminSegmentTabs.tsx:19`–`:26`; consumers `UserDirectory.tsx:151`, `AdminFileDirectory.tsx:168`.
- **Category:** Accessibility / Implementation integrity.
- **Source fact:** Buttons declare `role="tab"` and `aria-selected` in a tablist, but all remain ordinary tab stops; no arrow/Home/End handling, roving tab index, tab-panel linkage, or associated tabpanel is implemented. Route tabs use links and `aria-current`, which is appropriate to navigation.
- **Impact:** Keyboard and assistive-technology behavior differs from what the tab semantics promise. Buttons can still be reached and activated, so this is P2 rather than an asserted keyboard blocker.
- **Recommendation:** Use plain grouped filter buttons with `aria-pressed` for category filtering, or complete the tabs contract if these are genuinely tab panels. Like labeling a cupboard a filing cabinet, its controls should match the label's expected behavior.
- **Suggested command:** `$impeccable harden`.

### T10 — [P2] Some modal errors are rendered behind the modal

- **Location:** `frontend/components/organization/OrganizationAdminPage.tsx:142`, `:227`, `:269`; `frontend/components/admin/QuotaPlanPolicies.tsx:119`, `:146`, `:157`; `QuotaManagement.tsx:148`, `:175`.
- **Category:** Accessibility / Implementation integrity.
- **Source fact:** Organization create/edit failures update page-level `error`, whose alert is outside the native Dialog. Quota plan/change errors likewise render before their modal overlays. The organization's access-specific errors correctly render inside its access dialog at `OrganizationAdminPage.tsx:279`.
- **Impact:** Users may remain in an open modal without seeing its failure reason. Native modal background inertness makes page-level feedback particularly unsuitable. Actual alert announcement timing was not screen-reader-tested.
- **Recommendation:** Give each modal operation local error feedback near its controls, preserving input on failure. Like placing a service notice inside the waiting room rather than behind its locked door, feedback must be available where the user is working.
- **Suggested command:** `$impeccable harden`.

### T11 — [P2] Organization access loading can publish stale workspace members

- **Location:** `frontend/components/organization/OrganizationAdminPage.tsx:112`–`:124`, `:183`–`:188`, `:277`–`:301`.
- **Category:** Implementation integrity.
- **Source fact:** `refreshAccess(workspace)` unconditionally publishes the awaited result into shared `assignments`. Closing and opening another workspace does not cancel or sequence requests. A slower request for workspace A can overwrite B's assignments while B's title and mutation target remain active. In contrast, `WorkspaceSwitcher.tsx:96` checks a request ID and `WorkspaceMembersPage.tsx:99` checks response identity.
- **Impact:** The displayed members can disagree with the workspace being edited. This is a source-confirmed race opportunity; an out-of-order response was not induced against a backend.
- **Recommendation:** Apply the existing request-sequence and workspace-identity pattern, or key the access content by workspace. Like labeling trays before handing them to reception, results must be delivered to their original request.
- **Suggested command:** `$impeccable harden`.

### T12 — [P2] Hand-built create/share/quota dialogs lack viewport-height containment

- **Location:** `frontend/components/drive/browser/DriveCreateFolderDialog.tsx:31`; `DriveShareDialog.tsx:26`; `frontend/components/admin/QuotaManagement.tsx:175`; `QuotaPlanPolicies.tsx:147`, `:158`. Compare shared `frontend/components/ui/Dialog.tsx:49`.
- **Category:** Responsive design.
- **Source fact:** Fixed centered overlays have `p-4` but no scrollable overlay or max-height/overflow on their content. Shared Dialog already uses a viewport-dependent maximum height and `overflow-y-auto`; Move dialog also has explicit height containment.
- **Impact:** Short landscape viewports, software keyboards and enlarged text can push form controls beyond the visible overlay. This is a code-level risk; no claim of observed clipping at a specific viewport is made.
- **Recommendation:** Reuse the contained shared Dialog shell. Like fitting a long form onto a clipboard that can scroll, keep every control reachable when available space shrinks.
- **Suggested command:** `$impeccable adapt`.

### T13 — [P2] Touch-target improvements do not cover several custom controls

- **Location:** `frontend/components/drive/UploadManager.tsx:475`, `:484`, `:617`, `:696`; `frontend/components/layout/AuthForm.tsx:154`; `frontend/app/(auth)/admin-invite/page.tsx:44`; `frontend/components/drive/browser/DriveGrid.tsx:142`; custom scrollbar `DriveFileBrowser.tsx:920`; coarse-pointer rule `frontend/app/globals.css:201`.
- **Category:** Responsive design / Accessibility.
- **Source fact:** Upload controls are 32×32, password visibility is approximately 29×29 in AuthForm and an unpadded 18px icon in admin invitation, grid file drag is 20×24, and scrollbar width is 8px. These controls omit `ui-control`, so the 44px coarse-pointer rule does not increase them. Pause/Resume are unpadded small text buttons.
- **Impact:** Finger selection and motor accessibility are inconsistent. **44px is the audit's comfort target; a control below 44px is not automatically a WCAG AA violation.** AA's 24px target/spacing exceptions require rendered measurements. No touch gesture was synthesized.
- **Recommendation:** Extend the shared control hit-area rule to these controls, including a wider invisible scrollbar hit region. Preserve visual density while enlarging the target. Like giving a small drawer knob a larger grip area, the visible icon need not become large.
- **Suggested command:** `$impeccable adapt`.

### T14 — [P2] Marquee selection does unbounded layout work for every pointer event

- **Location:** `frontend/components/drive/browser/useDriveSelection.ts:147`–`:165`, `:206`; `DriveListTable.tsx:45`; `DriveGrid.tsx:39`, `:114`; data retrieval `frontend/lib/drive-service.ts:225`.
- **Category:** Performance.
- **Source fact:** Every pointermove queries all rendered items, reads each bounding rectangle, and sets React selection state. List and grid render all received items. No animation-frame coalescing or viewport windowing is present in these paths. This is repeated layout reading, **not evidence of a proven read/write layout-thrashing loop**.
- **Impact:** Work increases with folder size and pointer frequency; large directories may stutter. No frame drop or interaction duration was measured, so do not represent this as an observed slowdown.
- **Recommendation/trade-off:** First coalesce pointer updates per frame and cache bounds for a gesture, invalidating when scrolling/resizing. Profile realistic large folders before introducing virtualization, which adds complexity. Like checking every shelf on every hand movement, batch the inventory before reaching for a more complex warehouse system.
- **Suggested command:** `$impeccable optimize`.

### T15 — [P2] Saved dark preference is applied only after hydration

- **Location:** `frontend/components/theme/ThemeProvider.tsx:7`–`:15`; `frontend/app/layout.tsx:34`; default light colors `frontend/app/globals.css:3`.
- **Category:** Theming.
- **Source fact:** Server HTML has no theme attribute; the provider resolves local preference in a client effect. Therefore initial CSS uses the light root palette before the effect runs. Runtime duration and visible flash were not observed.
- **Impact:** Dark-mode users can receive a light initial paint, especially on slower startup.
- **Recommendation:** Resolve an explicit cookie preference on the server or apply a small, carefully scoped pre-paint preference initializer using the existing theme policy. Preserve system-preference listening. Like switching on the correct room lighting before guests enter, choose the palette before the first paint.
- **Suggested command:** `$impeccable harden`.

### T16 — [P3] Reduced motion globally collapses every animation and transition

- **Location:** `frontend/app/globals.css:158`–`:167`; compare intentional component handling at `DriveActionToolbar.tsx:38` and `:166`.
- **Category:** Accessibility / Implementation integrity.
- **Source fact:** A global 0.01ms animation/transition rule disables animated indicators and movement wholesale. Many busy states retain text/ARIA, so the source does **not** establish that essential status disappears everywhere.
- **Impact:** Motion preference handling lacks component-specific static alternatives; it can make a spinner look stopped while work continues. User impact was not rendered or tested with assistive technology.
- **Recommendation:** Keep purposeful static busy text/status and disable non-essential movement per component instead of relying solely on a global duration kill. Like replacing an animated road sign with a readable fixed sign, reduced motion should preserve the message.
- **Suggested command:** `$impeccable animate`.

## Coverage and positive findings

| Area | Source coverage / current evidence |
|---|---|
| Shared UI | Native Dialog/ConfirmDialog, buttons, icon buttons, input/select, tooltip, toast, progress, skeleton, table, breadcrumb and custom scroll. Named controls and common focus styling are established patterns. ContextMenu supports arrows/Home/End/Escape and uses a portal with viewport clamping. |
| Auth / invitations | Login and register share AuthForm, use labels/autocomplete, pending disabling and linked field errors. Registration gives explicit next steps. Admin and workspace invitation states are separate source flows; API success was not exercised. |
| Drive routes | My Drive/folder/recent/starred/trash/shared and workspace files/folders reuse DriveFileBrowser. Route folder IDs receive safe-integer validation. Shared-by-me is paginated and guards stale requests. |
| Drive interactions | List/grid, sorting, toolbar, marquee, custom scrollbar, folder creation, move, rename, share/revoke, preview and upload intake reviewed. Rename and preview already reuse native Dialog. List uses container-query column compaction (`DriveListTable.module.css:11`, `:26`) instead of forcing all columns onto mobile. |
| Preview | `FilePreviewDialog.tsx:34`–`:41` checks MIME and size before loading, cancels/revokes object URLs at `:61`, uses escaped text in pre and a named image. The authenticated blob image is not a generic remote-image optimization defect; adding next/image/lazy loading is not automatically beneficial here. |
| Upload | Root manager preserves tasks across client routes. Scheduler bounds active uploads to three (`UploadManager.tsx:58`, `:383`), supports cancellation and conditional pause/resume, warns before unload, and uses progress/error states. Hashing caches by File with weak keys (`upload-file-hash.ts:6`); no worker claim is made. |
| Account | Settings/profile/security/privacy/history/theme/data deletion reviewed. Delete requires current password, an exact confirmation phrase and another confirmation (`AccountSettingsContent.tsx:166`–`:180`). Profile/password error-to-field linkage should be made consistent with AuthForm; this is secondary to the listed priorities. |
| Workspaces | Switcher uses native popover, sequenced requests, native create/join dialogs. Member changes have confirmation and protected self/admin policy. Activity distinguishes lack of events from load failure. Several plain loading messages could reuse LoadingState for announcements. |
| Organization | Real tenant permission gating, workspace editing/archive and per-member access flows. Reuses DataTable/Dialog/ConfirmDialog. State ownership/error location defects are called out above. |
| Platform admin | Dashboard, user/session/file/workspace/organization directories, activity/audit logs, permissions, settings, quota policies, infrastructure/topology and backup routes reviewed. Live directories have pagination, abort/stale-response handling and explicit request failures. Shared directory CSS and container filters are coherent. |
| Unavailable operations | Backup actions are disabled and labeled unavailable; monitoring/topology/security alerts say unconnected or Unknown. These are honest capability boundaries, not fabricated operational metrics. Backup history filters update only local state and have no data connection; lower emphasis/disable them until a service exists. |

## Systemic patterns and recommended order

The source has the correct reusable answers in several places, but coverage is incomplete. Native dialogs coexist with manual overlays, semantic status colors coexist with fixed light surfaces, and robust request sequencing in workspace switching coexists with unguarded organization access loading. Consolidation is the smallest durable change; an additional UI framework or a wholesale redesign is not indicated by this audit.

1. **P1 `$impeccable harden`** — one modal/focus contract; keyboard selection and grid event isolation; scrollbar focus.
2. **P1 `$impeccable colorize`** — pair every status/background and accent/on-accent color, verify current light and dark variants.
3. **P2 `$impeccable harden`** — raw timestamp sort, local modal failures, organization request ownership and category semantics.
4. **P2 `$impeccable adapt`** — modal height/zoom, touch hit areas and keyboard-visible scrolling across narrow screens.
5. **P2 `$impeccable optimize`** — profile large folders; coalesce marquee work only to the extent current data requires.
6. **P3 `$impeccable animate`** — intentional reduced-motion states.
7. **`$impeccable polish`** — final rendered verification after behavior and theme fixes.

Repeat the audit after fixes. The next verification should exercise list and grid with a keyboard, each modal with Escape/Tab/Shift+Tab, short/mobile/zoomed viewports, both themes, slow/error requests, and an out-of-order organization access response. Browser measurements must replace source-only layout and performance risks before claiming they are resolved.

This audit workflow is reusable: inventory surfaces, isolate design judgment, scan once, trace shared contracts, calculate source color pairs, reproduce deterministic formatting defects, and clearly separate rendered evidence from source inference. After fixes and a successful browser pass, consider packaging that workflow as a project Agent Skill.

## Source inventory

Inventory excludes tests and binary assets. It records requested scope, including helper modules supporting UI behavior; it does not imply browser execution of every route/state.

```text
frontend/app\(admin)\admin\activity\page.tsx
frontend/app\(admin)\admin\audit\page.tsx
frontend/app\(admin)\admin\backups\history\page.tsx
frontend/app\(admin)\admin\backups\jobs\page.tsx
frontend/app\(admin)\admin\backups\page.tsx
frontend/app\(admin)\admin\backups\policies\page.tsx
frontend/app\(admin)\admin\backups\restore\page.tsx
frontend/app\(admin)\admin\files\page.tsx
frontend/app\(admin)\admin\infrastructure\[section]\page.tsx
frontend/app\(admin)\admin\infrastructure\page.tsx
frontend/app\(admin)\admin\infrastructure\quotas\[section]\page.tsx
frontend/app\(admin)\admin\infrastructure\quotas\page.tsx
frontend/app\(admin)\admin\infrastructure\topology\page.tsx
frontend/app\(admin)\admin\layout.tsx
frontend/app\(admin)\admin\organizations\page.tsx
frontend/app\(admin)\admin\page.tsx
frontend/app\(admin)\admin\permissions\page.tsx
frontend/app\(admin)\admin\security\alerts\page.tsx
frontend/app\(admin)\admin\settings\page.tsx
frontend/app\(admin)\admin\users\audit\page.tsx
frontend/app\(admin)\admin\users\page.tsx
frontend/app\(admin)\admin\workspaces\page.tsx
frontend/app\(auth)\admin-invite\page.tsx
frontend/app\(auth)\login\page.tsx
frontend/app\(auth)\register\page.tsx
frontend/app\account\profile\page.tsx
frontend/app\account\settings\page.tsx
frontend/app\account\support\page.tsx
frontend/app\account\upgrade\page.tsx
frontend/app\drive\folders\[folderId]\page.tsx
frontend/app\drive\page.tsx
frontend/app\drive\recent\page.tsx
frontend/app\drive\shared\page.tsx
frontend/app\drive\shared-by-me\page.tsx
frontend/app\drive\starred\page.tsx
frontend/app\drive\trash\page.tsx
frontend/app\drive\workspaces\[workspaceId]\[...path]\page.tsx
frontend/app\drive\workspaces\[workspaceId]\activity\page.tsx
frontend/app\drive\workspaces\[workspaceId]\members\page.tsx
frontend/app\drive\workspaces\[workspaceId]\page.tsx
frontend/app\globals.css
frontend/app\layout.tsx
frontend/app\organization\admin\page.tsx
frontend/app\page.tsx
frontend/app\workspace-invite\page.tsx
frontend/components\account\AccountPageLayout.tsx
frontend/components\account\AccountProfilePanel.tsx
frontend/components\account\AccountProvider.tsx
frontend/components\account\AccountSecurityPanel.tsx
frontend/components\account\AccountSettings.module.css
frontend/components\account\AccountSettingsContent.tsx
frontend/components\admin\AdminDirectory.module.css
frontend/components\admin\AdminFileDirectory.module.css
frontend/components\admin\AdminFileDirectory.tsx
frontend/components\admin\AdminLogDirectory.module.css
frontend/components\admin\AdminLogDirectory.tsx
frontend/components\admin\AdminPageHeader.tsx
frontend/components\admin\AdminResourceDirectory.tsx
frontend/components\admin\AdminSegmentTabs.tsx
frontend/components\admin\AdminWorkspaceDirectory.tsx
frontend/components\admin\InfrastructureDetail.tsx
frontend/components\admin\PlatformDashboard.tsx
frontend/components\admin\QuotaManagement.module.css
frontend/components\admin\QuotaManagement.tsx
frontend/components\admin\QuotaPlanPolicies.tsx
frontend/components\admin\UserDirectory.tsx
frontend/components\admin\UserSessionsDialog.tsx
frontend/components\drive\browser\DriveActionToolbar.tsx
frontend/components\drive\browser\DriveCreateFolderDialog.tsx
frontend/components\drive\browser\drive-display-utils.ts
frontend/components\drive\browser\DriveGrid.tsx
frontend/components\drive\browser\drive-item-actions-utils.ts
frontend/components\drive\browser\DriveItemIcon.tsx
frontend/components\drive\browser\DriveListTable.module.css
frontend/components\drive\browser\DriveListTable.tsx
frontend/components\drive\browser\DriveMoveDialog.tsx
frontend/components\drive\browser\drive-move-utils.ts
frontend/components\drive\browser\drive-selection-utils.ts
frontend/components\drive\browser\DriveShareDialog.tsx
frontend/components\drive\browser\drive-upload-utils.ts
frontend/components\drive\browser\recent-timeline.ts
frontend/components\drive\browser\RecentTimeline.tsx
frontend/components\drive\browser\types.ts
frontend/components\drive\browser\useDriveFileOperations.ts
frontend/components\drive\browser\useDriveItemActions.ts
frontend/components\drive\browser\useDriveItems.ts
frontend/components\drive\browser\useDriveSelection.ts
frontend/components\drive\browser\useDriveUploadIntake.ts
frontend/components\drive\DriveFileBrowser.tsx
frontend/components\drive\DriveNewMenu.tsx
frontend/components\drive\FilePreviewDialog.tsx
frontend/components\drive\GlobalDriveActions.tsx
frontend/components\drive\RenameDialog.tsx
frontend/components\drive\ShareManagementDialog.tsx
frontend/components\drive\upload-file-hash.ts
frontend/components\drive\upload-hash-core.ts
frontend/components\drive\UploadManager.tsx
frontend/components\drive\upload-manager-model.ts
frontend/components\drive\upload-part-authorization.ts
frontend/components\drive\upload-progress-model.ts
frontend/components\drive\upload-progress-telemetry.ts
frontend/components\drive\upload-resume-model.ts
frontend/components\drive\upload-service.ts
frontend/components\drive\upload-transfer-control.ts
frontend/components\layout\AdminBreadcrumb.tsx
frontend/components\layout\AdminConsole.tsx
frontend/components\layout\AuthForm.tsx
frontend/components\layout\DashboardShell.tsx
frontend/components\layout\DriveFolderNavigation.tsx
frontend/components\layout\Header.tsx
frontend/components\layout\SettingsSidebar.tsx
frontend/components\layout\Sidebar.tsx
frontend/components\layout\useNavigationDrawer.ts
frontend/components\layout\WorkspaceSidebar.tsx
frontend/components\organization\OrganizationAdminPage.tsx
frontend/components\shared\EmptyState.tsx
frontend/components\shared\ErrorState.tsx
frontend/components\shared\LoadingState.tsx
frontend/components\theme\ThemeProvider.tsx
frontend/components\ui\Badge.tsx
frontend/components\ui\BrandLogo.tsx
frontend/components\ui\Breadcrumb.tsx
frontend/components\ui\Button.tsx
frontend/components\ui\ConfirmDialog.tsx
frontend/components\ui\ContextMenu.tsx
frontend/components\ui\CustomScrollArea.tsx
frontend/components\ui\DataTable.tsx
frontend/components\ui\Dialog.tsx
frontend/components\ui\Dropdown.tsx
frontend/components\ui\IconButton.tsx
frontend/components\ui\Input.tsx
frontend/components\ui\Progress.tsx
frontend/components\ui\Skeleton.tsx
frontend/components\ui\Toast.tsx
frontend/components\ui\Tooltip.tsx
frontend/components\workspaces\useActiveWorkspaceId.ts
frontend/components\workspaces\WorkspaceActivityPage.tsx
frontend/components\workspaces\WorkspaceInviteAcceptance.tsx
frontend/components\workspaces\WorkspaceMembersPage.tsx
frontend/components\workspaces\WorkspaceSwitcher.tsx
```
