import { create } from "zustand";
import {
  api,
  ApiError,
  type Approval,
  type ApprovalAction,
  type ApprovalDecisionResponse,
} from "@/lib/api";

type Status = "idle" | "loading" | "ready" | "error";

interface ApprovalsState {
  items: Approval[];
  status: Status;
  error: string | null;
  // True when the backend reports HITL is disabled (501 Not Implemented).
  // The Inbox renders a banner instead of the empty-state placeholder.
  hitlDisabled: boolean;

  fetch: (params?: { sessionId?: string; requiresRole?: string }) => Promise<void>;

  // Resolve a pending approval. Approve/modify/defer resume the run on the
  // backend; reject terminates it. The returned promise resolves with the
  // backend response so callers can show the resulting status. After a
  // decision the row is removed from `items` (it's no longer pending).
  decide: (
    id: string,
    action: ApprovalAction,
    extras?: { edits?: Record<string, unknown>; reason?: string; deferCondition?: string; decidedBy?: string },
  ) => Promise<ApprovalDecisionResponse>;
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

export const useApprovalsStore = create<ApprovalsState>((set, get) => ({
  items: [],
  status: "idle",
  error: null,
  hitlDisabled: false,

  fetch: async (params) => {
    set({ status: "loading", error: null });
    try {
      const items = await api.listApprovals({
        sessionId: params?.sessionId,
        requiresRole: params?.requiresRole,
      });
      set({ items, status: "ready", hitlDisabled: false });
    } catch (e) {
      if (e instanceof ApiError && e.status === 501) {
        set({ items: [], status: "ready", hitlDisabled: true, error: null });
        return;
      }
      set({ status: "error", error: errorMessage(e), hitlDisabled: false });
    }
  },

  decide: async (id, action, extras) => {
    const result = await api.decideApproval(id, {
      action,
      edits: extras?.edits,
      reason: extras?.reason,
      defer_condition: extras?.deferCondition,
      decided_by: extras?.decidedBy,
    });
    set({ items: get().items.filter((a) => a.approval_id !== id) });
    return result;
  },
}));
