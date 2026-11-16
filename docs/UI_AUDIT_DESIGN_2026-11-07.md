# BlueDrive frontend design assessment A — 2026-11-07

Independent source-only design review of `frontend/`, in Operate mode. This is Assessment A, isolated from detector output and from Assessment B. No detector was run or read. No application page was rendered or interacted with by this reviewer. No source code was changed. The parent handles context setup and any browser evidence separately.

## Evidence and limits

Mapped all 42 `app/**/page.tsx` entry points and reviewed their user-facing component families, both app layouts, global CSS, shared controls, component styles, and the supporting request/route/selection/action logic necessary to follow the primary flows. This is interface coverage, not a claim that every helper or backend implementation was exhaustively audited. `docs/UI_REFINEMENT.md` was read for scope and product intent, not accepted as proof that its validations or rendered outcomes still hold. No PRODUCT.md or DESIGN.md was available in the project context reported by the parent. No project-specific audience persona has been invented.

Findings below distinguish source-proven behavior from rendered questions. Source inspection establishes handlers, labels, state transitions, ARIA declarations, route mapping, and token values. It cannot establish actual clipping, spacing, rendered font sizes, real API responses, pointer behavior on a particular phone, screen-reader announcements, browser focus behavior, or all theme contrast combinations. Scores are provisional source-based judgments, not a release certification. Calculated color ratios below use declared CSS color pairs, not sampled screenshots.

The key problem is uneven completion of otherwise sensible shared patterns: some high-stakes operations use the native dialog and clear recovery states, while others lose access to progress, hide errors behind overlays, or require different input methods. Recommendation: finish those shared interaction contracts before another visual redesign. Like a building with clear room signs but several doors using different handles, familiarity helps only until the user reaches the inconsistent door.

## Complete route coverage

All entries below received source review. “Shared” means the route is a thin wrapper and the corresponding implementation was reviewed once in depth, with its route-specific parameters and view restrictions checked. None received rendered verification in Assessment A.

