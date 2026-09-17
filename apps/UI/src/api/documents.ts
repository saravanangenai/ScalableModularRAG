import { apiFetch } from "./client";

export interface Document {
  id: string;
  workspace_id: string;
  filename: string;
  content_hash_current: string;
  status: string;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface UploadAccepted {
  document_id: string;
  document_version_id: string;
  job_id: string;
  status: "queued";
}

export interface UploadUnchanged {
  document_id: string;
  document_version_id: string;
  status: "unchanged";
}

export function listDocuments(
  accessToken: string | undefined,
  workspaceId: string,
): Promise<Document[]> {
  return apiFetch<Document[]>(`/workspaces/${workspaceId}/documents`, accessToken);
}

export function uploadDocument(
  accessToken: string | undefined,
  workspaceId: string,
  file: File,
): Promise<UploadAccepted | UploadUnchanged> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<UploadAccepted | UploadUnchanged>(
    `/workspaces/${workspaceId}/documents`,
    accessToken,
    { method: "POST", body: formData },
  );
}
