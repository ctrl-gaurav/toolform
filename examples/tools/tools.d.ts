// A small ticket tracker, declared in TypeScript. The loader reads function
// declarations, their parameter types and their JSDoc comments.

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
export declare function open_ticket(title: string, priority?: Priority, assignee?: Person, labels?: string[]): string;

/**
 * Close a ticket with a resolution.
 * @param ticket_id The ticket to close.
 * @param resolution Why it is closed.
 */
export declare function close_ticket(ticket_id: number, resolution: "fixed" | "wontfix" | "duplicate"): void;

/**
 * Search tickets by text.
 * @param query Words to look for.
 * @param limit Most results to return.
 */
export declare function search_tickets(query: string, limit?: number): Array<{ id: number; title: string }>;