| Route | Implementation / reviewed coverage |
|---|---|
| `/` | Redirect to `/login`. |
| `/login` | AuthForm login, fields, submit, failure, redirect, recovery copy. |
| `/register` | AuthForm registration, field errors, acceptance state, sign-in return. |
| `/admin-invite` | Administrator password activation, missing token, pending/error/success. |
| `/workspace-invite` | Preview, missing/expired/error, sign-in continuation, acceptance, completion. |
| `/account/profile` | Temporary redirect to combined Profile & Security. |
| `/account/settings` | General, Profile & Security, Privacy, Connected Apps; query selects initial security/general. |
| `/account/support` | Configured support link or unavailable/configuration copy. |
| `/account/upgrade` | Account eligibility branches, submission and failure. |
| `/drive` | Shared DriveFileBrowser, personal root, New/upload/search/list/grid/action states. |
| `/drive/folders/[folderId]` | Positive safe-ID validation; same browser, folder details, breadcrumbs. |
| `/drive/recent` | Shared browser plus 14-day RecentTimeline and 100-item qualification. |
| `/drive/starred` | Shared browser, unstar action and empty state. |
| `/drive/trash` | Shared browser, restore and permanent deletion confirmations. |
| `/drive/shared` | Shared browser, incoming shares, owner-dependent actions, outgoing-share entry. |
| `/drive/shared-by-me` | Paginated direct grants and ShareManagementDialog. |
| `/drive/workspaces/[workspaceId]` | Redirect to explicit workspace files route. |
| `/drive/workspaces/[workspaceId]/[...path]` | Allowed `files`, `recent`, `starred`, `trash`, and `folders/[folderId]`; invalid path calls notFound. Same browser with scoped URLs. |
| `/drive/workspaces/[workspaceId]/members` | Invite creation/copy, member roles/removal, protection labels, confirmation, pagination. |
| `/drive/workspaces/[workspaceId]/activity` | Manager timeline, loading/error/empty, refresh and return. |
| `/organization/admin` | Workspaces/members, create/edit/archive/restore and access-management dialog. |
| `/admin` | Live overview request, counts, service limitations, directory links, loading/error. |
| `/admin/users` | Users/admins segments, search/status/sort, suspension/reactivation, admin invitation/reinvitation/disable, sessions. |
| `/admin/users/audit` | Redirect to `/admin/audit`. |
| `/admin/organizations` | Search, newest-first directory, pagination, loading/error/empty. |
| `/admin/workspaces` | Ownership/search/sort, read-only role/member counts, pagination and limitations. |
| `/admin/files` | Scope/status/search/sort, metadata details, trash/restore/purge reasons and confirmation. |
| `/admin/permissions` | Role groups, live counts, capabilities, boundaries and links; route discoverability checked. |
| `/admin/activity` | Shared AdminLogDirectory activity filters, table, event details, paging. |
| `/admin/audit` | Shared AdminLogDirectory audit filters, table, reasons, details, paging. |
| `/admin/security/alerts` | Explicit disconnected detection-pipeline state. |
| `/admin/settings` | Console name/reason/revision, save/discard/refresh and read-only effective operations. |
| `/admin/infrastructure` | API/database observation and unmonitored storage limitations. |
| `/admin/infrastructure/topology` | Explicit disconnected telemetry guidance. |
| `/admin/infrastructure/[section]` | Servers/storage/database/minio/alerts placeholder health checks; unknown section fallback. |
| `/admin/infrastructure/quotas` | QuotaManagement defaults to personal directory. |
| `/admin/infrastructure/quotas/[section]` | Validated users/workspaces/policies/capacity; directory, management overlay, plans/policies and audit. |
| `/admin/backups` | Unknown backup metrics/source status and jobs/history/restore links. |
| `/admin/backups/jobs` | Disabled execution, unavailable notice, unknown rows. |
| `/admin/backups/history` | Local-only filters/search, disconnected empty table. |
| `/admin/backups/policies` | Disabled policy fields/actions and unavailable notice. |
| `/admin/backups/restore` | Local mode/scope/conflict/confirmation changes; disabled restore execution. |

Legacy `/admin/teams` and `/admin/infrastructure/quotas/teams` redirects were reviewed in `frontend/next.config.ts:6`. They preserve access to renamed workspace views. Query variants such as settings sections and Drive `q` are covered above; this inventory counts source entry points, not every possible parameter combination.

## Shared system and primary-flow coverage

The shell uses one 256px desktop navigation width, a shared drawer hook, header search and workspace switcher. Personal/workspace navigation reuses DriveFolderNavigation; settings replaces the sidebar navigation while retaining New and the workspace header. AdminConsole has its own role-gated shell, grouped navigation and theme control. Shared tokens establish foreground/surface/muted/brand/status colors, Poppins, control radius, motion timing, reduced-motion behavior and focus styling.

Reviewed Button, Input, IconButton, Badge, BrandLogo, Breadcrumb, ContextMenu, Dropdown, Dialog, ConfirmDialog, Toast, Tooltip, Progress, Skeleton, CustomScrollArea and DataTable, plus the shared Empty/Error/Loading states. Reviewed the admin page header/segment components, all three directory style modules, account container-responsive settings styles and Drive table container rules. Some primitives are not consistently used by the corresponding app surfaces.

