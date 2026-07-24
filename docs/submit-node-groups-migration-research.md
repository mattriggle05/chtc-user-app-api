# Submit Nodes → Groups Migration: Research Writeup

Status: **research only** — no plan or implementation decisions yet. This document exists to
be the shared factual basis for a follow-up planning pass.

Scope covers two repos:
- `chtc-user-app-api` (this repo) — FastAPI backend, currently on branch `feature/enhanced-submit-nodes`
- `chtc-user-ui` (`/Users/mriggle/Coding/chtc-user-ui`) — Next.js/TypeScript frontend

---

## 1. Why this is happening (GitHub issue #16)

Thread on [CHTC/chtc-user-app-api#16](https://github.com/CHTC/chtc-user-app-api/issues/16), chronological:

1. **CannonLock** asks brianhlin for real Unix group names for the known submit nodes (a list
   of 16 `{id, name}` pairs — this is the seed for the spreadsheet the user later pasted).
2. **CannonLock proposes an initial plan** (now superseded, see §4):
   - Add `groups.type: Enum('SUBMIT_NODE')` (nullable) and `groups.description: String` (nullable) to `Group`.
   - Migration: create the real groups from a shared spreadsheet, then for every user with
     access to submit node X, add them to the group Y that replaces it.
   - Explicit goal: **"Completion of this ticket will result in a UI that is indistinguishable
     from the previous UI."** Frontend should query on `type` to get "the list of submit nodes"
     and use group labels as the human-readable display string.
   - Explicit permission: **"API results are okay to change. I don't expect this to be backward
     compatible."**
3. **CannonLock's corrected/final plan, addressed directly to mattriggle05** (this is the plan
   actually being implemented right now):
   - DB: `+submit_nodes.group_id` (FK to the group associated with the submit node);
     `-user_submits` (deleted — membership derived from group membership; quota data deferred
     to a future table keyed on `(user, submit_node)`).
   - API: `/submit_nodes` acknowledges the new field; `POST`/`PATCH /users` submit-node
     assignment adds the user to the associated group instead of writing a `UserSubmit` row;
     `GET /users/{id}/submit_nodes` returns nodes derived from group membership (proposed shape:
     `UserSubmitView = {user_id, **submit_node_fields}`).

**Important:** two different backend designs were floated in this one issue. The first
(`groups.type` enum, no independent submit-node entity) was implemented experimentally on
branch `feature/submit-node-login-groups` (see §4) but was **not merged** and appears to have
been superseded by the second, more specific plan aimed at mattriggle05 — which is what's
currently in progress on `feature/enhanced-submit-nodes`. Anyone picking this up needs to know
the first design was tried, works, and was still set aside in favor of the second.

---

## 2. Current backend state (`feature/enhanced-submit-nodes`, in progress)

Already implemented this session (uncommitted, plus one generated-but-unedited migration):

- **`SubmitNode`** ([tables.py](../userapp/core/models/tables.py)) keeps its own table/identity
  and gains `group_id` (nullable FK → `groups.id`, `ON DELETE SET NULL`). A submit node **can**
  exist with no group (transitional state).
- **`UserSubmit` / `user_submits` table deleted entirely.** No quota fields
  (`disk_quota`, `hpc_diskquota`, `hpc_inodequota`, `hpc_joblimit`, `hpc_corelimit`,
  `hpc_fairshare`, `for_auth_netid`) survive anywhere in the API. Per the issue, this data is
  meant to move to a new table keyed on `(user, submit_node)` — **not yet designed or built.**
- **`UserSubmitView`** (renamed from `UserSubmitNodesView`, backing DB view `user_submit_nodes`)
  reshaped from `{user_id, submit_node_id, submit_node_name, <quota fields>}` to
  `{user_id, id, name, group_id}` — i.e. `user_id` plus the submit node's own fields, matching
  the issue's suggested shape. **The view's SQL itself has not been rewritten yet** — it still
  needs a `DROP VIEW`/`CREATE VIEW` sourced from `user_groups ⋈ submit_nodes.group_id`, to be
  hand-added to the generated migration.
- **Write-through helper** `_patch_user_submit_nodes` ([_util.py](../userapp/api/routes/_util.py))
  resolves requested `submit_node_id`s → `group_id`s, then adds/removes `UserGroup` rows,
  scoped only to groups that are actually tied to some submit node (never touches unrelated
  group memberships). Used by `POST/PATCH /users` and form-approval (`on_user_form_accept`).
  Raises 400 if a requested submit node has no `group_id` yet.
