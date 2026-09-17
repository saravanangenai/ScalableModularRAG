import { apiFetch } from "./client";

export interface Job {
  id: string;
  document_id: string;
  document_version_id: string;
  status: "queued" | "parsing" | "chunking" | "embedding" | "indexing" | "ready" | "failed";
  failure_stage: string | null;
  failure_reason: string | null;
  retry_count: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export const TERMINAL_JOB_STATUSES = new Set(["ready", "failed"]);

export function getJob(
  accessToken: string | undefined,
  workspaceId: string,
  jobId: string,
): Promise<Job> {
  return apiFetch<Job>(`/workspaces/${workspaceId}/jobs/${jobId}`, accessToken);
}