| Flow | Source strengths and gaps |
|---|---|
| Sign in / registration / activation | Labeled fields, autocomplete, disabled pending submit, inline auth errors and safe internal redirects. No password-recovery implementation; displayed recovery statement has no support action. Admin activation does not explain its 12-character minimum in the visible instruction. |
| Select/create/join workspace | My Drive stays visible in the popover; create/join each has a focused form and cancel; explicit workspace URLs preserve scope. Creation explains role permissions and email-bound invitations. Long workspace lists have no search. |
| Browse/search/open/select files | Search is scoped and named; breadcrumbs, list/grid toggle and sort expose location/control. List selection is pointer-only; grid keyboard handling also responds to descendant buttons. |
| Upload and recover transfer | Queue, bounded concurrent work, bytes/ETA, backend-confirmed completion, pause/resume/retry/cancel and unload warning are present. Closing the tray dismisses all tracked tasks from every future visible view. |
| Create/rename/move/share/delete | Native dialogs are used for global New, rename, preview, single-item access and confirmations. Move and bulk share use custom overlays with a weaker keyboard contract. Permanent delete has explicit irreversible copy. Sidebar New intentionally targets the selected root, with that destination explained in the menu. |
| Workspace membership | Roles, protected organization assignments, self protections, confirmed changes/removals and manual invitation delivery are explicit. The organization access editor uses a different immediate-change/remove contract. |
| Account management | Profile/current-password and password-change consequences are explained. Appearance and language controls are honest; English-only is stated. Privacy independently fetches activity/search but still displays successful-empty text after endpoint failures. |
| Admin management | Role-sensitive actions, reasons, sessions, purge filename confirmation and read-only metadata boundaries are strong. Quota overlays bypass shared Dialog and place some mutation errors outside the overlay. |
| Operational review | Distinguishes unavailable telemetry from healthy status; no invented live disks/backups/alerts. Several deep routes have no visible navigation entry; log details require double-click for pointers. |

## Verified findings

Severity follows the critique guide: P0 blocks task completion entirely, P1 causes significant difficulty/confusion, P2 has a workable alternative, P3 is polish. No P0 was established. Missing planned backend capabilities are not proposed as new implementation scope; findings about them concern truthful presentation and recovery in the existing interface.

### A01 — P1: Hiding uploads removes the way back to active transfers

`frontend/components/drive/UploadManager.tsx:333` adds every current task ID to `dismissedTaskIds` and sets `visible=false`. At `:424` the task list excludes all those IDs; `:460` renders both the tray and its supposed reopening button only when that filtered list is nonempty. Consequently closing a tray containing active uploads leaves no reopen button, although the uploads continue. `openManager` at `:417` does not clear dismissal, and enqueue only undismisses new task IDs (`:150`). Existing progress, failure details, pause and stop controls become inaccessible through this UI. Preserve active tasks and expose a persistent collapsed entry; dismiss completed history separately. This is like closing a parcel-tracking window and losing the tracking number while delivery is still underway.

### A02 — P1: Default list view has no keyboard selection path

`frontend/components/drive/browser/DriveListTable.tsx:129` binds selection to a nonfocusable table row's `onClick`, with open on double-click. The name at `:157` is a span; there is no row key handler or selection checkbox. `useDriveSelection.ts:57` adds only Escape, not keyboard selection. Context-menu Open remains a keyboard workaround for opening one item, and grid has Space selection, but list users cannot keyboard-select rows for the bulk toolbar. Add the same accessible selection control/keyboard contract to both views. Like a filing cabinet whose labels are readable but whose drawer handles can only be pulled with a mouse, the visible information is not sufficient access.

### A03 — P1: Grid keyboard commands fire when a child control is used

`frontend/components/drive/browser/DriveGrid.tsx:52` and `:125` run Enter/Open and Space/selection on the article for every bubbled keydown, without checking `event.target === event.currentTarget`. Cards contain drag buttons, star buttons and ContextMenu triggers. Enter on a star/menu trigger therefore also invokes `onOpen`; Space is prevented and toggles the parent selection. Pointer propagation guards at `:84` and `:158` do not guard keydown. Restrict card commands to the card itself or move open/select to separate native controls. It is like pressing a light switch and also opening the room door because both share the same wire.

### A04 — P1: Several high-stakes overlays bypass the shared dialog's keyboard behavior

