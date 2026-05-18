import { useEffect, useMemo, useState } from "react";
import { Check, X, Pencil, Clock, RefreshCw, Inbox as InboxIcon } from "lucide-react";
import { toast } from "sonner";
import { useApprovalsStore } from "@/stores/approvals";
import type { Approval, ApprovalAction } from "@/lib/api";

function ageString(epoch: number): string {
  const sec = Math.max(0, Date.now() / 1000 - epoch);
  if (sec < 60) return `${Math.floor(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}

function ttlString(approval: Approval): string | null {
  if (!approval.expires_at) return null;
  const left = approval.expires_at - Date.now() / 1000;
  if (left <= 0) return "expired";
  if (left < 3600) return `expires in ${Math.floor(left / 60)}m`;
  if (left < 86400) return `expires in ${Math.floor(left / 3600)}h`;
  return `expires in ${Math.floor(left / 86400)}d`;
}

export function Inbox() {
  const items = useApprovalsStore((s) => s.items);
  const status = useApprovalsStore((s) => s.status);
  const error = useApprovalsStore((s) => s.error);
  const hitlDisabled = useApprovalsStore((s) => s.hitlDisabled);
  const fetchAll = useApprovalsStore((s) => s.fetch);
  const decide = useApprovalsStore((s) => s.decide);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [editsJson, setEditsJson] = useState("");
  const [deferCondition, setDeferCondition] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // Keep the selection valid as the list changes.
  useEffect(() => {
    if (selectedId && !items.find((a) => a.approval_id === selectedId)) {
      setSelectedId(items[0]?.approval_id ?? null);
    } else if (!selectedId && items.length > 0) {
      setSelectedId(items[0].approval_id);
    }
  }, [items, selectedId]);

  const selected = useMemo<Approval | null>(
    () => items.find((a) => a.approval_id === selectedId) ?? null,
    [items, selectedId],
  );

  // Seed the edits editor with the current payload's allowed-edit fields.
  useEffect(() => {
    if (!selected) {
      setEditsJson("");
      return;
    }
    const seed: Record<string, unknown> = {};
    for (const k of selected.allowed_edits) {
      seed[k] = selected.payload[k];
    }
    setEditsJson(JSON.stringify(seed, null, 2));
    setReason("");
    setDeferCondition("");
  }, [selected?.approval_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (action: ApprovalAction) => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const extras: { edits?: Record<string, unknown>; reason?: string; deferCondition?: string } = {};
      if (action === "modify") {
        try {
          extras.edits = JSON.parse(editsJson || "{}");
        } catch {
          toast.error("Edits must be valid JSON");
          setSubmitting(false);
          return;
        }
      }
      if (reason.trim()) extras.reason = reason.trim();
      if (action === "defer" && deferCondition.trim()) extras.deferCondition = deferCondition.trim();
      const result = await decide(selected.approval_id, action, extras);
      toast.success(`${action} → ${result.status}`);
      fetchAll();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-full">
      {/* Left rail — list */}
      <div className="w-80 border-r flex flex-col">
        <div className="flex items-center justify-between p-3 border-b">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <InboxIcon size={16} />
            <span>Inbox</span>
            <span className="text-xs text-muted-foreground">({items.length})</span>
          </div>
          <button
            type="button"
            onClick={() => fetchAll()}
            className="p-1.5 rounded hover:bg-muted text-muted-foreground"
            aria-label="Refresh"
          >
            <RefreshCw size={14} className={status === "loading" ? "animate-spin" : ""} />
          </button>
        </div>

        {status === "error" && (
          <div className="p-3 text-xs text-red-600">{error}</div>
        )}

        {hitlDisabled && (
          <div className="m-3 p-3 rounded-md border border-amber-300 bg-amber-50 text-amber-900 text-xs">
            <div className="font-medium mb-1">HITL approvals are disabled</div>
            <div className="text-amber-800">
              Set <code className="font-mono bg-amber-100 px-1 rounded">ENABLE_HITL=true</code> in{" "}
              <code className="font-mono bg-amber-100 px-1 rounded">agent/.env</code> and restart the API
              server. Without this, skills with HITL checkpoints cannot pause for review.
            </div>
          </div>
        )}

        {status === "ready" && !hitlDisabled && items.length === 0 && (
          <div className="p-6 text-sm text-muted-foreground text-center">No pending approvals.</div>
        )}

        <ul className="flex-1 overflow-y-auto">
          {items.map((a) => {
            const active = a.approval_id === selectedId;
            return (
              <li key={a.approval_id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(a.approval_id)}
                  className={`w-full text-left p-3 border-b text-sm hover:bg-muted/50 ${
                    active ? "bg-muted" : ""
                  }`}
                >
                  <div className="font-medium truncate">{a.skill_name}</div>
                  <div className="text-xs text-muted-foreground truncate">{a.checkpoint_id}</div>
                  <div className="text-xs text-muted-foreground flex gap-2 mt-1">
                    <span>{ageString(a.created_at)}</span>
                    {ttlString(a) && (
                      <span className="flex items-center gap-1">
                        <Clock size={10} /> {ttlString(a)}
                      </span>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Right pane — detail */}
      <div className="flex-1 overflow-y-auto">
        {!selected ? (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            Select an approval to review.
          </div>
        ) : (
          <div className="p-6 max-w-3xl">
            <div className="mb-2 text-xs text-muted-foreground">
              {selected.skill_name} · attempt {selected.attempt_id}
              {selected.requires_role && (
                <span className="ml-2 px-2 py-0.5 rounded bg-amber-100 text-amber-900">
                  role: {selected.requires_role}
                </span>
              )}
            </div>
            <h2 className="text-lg font-semibold mb-1">{selected.checkpoint_id}</h2>
            {selected.prompt && (
              <p className="text-sm text-muted-foreground mb-4">{selected.prompt}</p>
            )}

            <section className="mb-4">
              <h3 className="text-sm font-medium mb-2">Payload</h3>
              <pre className="text-xs bg-muted rounded p-3 overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(selected.payload, null, 2)}
              </pre>
            </section>

            {selected.allowed_edits.length > 0 && selected.decision_types.includes("modify") && (
              <section className="mb-4">
                <h3 className="text-sm font-medium mb-2">Edits (JSON — must be a subset of {selected.allowed_edits.join(", ")})</h3>
                <textarea
                  value={editsJson}
                  onChange={(e) => setEditsJson(e.target.value)}
                  className="w-full h-40 rounded-md border bg-background p-2 text-xs font-mono outline-none focus:border-primary"
                />
              </section>
            )}

            <section className="mb-4">
              <h3 className="text-sm font-medium mb-2">Reason (optional)</h3>
              <input
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="why this decision"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </section>

            {selected.decision_types.includes("defer") && (
              <section className="mb-4">
                <h3 className="text-sm font-medium mb-2">Defer condition (defer only)</h3>
                <input
                  value={deferCondition}
                  onChange={(e) => setDeferCondition(e.target.value)}
                  placeholder="revisit when …"
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                />
              </section>
            )}

            <div className="flex gap-2 flex-wrap">
              {selected.decision_types.includes("approve") && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => submit("approve")}
                  className="px-3 py-2 rounded-md bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-60 flex items-center gap-2"
                >
                  <Check size={14} /> Approve
                </button>
              )}
              {selected.decision_types.includes("modify") && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => submit("modify")}
                  className="px-3 py-2 rounded-md bg-amber-600 text-white text-sm font-medium hover:bg-amber-700 disabled:opacity-60 flex items-center gap-2"
                >
                  <Pencil size={14} /> Approve with edits
                </button>
              )}
              {selected.decision_types.includes("defer") && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => submit("defer")}
                  className="px-3 py-2 rounded-md border text-sm font-medium hover:bg-muted disabled:opacity-60 flex items-center gap-2"
                >
                  <Clock size={14} /> Defer
                </button>
              )}
              {selected.decision_types.includes("reject") && (
                <button
                  type="button"
                  disabled={submitting}
                  onClick={() => submit("reject")}
                  className="px-3 py-2 rounded-md bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-60 flex items-center gap-2"
                >
                  <X size={14} /> Reject
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
