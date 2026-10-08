import type { Me, TimeEntry } from "./api/types";

/**
 * UI mirror of server-side rules (API.md §2.1 permissions). The server stays
 * authoritative; these flags only hide or lock controls a child cannot use.
 * Missing flags (older backend) are treated as "not allowed".
 */
export function permissionsOf(me: Me) {
  const p = me.permissions;
  return {
    canConfirmQuality: Boolean(p.can_confirm_quality),
    canSetWorkload: Boolean(p.can_set_workload),
    canEditTimezone: Boolean(p.can_edit_timezone),
    canDeleteReviewed: Boolean(p.can_delete_reviewed_entries),
  };
}
export type Permissions = ReturnType<typeof permissionsOf>;

/** Confirmed/rejected lesson entries were reviewed by an adult. */
export const isReviewed = (e: TimeEntry) => e.quality_status === "confirmed" || e.quality_status === "rejected";