`frontend/components/drive/browser/DriveMoveDialog.tsx:29`, `DriveShareDialog.tsx:25`, `frontend/components/admin/QuotaManagement.tsx:175`, and `QuotaPlanPolicies.tsx:146`/`:157` render ordinary fixed elements. They do not implement Escape dismissal, focus containment/restoration, or background inertness. Bulk share also lacks `role=dialog`/`aria-modal` on its form. Declaring `aria-modal` on the other custom sections does not implement modality. Contrast the existing native `Dialog.tsx:31` and `:42`, which call showModal and handle cancel. Reuse that component, with appropriate pending-close guards. This is the same door-handle problem across several rooms: one trained interaction should work everywhere. The browser must confirm actual focus behavior after migration.

### A05 — P1: Dark theme declares very low-contrast notification text

`frontend/components/ui/Toast.tsx:13` pairs fixed green/amber/rose-50 backgrounds with semantic success/warning/danger text. Dark theme in `frontend/app/globals.css:42` sets those foregrounds to bright light colors while the backgrounds remain pale. Calculated declared-pair ratios: warning `#facc15` on amber-50 `#fffbeb` = **1.48:1**; success `#4ade80` on green-50 `#f0fdf4` = **1.66:1**; danger `#fb7185` on rose-50 `#fff1f2` = **2.45:1**. This affects error/recovery information at normal small text sizes. Badge uses the same pattern (`Badge.tsx:12`); account status panels also mix semantic bright text with pale fixed backgrounds. Introduce status-surface tokens or use a fixed dark foreground appropriate to the pale background. Like printing a warning in yellow ink on cream paper, the message exists but becomes difficult to read. These are source color calculations, not a full contrast audit.

### A06 — P1: Some quota/plan save failures are behind the modal

`frontend/components/admin/QuotaManagement.tsx:139` stores request failure in `error`, which is rendered at `:148` before the fixed overlay at `:175`; no error is rendered inside the quota form. The editor remains open after failure. Similarly `QuotaPlanPolicies.tsx:80` renders errors at `:119`, outside the edit overlay at `:157`; delete has its own inline error at `:150`, proving the inconsistency. Display the mutation failure beside the active form while preserving input. This is like a cashier reporting a rejected payment on a screen behind the customer.

### A07 — P2: Eligible users are offered an upgrade action guaranteed to fail

`frontend/app/account/upgrade/page.tsx:55` presents “Continue to upgrade” for eligible individual accounts, but `frontend/lib/account-service.ts:145` always throws “Personal plan upgrades are not connected.” The destination title also leads with backend records rather than a user's plan decision. State the unavailable capability before the action and use an existing configured support channel if appropriate; no billing implementation is requested. Like a shop displaying an open checkout lane whose till is disconnected, eligibility is not the same thing as an available transaction.

### A08 — P2: Help exists as a route but cannot be discovered from the main UI

`frontend/app/account/support/page.tsx:7` implements support, but `frontend/components/layout/Header.tsx:71` offers only Settings/Sign out, the personal sidebar at `Sidebar.tsx:64` has five Drive entries, and settings sections at `SettingsSidebar.tsx:12` contain no help. A source-wide route-reference search found no UI link to `/account/support`. Login says password recovery is unavailable (`AuthForm.tsx:175`) without pointing to support. Add a consistent support entry and recovery next step. A help desk behind an unmarked door is of little use to someone already stuck.

### A09 — P2: Shared-link acceptance has no registration continuation

`frontend/components/workspaces/WorkspaceInviteAcceptance.tsx:97` sends signed-out invitees to login with a `next` URL. `frontend/components/layout/AuthForm.tsx:192` links from login to bare `/register`, dropping that invitation context; registration returns a general message and its sign-in link is bare `/login`. New invitees must recover/reopen the original link. Keep the same safe continuation through registration and back to login. This is like requiring a new visitor to leave the reception queue to obtain a badge, then discarding the room number they were visiting.

### A10 — P2: Privacy load errors also present successful-empty messages

