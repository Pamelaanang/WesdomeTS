# Crew Grid: Functionality Reference and Comparison

Written for: the team maintaining WesdomeTS, to plan the Crew Grid as the single management switchboard.
Status as of 2026-10-03. "Grid" is `/crew/grid/`. Items marked **Not yet captured** have no grid or page equivalent, or are known gaps.

## How to read this

- **On grid:** the action can be done from the Crew Grid.
- **External only:** the action exists only on another page, listed in the last column.
- **Not yet captured:** no working path exists anywhere, or the path is known to be wrong.

## 1. Placement (who sits where)

| Function | On grid | Where else today | Notes |
|---|---|---|---|
| Add a member to a live basket | Yes (+Add on a position row, Add modal) | Crew Assignment Detail | Position is pre-selected from the row clicked. |
| Add members to an unassigned basket | Yes (Add members under Unassigned, or +Add on any position row) | None | Members wait without a leader; the banner flags the basket. |
| Remove a member without replacing | Yes (occupant's Replace modal) | Crew Assignment Detail | |
| Replace a seat occupant with an existing Miner | Yes (Replace modal) | Crew Assignment Detail | The old seat is ended, the new one starts. |
| Replace with a new hire | Yes (Replace modal, "Hire (pending IT access) & Replace") | Crew Assignment Detail | Creates a pending record. IT activates it. |
| Move a member between seats | Yes (drag and drop) | Crew Assignment Detail (live targets only) | Works live to live, live to unassigned, and unassigned to live. |
| Member also covers another crew (cross-crew seat) | Yes ("Also covers Crew ___" in the Add and Replace forms) | None | Joint AB/CD cells merge automatically. |
| Record a Miner's quit | Yes ("Record quit" in the Replace modal) | None | Immediate only. Ends seats and deactivates the account. |

## 2. Leadership (who runs each basket)

| Function | On grid | Where else today | Notes |
|---|---|---|---|
| Assign an existing shifter to an unassigned basket | Yes (fill modal, "Assign an Existing Shifter") | Shifter & Miner Management (as `assign_basket`) | An existing shifter with a basket can take an empty second basket. It's recorded as a basket lead. |
| Promote a Miner permanently into an unassigned basket | Yes (fill modal) | Shifter & Miner Management (`promote_to_shifter_permanent`) | Sets the Miner's level to Staff, which is intended. Ends their seat. |
| Temporary cover of an unassigned basket by a Spare Shifter | Yes (fill modal, "Temporary cover (Spare Shifter)") | Crew Coverage (promote action, see Not yet captured) | Recorded as a coverage. The Miner keeps their greyed seat. |
| Hire a new shifter on hold for IT | Yes (fill modal, "Hire a New Shift Coordinator") | None | The basket shows "Leader pending IT access" until activation. |
| Start temporary coverage of a live basket | Yes (Manage modal, "Start Coverage") | Crew Coverage (add) | Same overlap rule on both pages. |
| End coverage | Yes (end icon on the covered basket) | Crew Coverage (end) | The roster returns to the home shifter if they're still an active shifter, otherwise the basket is left vacant. |
| Make a covering shifter permanent | Yes (star icon, only once the home shifter is gone) | None | Refused while the home shifter is still an active shifter. |
| Transfer a basket permanently to another shifter | Yes (Manage modal, "Transfer") | Crew Assignment Detail | Moves the members and the home basket. |
| Swap two shifters' baskets | Yes (Manage modal, "Swap baskets") | None | Refused while either basket has coverage or either shifter leads a second basket. |
| Demote a shifter to Miner | Yes (header icon) | Shifter & Miner Management | If members are present, a fill is required. |
| Record a shifter's quit | Yes (header icon, or the home shifter's icon on a covered basket) | None | A fill is required when members would be left without a leader. |
| Fill a basket when a leader leaves | Yes (fill form on quit and demote) | None | Options depend on whether the basket is covered; see Section 5. |

