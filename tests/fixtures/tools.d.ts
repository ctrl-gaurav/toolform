// Declarations for a small ticket tracker.

/** A person on the team. */
interface Person {
  /** Login name. */
  login: string;
  /** Display name. */
  name?: string;
}

type Priority = "low" | "normal" | "high";

/**
 * Open a new ticket.
 * @param title Short summary of the problem.
 * @param priority How urgent it is.
 * @param assignee Who should handle it.
 * @param labels Labels to attach.
 * @returns The new ticket's id.
 */
export declare function open_ticket(title: string, priority: Priority = "normal", assignee?: Person, labels?: string[]): string;

/**
 * Close a ticket with a resolution.
 */
export function close_ticket(args: { ticket_id: number; resolution: "fixed" | "wontfix" | "duplicate"; note?: string | null }): void {
  const x = { a: 1 };
  if (x.a > 0) { return; }
}

/** Search tickets. */
declare function search_tickets(query: string, limit?: number, filters?: Record<string, string>): Array<{ id: number }>;