`frontend/components/account/AccountSettingsContent.tsx:103`/`:110` independently record endpoint failures, but activity at `:275` and search at `:316` use only loading/array length to choose “No activity recorded yet” or “No search history yet.” An initial failure leaves empty arrays and displays both the error and the empty claim. Preserve independent panels, but gate each empty message on that panel's successful response. It is like a librarian saying “there are no books” when the catalog computer is offline.

### A11 — P2: From/To activity labels do not match one-bound filtering

`frontend/components/account/AccountSettingsContent.tsx:64` treats a lone From or To as equality to that exact day, despite conventional boundary labels at `:263`/`:267`. Selecting From November 1 hides November 2 onward rather than showing that period. Either implement open-ended boundaries or label the control as a single-day selector and explain the mode. The admin log date controls already use normal From/To constraints (`AdminLogDirectory.tsx:273`). This is like a shop sign reading “open from Monday” when it means “open Monday only.”

### A12 — P2: Pointer access to admin event details requires undisclosed double-click

`frontend/components/admin/AdminLogDirectory.tsx:317` opens details only on double-click or Enter/Space. The cue is a title attribute and an ARIA label, not a visible details action. Pointer users who click a row once receive no outcome; touch users cannot rely on title hover. Account activity uses a native single-click button (`AccountSettingsContent.tsx:276`). Use a visible single-action details button/link in both log modes. It is like a door that opens only when knocked twice with the instruction written on its back.

### A13 — P2: Settings navigation does not persist its location

`frontend/components/account/AccountSettingsContent.tsx:47` stores selection only in local state; the sidebar callback at `:205` changes state without updating the URL. `frontend/app/account/settings/page.tsx:7` reconstructs only security versus general from query. Refreshing Privacy/Connected Apps returns General, and browser Back does not traverse sections. Store the supported section in the URL using the existing server selection pattern. Like sticky-note room directions, the location disappears when the page is reopened.

### A14 — P2: Organization membership controls differ from workspace membership safeguards

`frontend/components/organization/OrganizationAdminPage.tsx:297` changes roles immediately, and `:301` removes members immediately. The workspace Members page confirms both (`WorkspaceMembersPage.tsx:135`/`:160`) and explains protected assignments. The organization editor also keeps error/notice for workspace create/edit outside that active dialog (`OrganizationAdminPage.tsx:142`/`:227`/`:269`). Reuse confirmed role/removal patterns and local form feedback where consequences match; keep backend authorization unchanged. This is like two offices using the same access badge but one revoking it on a single accidental tap.

### A15 — P2: Read-only quota errors can leave stale records looking current

`frontend/components/admin/QuotaManagement.tsx:91` sets the error but does not clear directory data. At `:156`, once loading ends, the table is rendered regardless of `error`. A failed search/sort/page request can leave old records beneath the new filter or page label, without saying they are stale. Other directories gate table rendering on `!error`, for example `AdminWorkspaceDirectory.tsx:73`. Hide stale results or explicitly label the retained snapshot with its previous scope. This is like a timetable switching to tomorrow's heading while retaining yesterday's departures.

### A16 — P2: Deep operational routes have navigation dead ends and ambiguous fallback

AdminConsole's groups (`frontend/components/layout/AdminConsole.tsx:18`) expose no Roles & Permissions or Backups entry; no other source UI links to `/admin/permissions` or `/admin/backups`. Backup overview links jobs/history/restore at `frontend/app/(admin)/admin/backups/page.tsx:50`, but not policies; these subpages offer no shared local section navigation or return link. Separately `InfrastructureDetail.tsx:27` silently shows Servers for an unrecognized `[section]` URL instead of notFound. Make intended live routes discoverable, give deep pages a consistent way back, and reject unknown sections. Like a floor plan with unlabeled corridors, direct URLs are useful only to people who already know them. Hiding unavailable roadmap features may be intentional; the appropriate fix can be explicit route retirement rather than adding them to navigation.