- **Migration generated:** `alembic/versions/5a9269d00368_add_submit_nodes_group_id_drop_user_.py`
  — table-level diff only (drop `user_submits` + its indexes, add `submit_nodes.group_id` + FK +
  index). Still needs, before it's usable: the view drop/recreate (both directions), and an
  explicit FK constraint name (autogenerate emitted `None` for both `create_foreign_key` and the
  matching `drop_constraint` in `downgrade()`, which won't reliably round-trip).
- Tests updated to match (dynamic group+submit-node creation instead of hardcoded IDs 1/2,
  field-name renames). Not yet run against a real Postgres — only reachable DB is a
  `kubectl port-forward` to the shared `chtcdev` dev cluster, which we've deliberately avoided
  touching.
- **`/submit_nodes` CRUD router is unchanged/kept** — this design keeps submit nodes as a
  distinct, independently listable/creatable entity (unlike the abandoned branch, see §4).

**Not yet addressed by current work:**
- The quota-table replacement (deferred per the issue itself).
- Any data migration to actually create real groups for the known submit nodes and backfill
  existing users' access (the abandoned branch did this with hardcoded seed data; current
  branch has not).
- The view SQL rewrite + FK naming fix in the generated migration.
- Anything on the frontend.

---

## 3. The abandoned branch: `feature/submit-node-login-groups`

