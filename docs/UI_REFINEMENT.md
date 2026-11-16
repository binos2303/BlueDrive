# Drive, Workspace and admin UI refinement

## Restore point

- Baseline commit: `d968ebf`.
- Annotated Git tag: `backup/ui-before-workspace-polish-2026-11-07`.
- The working tree was clean when the tag was created.

This tag preserves the source before this UI pass. When restoring later, compare
against any subsequent work first and restore only the affected UI changes. Avoid
a blanket reset that could discard newer work. This is a source checkpoint, not a
database or storage backup.

The follow-up header/New refinement has a separate source ZIP checkpoint:
`C:\Users\dang2\AppData\Local\Temp\bluedrive-before-header-2026-11-07-55691762ed814a27945b0cd4a7804ed0.zip`.
It contains the 426 source files present before that follow-up, including the first
pass's uncommitted and newly added files. Ignored runtime data and secrets are not
part of this source checkpoint.

The subsequent Settings content refinement has a smaller seven-file checkpoint:
`C:\Users\dang2\AppData\Local\Temp\bluedrive-before-settings-content-2026-11-07-06a6aba25c3e441a9a1fc449481101c6.zip`.
This checkpoint was taken after moving New back to the sidebar and before changing
the Settings content. Use the earlier ZIP when reviewing the header/New rollback.

The Recent timeline/navigation cleanup has a seven-file source checkpoint:
`C:\Users\dang2\AppData\Local\Temp\bluedrive-before-recent-timeline-83b7819b037a476d90eadb8097051532.zip`.

The context-aware New/Profile consolidation has a nine-file checkpoint:
`C:\Users\dang2\AppData\Local\Temp\bluedrive-before-context-new-profile-7ee5dc592e2b4f35af66175049abdf2a.zip`.

## Navigation and collaboration

- Keep one **Shared with me** entry in the visible sidebar. This opens the existing
  incoming-shares API, which checks each item across tenants. Shared folders remain
  navigable, and the existing authorization boundary is preserved.
- **Shared by me** remains available through **Manage my shares** on the incoming
  shares page. Removing its sidebar entry does not remove access management.
- A selected workspace gets its own navigation: Files, Recent,
  Starred and Trash. Workspace managers also see Members and Activity. **Back to
  My Drive** clears the workspace used for both navigation and file requests.
- Files has the same folder-tree disclosure as My Drive. Both use the shared
  `DriveFolderNavigation` component, including nested expansion, selected-folder
  links, loading/empty/error states and retry. Each tree pins its request to its
  own workspace and remounts on scope changes to discard the previous tree.
- Opening a workspace management URL resolves the workspace from the authenticated
  user's available workspaces. Old async responses cannot reselect a workspace
  after the user leaves that route.
- Workspace navigation has explicit URLs: `/drive/workspaces/<id>/files`,
  `/folders/<folderId>`, `/recent`, `/starred` and `/trash` under the same Workspace
  prefix, alongside Members and Activity. The Workspace root redirects to Files.
  Switching, creating and joining a Workspace opens its Files URL. Folder-tree
  links, breadcrumbs, search and return links preserve that prefix.
- On Drive routes, the URL selects the API workspace immediately, including direct
  links, reloads and Back/Forward. `/drive` and its personal views always select
  My Drive. Account pages retain the saved workspace context. The backend remains
  responsible for authentication and membership checks on every request.
- Invitations live in Workspace Members; remove the unused duplicate invitation
  dialog from the switcher.
- The workspace switcher now lives in the header. Its My Drive option is always
  visible when opened, and the workspace sidebar also provides a My Drive return
  link. Hide `isDefault` workspaces regardless of tenant type; do not hide ordinary
  workspaces merely because their user-chosen name happens to be General.

## Accounts and roles

The current backend has Workspace and WorkspaceMembership models; there is no
separate live Team/Group collaboration model to migrate. Account identity, billing
account type, organization membership and workspace role are different concepts.
One account can hold different roles in different workspaces, like a person holding
different access badges for different rooms.

Consolidate the former Teams directory into Workspaces, retaining the ownership
filter and active explicit member/role counts. Platform administrators inspect
metadata here; workspace managers retain membership authority. Keep Admin, Editor
and Viewer workspace roles and all existing protection rules.

The old `/admin/teams` and `/admin/infrastructure/quotas/teams` URLs redirect to
their Workspaces equivalents through Next.js configuration. Use temporary redirects
so a later rollback is not obstructed by a cached permanent redirect.

## Layout and controls

- Shared buttons use 40px compact and 44px standard heights; touch controls use a
  minimum 44px target. Main interface text is 14px, with 12–13px supporting text.
- Move control font inheritance into the CSS base layer so it no longer overrides
  each component's typography. Use explicit foreground colors for primary and
  destructive buttons in both themes.
- Keep New fixed below the logo in the Drive and Settings sidebars, outside the
  scrolling navigation, on all Drive/account/Workspace tabs. Its upload and
  folder actions target My Drive root when personal Drive is selected, or Files
  root in the selected Workspace, without changing the visible tab. Capture the
  destination when opening the picker/dialog; subsequent Workspace switches must
  not redirect an already-started operation.
  Mount its file pickers and folder dialog in the shell, so the menu works even
  when the file browser is not mounted.
- Remove the separate Add to workspace menu. Workspace file browsing retains
  existing drop/paste intake. Capture workspace and folder before asynchronous
  preparation, and carry that workspace through queued upload, retries, resume,
  part authorization and completion. Duplicate detection is workspace-specific.
  Backend permissions still determine whether any mutation succeeds.
- Use a compact desktop header and reduce the file browser's top padding and
  toolbar height. On narrow screens, move search onto its own row, retain the
  workspace switcher in the header and access New through the navigation drawer.