## 3. Attributes and classification

| Function | On grid | Where else today | Notes |
|---|---|---|---|
| Edit a person's Level and Contract (and Employment Type) | Yes ("Edit Classification" on the level chip) | Shifter & Miner Management (bulk), System Admin (full edit) | Contract choices are filtered by level. Unclassified contracts appear under every level, by design. |
| Set crew and section for a shifter already placed | No | Shifter & Miner Management (bulk) | Deliberately left off the grid: it's rare and deliberate. |
| Bulk edit of crew, section, level, and employment type | No | Shifter & Miner Management | Stays on that page. |
| Classify positions by discipline, add positions, activate or deactivate them | No (grid links to Position Catalog) | Position Catalog | |

## 4. Accounts and onboarding (IT)

| Function | On grid | Where else today | Notes |
|---|---|---|---|
| Activate a pending hire (sets a temporary password) | No, by design | IT Onboarding | IT owns login access. |
| Reject a pending hire | No, by design | IT Onboarding | Keeps the record for audit, archived by the month it was resolved. |
| Add a brand-new employee account | No, by design | User Management | Account creation stays with IT. |
| Edit account details (name, role, phone, and so on) | No, by design | User Management | |
| Reset a password | No, by design | User Management | |
| Reactivate someone who has quit | No, by design | User Management | Refused for anyone still awaiting IT onboarding. |
| Replace an employee (System Admin path, with a new account) | No, by design | User Management | Kept as it was, by decision. |

## 5. Rules that apply on the grid

- **Every basket with members needs a leader.** A quit or demote of a leader refuses until the Superintendent chooses who runs the basket.
- **Covered baskets:** a quit or demote of the home shifter keeps the cover running. The choice is then to make the cover permanent, or to hire a new shifter on hold, and the cover ends when the new shifter is activated.
- **Temporary covers keep the Miner's seat.** The seat is greyed, so it can't be added to or moved into by mistake. Permanent promotions end the seat.
- **Overlapping coverage is refused** on a basket, except for a same-day handover.
- **Pending hires can be members** right away, but they can't log in until IT activates them.
- **Crew daily sheets:** a covered basket's roster leaves out the covering Miner, who fills their own row by hand if they want to. The captain checks it at the end of the day.

## 6. Not yet captured

| Gap | Where it stands | Next step |
|---|---|---|
| Crew Coverage "Promote to Spare" creates no coverage record | External only. The Miner keeps no greyed seat and no cover is recorded. | Make it record a coverage, or remove it once the grid covers the case. |
| Release a basket without replacing its leader | Not built. A leader can only leave through quit, demote, transfer, or swap. | Would work like demote, with the same fill rule. Decide whether to build it. |
| Joint AB/CD "no leader" warning | Not verified. | Investigate next. |
| 10Mine is not visible on the grid | Their row sits in a crew and discipline the band doesn't display, and Needs Attention doesn't list it. | Add rows the grid can't place to Needs Attention. |
| Contract choices for unclassified contracts | Data: they appear under every level. | Assign those contracts to levels. |
| Room allocation | Saved in the browser only. | Out of scope for now. |
| Crew Coverage history list | External only (Crew Coverage page). | Decide whether the grid needs a history view, or whether the page stays as the history screen. |
| Per-shifter Crew Assignment Detail page | Mostly duplicated by the grid. | Retire once the grid's coverage of its actions is confirmed in testing. |
| Shifter & Miner Management page | Bulk crew, section, level, and promote or demote. Partly duplicated by the grid. | Keep the bulk table, or fold it into the grid, once the scope is agreed. |
| Position Catalog | No grid equivalent beyond a link. | Decide whether discipline classification belongs on the grid. |

## 7. Pages outside management

The My Crew page (`/crew/my-crew/`) is for Shifters themselves, not the Superintendent. It isn't part of this comparison.