### A17 — P2: Small custom controls escape the shared touch-size policy

`frontend/components/drive/UploadManager.tsx:475`, `:484`, and `:617` declare 32px square transfer controls without `ui-control`; the coarse-pointer rule in `frontend/app/globals.css:227` targets `ui-control`, drive-toolbar controls and admin controls, so these transfer buttons remain 32px. `Dialog.tsx:57` uses 18px icon plus 8px padding on each side (34px), also outside that rule. The admin-invite show-password button at `frontend/app/(auth)/admin-invite/page.tsx:44` has only its 18px icon as declared size. Use IconButton/shared minimum targets. This is like making the emergency stop smaller than ordinary switches. Actual hit boxes and spacing still require device inspection.

### A18 — P2: Product-facing fallback copy exposes implementation instructions

`frontend/app/account/support/page.tsx:31` asks the account user to configure `NEXT_PUBLIC_SUPPORT_URL` or connect an endpoint. `AccountProfilePanel.tsx:83` discusses classification “by the backend”; upgrade has several backend-authority explanations; `DriveShareDialog.tsx:29`/`:52` calls the product SecureDrive while the shell and login say BlueDrive. Admin technical details are often appropriate, but end-user recovery should name the next person/action in familiar language and use one product name. Like a lift telling passengers to repair its control board, configuration facts do not supply an actionable next step.

### A19 — P3: Secondary tab semantics stop at labels

`frontend/components/admin/AdminSegmentTabs.tsx:19` declares tablist/tab/aria-selected for local segments, but offers no arrow-key movement, roving tabindex, aria-controls or corresponding tabpanel relationship. Native buttons remain reachable by Tab, so this is not a blocked flow. Complete the tabs pattern or use ordinary grouped pressed buttons consistently. Like marking a lane as an escalator while providing stairs, the announced convention promises a behavior the control does not implement.

## Holistic judgment and specificity

**Specificity verdict: coherent and moderately product-grounded, with generic scaffolding around the strongest domain interactions.** Personal versus shared workspace scope, creator/role labels, inherited-versus-direct access explanations, metadata-only platform administration, quota reservation and backend-confirmed upload completion are distinctive to a secure collaboration drive. These should be preserved. The visual vocabulary—cloud mark, blue-violet accent, rounded bordered cards, avatar circles, standard sidebar—is conventional and transferable to many SaaS tools. In Operate mode that is acceptable when it reduces learning effort. Source alone does not justify calling the composition bland, crowded, elegant, or visually complete.

Hierarchy is structurally sensible: one main admin title, titled sections, dominant New, breadcrumbs and contextual action toolbar. Navigation duplication is substantially reduced. The weaker areas are completion and discoverability, especially in deep routes and recovery. Typography uses a single family and restrained size scale, but tables/metadata include 10–12px copy and must be inspected at 200% zoom. Long strings are handled deliberately in many directories using truncation/title or wrapping; organization tables and modal headers need rendered stress checks. Theme tokens exist, yet hardcoded pale status surfaces and some blue controls fragment the intended system.

## Nielsen scores (source-only, provisional)

All ten apply to this task-oriented web application. Scores use 0–4, where 4 requires excellent coverage; no heuristic is n/a.