- Sidebar widths and navigation rows follow one scale. Mobile drawers share focus
  restoration, Escape dismissal and keyboard containment.
- Drive grids adapt to their available content width. Compact file tables move
  owner, size and modification information below the name as columns collapse.
- Admin directories share table spacing, fixed column proportions, truncation for
  long identifiers and wrapping action groups. Filter rows respond to panel width,
  accounting for the sidebar. Wide admin tables scroll inside their own panel.
- Remove the Organizations sort selector: the current endpoint supports search
  and newest-first ordering, not the other sort choices that were displayed.

## Account Settings refinement

- Match the Drive sidebar's logo, width, New position and navigation spacing.
- Give each section a heading and short explanation. Use container-responsive
  preference rows for storage, appearance and language; keep controls below their
  labels when the available panel width is narrow.
- Limit the password form width, use 44px inputs and align the submit action with
  the fields. Remove Active sessions, its client-side loading and revocation
  controls from Settings; retain the backend session protections and the existing
  password-change behavior that revokes other sessions.
- Separate history filters from headings, stack them on narrow panels, and make
  each activity row a native button that opens its existing detail dialog.
- Distinguish loading, unavailable and empty states. Password and destructive-action
  authorization and confirmation flows remain unchanged.
- Consolidate Profile and password management in Settings → Profile & Security.
  Reuse the original email-update form and current-password validation, keeping
  username read-only. Remove the separate Profile menu action. `/account/profile`
  temporarily redirects to `/account/settings?section=security`, whose server
  route opens the combined section directly. Other Settings sections retain their
  existing behavior.

## Recent timeline

- Show a 14-day bar chart above the existing file list/grid in Recent, using the
  active My Drive or Workspace's existing Recent response. Retain the original API
  timestamp alongside its localized display date for accurate local-day grouping.
- Count each item once by its latest access/update, including zero-count days.
  Explain that this covers up to 100 recent items; it is not a complete event log.
  Preserve older items in the list below the chart.
- Keep the chart inside the scrolling content, support horizontal scrolling and
  keyboard access on narrow screens, and exclude the chart from marquee selection.
- Respect the browser's existing loading/error states and workspace request scoping.

## Validation

- Frontend unit tests: 131 passed. Coverage includes workspace identity/selection events, member protection,
  directory queries and the follow-up upload destination binding. Run
  `npm run test:workspace-context` for the real request-header regression check.
- TypeScript, ESLint and production build completed successfully during this pass.
- Production HTTP smoke checks passed for six primary routes and both legacy
  redirects (307 with the expected Workspaces destination). These check route
  delivery, not authenticated API behavior or browser rendering.
- Follow-up shell checks passed for seven Drive/Workspace routes: global New and
  the personal file picker are present even when the file-browser view is absent.
- Sidebar/Settings follow-up: production build (including TypeScript), ESLint,
  two workspace-context tests and five account-security policy tests passed.
  Seven HTTP shell checks, including Account Settings and Workspace Members,
  confirmed New is in the sidebar, absent from the header, and accompanied by
  the personal upload picker. The changed UI files had no static scan findings.
- Recent/navigation cleanup: production build (including TypeScript), ESLint and
  nine targeted tests passed (two timeline, two workspace-context, five security
  policy). Timeline tests cover local-day boundaries, invalid/missing timestamps,
  excluded dates, zero-count days and year transitions. Static UI scan was clean.
- Workspace folder navigation: production build (including TypeScript), ESLint,
  both workspace-context tests and the changed-file static scan passed. The request
  regression test now explicitly checks personal and workspace folder-tree headers.
- Context-aware New/Profile: production build (including TypeScript), ESLint and
  14 targeted tests passed (workspace context, upload lifecycle and security policy).
  Tests exercise root destination capture in My Drive and Workspaces, switching
  after capture, current-folder intake, retries and completion. HTTP checks passed
  for Drive, Settings and the combined security section; the old Profile URL
  returned the expected 307 redirect. Changed-file static scan was clean. Browser
  verification and authenticated upload/profile mutation checks remain unverified
  because the browser host and native pipe are unavailable.
- Explicit Workspace URLs: production build (including TypeScript), ESLint and
  26 targeted tests passed across route/context handling, upload lifecycle, browser
  utilities and breadcrumb moves. HTTP checks covered seven Workspace views,
  the root-to-Files 307 redirect and five invalid routes returning 404. Static UI
  scan was clean. Both avatar-menu implementations were inspected: the Drive menu
  has Settings/Sign out, the admin menu has Manage accounts/Sign out, and neither
  contains a Profile action. Profile management remains inside Settings.
- Static design scan returned no findings. Palette contrast checks covered muted
  text on both light surfaces and primary action text in light/dark themes.
- Browser visual and interaction verification is **pending**: the first pass
  stopped because computer use could not verify the browser URL; in the header
  follow-up and Settings refinement, the native pipe and browser host were
  unavailable. No screenshots were produced.
- Local backend execution is **unverified**: `.venv` points to a missing Python
  installation. No database migration, user reclassification mutation, permission
  change or storage operation was performed.

Before calling the visual pass approved, inspect My Drive, incoming/outgoing
shares, Workspace Files/Members/Activity and admin Users/Workspaces/Organizations/
Files/Quotas/Logs at phone, tablet and desktop sizes, in both themes. Check long
names, loading/error/empty states, rapid workspace switching and keyboard use.

## Follow-up scope

The user confirmed that the supplied Workspace function inventory is a roadmap,
not a request to implement missing functionality in this UI pass. Pending-invite
management, additional Settings surfaces, invitation email and file versioning
remain outside this follow-up. No workspace storage amount or Start-plan limit
has been invented.