9 commits ahead of merge-base `ad82974` (same as current `main`'s tip), never merged. Implements
CannonLock's **first** proposal from the issue (§1.2), not the one currently being built.

**Design:** no independent submit-node entity at all. `SubmitNode`/`UserSubmit` tables, their
views, schemas, and the entire `/submit_nodes` router are **deleted outright**. `Group` instead
gains:
```python
type = Column(SQLEnum(GroupTypeEnum, name='group_type_enum'), nullable=True)  # only member: SUBMIT_NODE
description = Column(String(255), nullable=True)
```
A "submit node" is nothing but a `groups` row tagged `type='SUBMIT_NODE'`. Access is purely
`UserGroup` membership; `_patch_user_submit_nodes` became `_patch_user_submit_node_groups`,
diffing `user.groups` (filtered to `type == SUBMIT_NODE`) against a plain `list[int]` of group
ids (`UserFormPatch.submit_node_group_ids: list[int]`, not `list[UserSubmitPost]`).

**Migration** (single file, `026216ef4d8a`): creates the enum, adds the two `Group` columns,
**hardcodes and inserts the 9 known submit-node groups** (`wright-ap-login`, `ap2001-login`,
`htc-transfer-login`, etc. — this is the same list as the issue's `{id,name}` table and
presumably an earlier cut of the user's pasted spreadsheet), backfills `user_groups` from
`user_submits ⋈ submit_nodes ⋈ <hardcoded node→group name mapping>`, then drops
`user_submit_nodes` view → `user_submits` table → `submit_nodes` table in that order. The
`downgrade()` is fully written (not a stub) and explicitly comments that per-user quota
overrides are **not recoverable** on downgrade since they were never carried forward — direct
evidence that this same data-loss question exists for the current design too, since it also
drops `user_submits` without giving that data a new home yet.

**Assessed as complete, not half-finished:** no leftover comments/TODOs, no skipped tests, full
downgrade path, tests fully rewritten in lockstep (`test_submit_nodes.py` deleted, `test_users.py`
submit-node tests removed, `test_forms.py` helper renamed to `create_submit_node_group` and now
posts to `/groups` instead of `/submit_nodes`). It reads like a working solution that was
deliberately set aside for the more specific plan, not abandoned due to a dead end.

**Reusable pieces / concrete tensions vs. the current design:**

| Question | Abandoned branch | Current branch |
|---|---|---|
| Independent submit-node ID? | No — `submit_nodes.id` gone, only `groups.id` exists | Yes — `submit_nodes.id` preserved, `group_id` is just an FK on it |
| Can a submit node exist with no group? | N/A (no separate entity) | Yes, nullable `group_id` |
| `/submit_nodes` router | Deleted | Kept |
| "List submit nodes" query | Generic `/groups` filter (no dedicated `type=` filter param was ever added — a gap in that branch too) | Native `/submit_nodes` list |
| Quota-field fate | Explicitly dropped, documented as unrecoverable on downgrade | Also dropped by the current migration; **still no new home designed** |
| Naming pattern for the group-diff helper | `_patch_user_submit_node_groups(user, group_ids: list[int])` | `_patch_user_submit_nodes(user, submit_nodes: list[UserSubmitPost])` (resolves ids → groups internally) — same diffing logic, different input shape |

The **biggest open question a future implementer must resolve**: does anything outside this API
(HTCondor config, other CHTC tooling, another database) reference a `submit_node_id` value
today? If yes, the current design (stable ID) is necessary. If no, the abandoned branch's
simpler "just a group" model remains a live alternative and its migration is a ready-made
template (including the hardcoded seed-data pattern, which will need re-deriving from the
now-more-authoritative spreadsheet in §5).

---

## 4. Frontend state (`chtc-user-ui`)

Checked out on `enhanced-submit-nodes` (commit `d60d890`) — matches the **old**, pre-migration
API shape end to end (`SubmitNode{id,name}`, `UserSubmitGet` with `submit_node_id`/
`submit_node_name`/all six quota fields). No code currently assumes any part of this migration.

**Where submit nodes are used today:**
- `SubmitNodeAutocomplete.tsx` — generic picker hitting `GET /submit_nodes`.
- `Forms/UserForm/UserForm.tsx` — admin user create/edit. Lets an admin add/remove submit nodes
  by `submit_node_id`; in edit mode renders a **read-only table of quota fields** (Disk Quota,
  HPC Disk/Inode/Job/Core/Fairshare) per assigned node. This table goes dead/blank once the
  backend drops those fields — no crash, but a stale UI section that should be removed.
- `Forms/UserApplicationForm/UserApplicationEditForm.tsx` — **the actual account-approval UI**:
  admin picks submit nodes via autocomplete + "Add Submit Node" button, rendered as **MUI Chips**
  (not checkboxes — see caveat below), submitted as `submit_nodes: [{submit_node_id}]` on
  `PATCH /forms/user-applications/{id}`.
- `app/email/page.tsx` — bulk email tool filters users by submit node client-side.

**No checkbox-based submit-node UI exists anywhere in this repo (any branch), and no hostnames
from the pasted spreadsheet (`wright-ap4000.chtc.wisc.edu` etc.) appear in its source or git
history.** The "checkbox" framing in the spreadsheet almost certainly refers to a different,
likely legacy/external system (possibly the old pre-`chtc-user-app-api` account-request form —
consistent with `transition/` in this repo being a one-time import from a legacy system), not
anything in `chtc-user-ui` today. **Worth confirming with the user/CannonLock/brianhlin where
that checkbox UI actually lives**, since it isn't here.

**`/groups` already has full CRUD + membership UI**, but it's **admin-only** in the nav
(`AppShell.tsx`'s `adminPages`). A user's own group memberships are already shown read-only on
their own account page (`/users/me`) via `UserGroupTable`, with no edit affordance — i.e. some
of the "expose groups to end users" groundwork already exists, just not the submit-node-specific
framing.

**`openapi.json` (root of chtc-user-ui) is badly stale** — last regenerated before `/submit_nodes`,
`/tokens`, or `/forms/user-applications` even existed; don't use it as a reference. `types.ts` is
more current (matches the OLD submit-node shape) but will need regenerating against whatever the
API looks like once this migration ships.

### 4a. Critical finding: an unmerged frontend branch already assumes the *other* design

**`groups-select-for-submit-nodes`** (7 commits ahead of the same `d60d890` base, not merged)
already implements a frontend-side version of this migration — but built against the
**abandoned** `groups.type = 'SUBMIT_NODE'` backend design (§3), not the `submit_nodes.group_id`
design actually being implemented now:

- Adds `GroupTypeEnum = "SUBMIT_NODE"` to `Group`/`GroupCreateUpdate`/`UserGroupView` types.
- Repoints `SubmitNodeAutocomplete` from `/submit_nodes` to `/groups?type=eq.SUBMIT_NODE`.
- Changes approval-form submission from `submit_nodes: [{submit_node_id}]` to
  `submit_node_group_ids: number[]`.
- Hides the submit-node quota table in `UserForm.tsx` outright.
- Deletes `SubmitNode`/`UserSubmitGet`/quota types from `types.ts` entirely.

**This branch cannot land as-is against the API being built now** — the API won't have
`groups.type`, and it still exposes `/submit_nodes` and `submit_nodes.group_id` rather than a
group-type filter. This needs explicit reconciliation before frontend planning starts: either
rewrite this branch against the real contract (`GET /groups`-style filter → `GET /submit_nodes`
with `group_id`; `submit_node_group_ids` → whatever shape `UserSubmitPost`/`_patch_user_submit_nodes`
ends up expecting), or treat it purely as a reference for *which frontend call sites need to
change* (it already enumerates them) while re-doing the actual request/response shapes.

---

## 5. The spreadsheet: target submit-node → group mapping

User-provided, presumably a newer cut of the same list CannonLock asked brianhlin to fill in on
the issue (16 nodes there vs. these — check for drift: the issue's list still has `id`s 1–33 and
includes `test-ap2000.chtc.wisc.edu`? no — issue list doesn't include it, but does include
`jupyter0000.chtc.wisc.edu`/`osg-learn`/`osghost`/`annex-cm`, which this spreadsheet also marks
for deletion/staff-only, so they're consistent, just the spreadsheet is more decisive):

| Old checkbox / hostname | New checkbox / target group | Disposition |
|---|---|---|
| wright-ap4000.chtc.wisc.edu | wright-ap-login | Active — migrate |
| townsend-submit.chtc.wisc.edu | townsend-ap-login | Active — migrate |
| hpclogin1.chtc.wisc.edu | spark-login | Active — migrate (note: renamed, not just suffixed) |
| osg-sw-submit.chtc.wisc.edu | osgsw-ap-login | Active — migrate |
| oconnor-ap.chtc.wisc.edu | oconnor-ap-login | Active — migrate |
| learn.chtc.wisc.edu | learn-ap-login | Active — migrate |
| htc_transfer | htc-transfer-login | Active — migrate |
| ap2002.chtc.wisc.edu | ap2002-login | Active — migrate |
| ap2001.chtc.wisc.edu | ap2001-login | Active — migrate |
| COSMOS | — | **Retired, delete** ([INF-2991](https://opensciencegrid.atlassian.net/browse/INF-2991)) |
| jupyter0000.chtc.wisc.edu | — | **Retired, delete** ([INF-2142](https://opensciencegrid.atlassian.net/browse/INF-2142)) |
| osg-learn.chtc.wisc.edu | — | **Retired, delete** |
| osghost.chtc.wisc.edu | — | **Retired, delete** |
| deepdivesubmit2000.chtc.wisc.edu | — | **Staff-only** — should not be self-service checkbox-controlled |
| annex-cm.chtc.wisc.edu | — | **Staff-only** — should not be self-service checkbox-controlled |
| test-ap2000.chtc.wisc.edu | — | **Staff-only** — should not be self-service checkbox-controlled |

Notable pattern: for every "active" row, **new checkbox label == target Unix group name**
exactly — no separate human-readable label distinct from the group name is needed for these.
That simplifies the `groups.description`/label question the original (superseded) plan raised.

Three categories of action implied, none yet designed in code:
1. **Delete** the 4 retired submit nodes (and any dangling user access to them).
2. **Exclude from self-service** the 3 staff-only nodes — they may still need to exist as
   `SubmitNode` rows (staff still need *something* to reference/manage), but must not be
   selectable in whatever UI lets ordinary users request/manage their own access. This implies
   either a flag distinguishing "self-service-eligible" submit nodes, or simply never creating a
   selectable group for them and handling their access purely via direct admin group management
   (which already exists via `/groups/{id}/users`).
3. **Create real groups** for the 9 active nodes and set `submit_nodes.group_id` accordingly —
   this is the actual data migration step CannonLock's original plan (§1.2) called for, still
   not built for the current (group_id-FK) design.

---

## 6. Open questions / tensions to resolve before planning

1. **Does anything outside this API rely on a stable `submit_node_id`?** Determines whether the
   current table-keeping design is required or whether the abandoned branch's simpler
   groups-only model is still on the table.
2. **Where does per-user quota data go?** Explicitly deferred by the issue ("added later as a new
   table"), but both the abandoned branch and the current migration drop `user_submits` (and its
   quota columns) with nothing replacing it yet. Needs a decision before or alongside this ships,
   since `UserForm.tsx`'s quota table goes dead the moment this lands.
3. **Where does the "checkbox" UI in the spreadsheet actually live?** Not found anywhere in
   `chtc-user-ui`. Needs confirming before frontend planning — may be a different repo, a legacy
   system, or aspirational/not-yet-built.
4. **What happens to `groups-select-for-submit-nodes`?** Built against the abandoned backend
   design; needs an explicit decision (rebase/rewrite vs. discard-but-mine-for-call-sites)
   before frontend implementation planning.
5. **Self-service eligibility flag for staff-only submit nodes.** No existing field models
   "can a non-admin request this" — needs a decision (new column? absence of a group means
   ineligible? separate allowlist?).
6. **Retirement/cleanup mechanics.** Deleting a `SubmitNode` cascades how, exactly, to any
   existing `UserGroup` rows tied to its (would-be) group, and to any other system consuming the
   retired hostnames?
7. **`/submit_nodes` list filtering.** If kept as a distinct router (current design), does it
   need a way to distinguish self-service-eligible vs. staff-only nodes for the frontend to
   query (neither the current branch nor the abandoned one has built this)?
8. **openapi.json/types.ts regeneration** needs to happen once the backend contract is final —
   both are currently stale to varying degrees and shouldn't be trusted as ground truth today.