| Heuristic | Score | Evidence and limitation |
|---|---:|---|
| 1. Visibility of system status | 2 | Rich transfer state and request states, but tray dismissal hides ongoing work; some loading states use plain EmptyState without live status; no live timing verified. |
| 2. Match with real world | 2 | Familiar Drive/folder/Trash terms and concrete access descriptions; From/To semantics, backend jargon, brand naming and upgrade promise diverge. |
| 3. User control and freedom | 2 | Cancel, native dialogs, Trash restore and clear search exist; custom modal keyboard exits and upload recovery are incomplete. |
| 4. Consistency and standards | 2 | Strong tokens, shared shell/tree/buttons/directories; competing dialog/role-change/log activation patterns remain. No rendered visual-consistency claim. |
| 5. Error prevention | 3 | Destructive confirmation, current-password checks, role protections, explicit purge filename/reason and guarded upload completion; organization membership differs and pending behavior needs runtime checks. |
| 6. Recognition rather than recall | 2 | Location, roles and visible menus help; no discovered support link, hidden deep routes, icon-heavy bulk actions, invitation continuation loss and closed transfer history add recall. |
| 7. Flexibility and efficiency | 2 | Bulk selection, drag/drop/paste, list/grid, sorting, download and transfer controls exist; default list has no keyboard selection and repeated card actions multiply tab stops. |
| 8. Aesthetic and minimalist design | 3 | Source establishes restrained tokens and progressive disclosure, grouped navigation and no fabricated telemetry. Actual visual balance/contrast/spacing cannot be scored confidently without rendered pages; icon toolbar density is a concern. |
| 9. Recognize/diagnose/recover errors | 2 | Errors generally preserve inputs and offer retry; modal errors can sit outside the task, false-empty privacy text and stale quotas conflict with recovery. |
| 10. Help and documentation | 1 | Useful inline access/transfer/telemetry notes and a support route exist, but no visible support entry or task-help system was found. |
| **Total** | **21/40 (52.5%)** | **Acceptable band under the scoring guide; significant targeted improvements required. Source-only, not a rendered usability grade.** |

## Cognitive load

Checklist results from source:

- **Grouping/progressive disclosure: partial pass.** Admin has four expandable groups (Management has four child routes, Security three, Infrastructure three, System one). Workspace creation and joining are separated. Personal navigation has five visible top-level destinations; manager workspace navigation has six, plus My Drive return. Those are 5–7-choice decision points, not evidence by themselves that users are overwhelmed.
- **Action decision points above four: fail in selected-file toolbar.** Clear selection, Open, Download, Rename, Move, Duplicate, Star, Share and Trash can appear together (`DriveActionToolbar.tsx:45`). That is nine mostly icon-only controls. Single-item context menus can similarly exceed seven options (`DriveFileBrowser.tsx:599`). Keep frequent actions visible and group the rest; preserve accessible labels.
- **Memory bridges: fail.** Invitation registration loses continuation; closing transfers loses the previous tasks; hidden support/deep routes require remembered URLs.
- **Current location: partial pass.** Explicit workspace URLs, breadcrumbs and aria-current are strong; settings local tabs and unknown infrastructure fallback weaken location reliability.
- **Plain language: partial fail.** Main file terminology is familiar, but backend, tenant and service configuration appear in end-user messages. Role scope is explained in some places and assumed in others.
- **Focused sequence: mostly pass.** Share and create are short forms, permanent deletion is separated and explained. Restore's unavailable page still offers many local choices (four modes, optional four scopes, three conflict choices and acknowledgment) before an action that cannot run; simplify the disconnected state instead of inviting futile setup work.
- **Consistent patterns: fail.** Same member role/removal task has confirmed versus immediate behavior; same event-details task has single-click versus double-click; same form task has native versus custom modal behavior.
- **Visual noise: unverified.** Source count of controls is evidence; perceived visual density, first-screen hierarchy and table scanability must be judged from actual layouts.

## Emotional journey

Entry is calm and direct, with clear identity and one primary authentication action. The first personal Drive empty state (“No files here” plus a generic location explanation at `DriveFileBrowser.tsx:834`) is a mild valley: it does not directly tell a first-time user to use New or drop a file, though New remains available. Shared access forms provide appropriate reassurance about email-bound invites and other sources of access. Destructive data removal carefully separates personal Drive from shared workspaces.

The transfer peak has good quantitative progress, verified completion and controlled retry. Its ending is undermined by hiding an unfinished tray and losing the route back. Upgrade and unavailable service pages create another valley by asking the user to consider actions they cannot complete. Admin metadata boundaries and explicit “Not monitored” statements build trust because uncertainty is named rather than dressed up as health. Preserve that honesty while replacing configuration prose with task-focused recovery.

