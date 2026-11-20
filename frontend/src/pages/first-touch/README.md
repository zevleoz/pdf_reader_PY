# First Touch shell migration

`FirstTouch` resolves permitted student metadata from `/api/students`, then the
existing profiling API. Account summary policy is checked before either request;
profiling permissions/restricted state are checked before controller creation.
Viewer controllers remain read-only. Existing server gates remain authoritative.

The factory in `static/js/first_touch_workspace.js` is byte-identical to the inline
factory at baseline `3e3b9b3` (SHA256
`85f513a2be34dd0c18201c6f08a647cc42ddbfd5f7ab8812373c06e8e16dc97d`).
The public asset is a relative symlink to that source; Vite copies it unchanged
into `static/app/assets`. Both the legacy template and React load that hashed URL
through the existing app-shell asset route. The application intentionally has no
generic Flask static endpoint. If the factory intentionally changes later, update
the asset name, symlink, loader, legacy URL and fingerprint together.

`controller.ts` adds request/lifetime cancellation and caller signal composition,
cancellable delays, guarded action entry, timer cleanup, imperative DOM refs and
next-tick scheduling. It leaves domain actions, payloads, revisions, autosave and
job result interpretation in the shared factory. `observable.ts` observes plain
containers and arrays, preserving browser/native instances. `workspace-contract.ts`
types the structural boundary and basic state; dynamic server payloads retain
`any`. The hook supplies React notifications, the legacy toast shim and cleanup.

`navigation.ts` captures shell links and browser history before BrowserRouter.
Rejected Back/Forward uses the router history indices to restore the departing
entry, suppressing its compensating event without recursive dispatch.

The three legacy phases/actions are JSX in `WorkspaceView`; the existing Button
and Sheet components supply shell controls and accessible chat focus handling.
List, guide, original workspace and admin archive remain reachable. Report export
URLs and the legacy controller's preview/save/confirmation race semantics remain
unchanged. No new domain API implementation, storage, AI calls or dependencies.

Verification (from this worktree):

- `node --test tests/first_touch/frontend.test.mjs` — 14 synthetic tests.
- `/Users/jefflau/anaconda3/bin/python -m pytest tests/first_touch test_first_touch_pages.py test_privacy_gates.py test_copilot_routes.py test_copilot_gapfixes.py -q` — 113 passed.
- `npm run build --prefix frontend` — typecheck and build passed; Vite reports the main bundle size advisory.

The extraction tests use a pinned fingerprint, not git history, and check built
asset equality, legacy loading and JSX action coverage. Frontend tests cover
native receivers, disposed requests, composed polling abort, delays/timers,
stale responses, summary/viewer gates, phase rendering, Back refusal, interest
editing/undo, conflicts/errors, report confirmation/exports, project provenance,
and chat history. Real AI and browser layout are not exercised by these tests.