## Persona walkthroughs

**Alex, impatient power user:** Can use drag/drop/paste, range/additive pointer selection, bulk actions, sorting, list/grid and transfer controls without a tutorial. Red flags: keyboard bulk selection unavailable in default list; no select-all accelerator found in the reviewed selection hook; a closed transfer cannot be recovered; long workspace lists lack filtering. Under-60-second completion cannot be established without runtime data.

**Sam, accessibility-dependent user:** Native fields, focus-visible styling, reduced motion, labeled icon actions, native Dialog and shared drawer containment are strong source foundations. Red flags: list selection is unavailable to keyboard, grid child keydown triggers unintended parent action, custom overlays do not contain focus or handle Escape, status color pairs are weak in dark theme. Real screen-reader output, zoom reflow and focus restoration remain unverified.

**Jordan, confused first-timer:** Clear sign-in instructions, Create/Join separation, Viewer/Editor explanations and manual invite-delivery notice reduce ambiguity. Red flags: first empty Drive lacks a direct next-step instruction; support is undiscoverable; registration detaches an invitation; the selected toolbar has many unlabeled-visible icons; upgrade takes the user to an unavoidable failure. Task success needs a first-use session to confirm.

## Strengths to preserve

1. **Scope is treated as a first-class task context.** Explicit workspace URLs, scoped folder trees, root destination capture and personal/shared-data distinctions help users know which room they are working in and which badge they are using.
2. **High-risk operations have substantial existing safeguards.** Current-password checks, purge filename/reason confirmation, protected members, manual invitation delivery copy and backend-confirmed transfer completion provide a strong base for trust.
3. **There is a usable shared system already.** Tokens, native Dialog, ContextMenu keyboard behavior, consistent directory spacing, container-responsive controls and reduced-motion handling can be reused to solve the gaps without a new design language.

## Recommended priorities and trade-offs

1. **Restore transfer control and honest error recovery (A01, A06, A10, A15).** Keep active transfer access persistent and show failure beside the form/data that caused it. This directly protects task completion; its value exceeds another layout pass. Preserve completed history separately so the tray stays manageable.
2. **Finish one keyboard contract across file views and overlays (A02–A04, A17).** Add accessible selection/open controls and reuse native Dialog/IconButton. Reuse is smaller and more sustainable than separate focus traps; confirm with keyboard and assistive-technology tests. The analogy is one reliable handle on every door.
3. **Complete semantic theme pairs (A05).** Add/reuse status surface/foreground tokens and replace unsafe hardcoded combinations. The existing palette can remain; the problem is pairing, not identity. Inspect error, warning and success states in both themes.
4. **Make next steps real and discoverable (A07–A09, A16, A18).** Preserve invitation continuation, link existing support, state unavailable capabilities before an action, and decide which deep operational routes are intended for current users. Avoid building roadmap backend features merely to justify existing UI.
5. **Unify common task conventions (A11–A14, A19).** Align date boundaries, event activation, membership confirmations and settings URLs with established patterns already in the code. This reduces learning cost without changing authorization policy.

For rendered follow-up, inspect desktop/tablet/phone and both themes with long names, slow/failed requests, initial empty state, existing content, selection, upload close/reopen, keyboard-only dialogs, 200% zoom and workspace switching. Source-defined widths are not proof of reflow. No visual or authenticated mutation result is claimed here.

A reusable workflow is evident: enumerate every route, map each to shared implementations, trace primary/error/empty/keyboard paths, then record only source-proven issues separately from rendered evidence. After this audit is resolved, consider packaging that route-coverage and evidence-separation checklist as a reusable Agent Skill.

Questions skipped: this independent Assessment A was explicitly scoped to research and reporting without questions; the parent owns synthesis and follow-up.
