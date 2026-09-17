import { apiFetch } from "./client";

export interface Workspace {
  id: string;
  name: string;
  created_at: string;
}

export function listWorkspaces(accessToken: string | undefined): Promise<Workspace[]> {
  return apiFetch<Workspace[]>("/workspaces", accessToken);
}

export function createWorkspace(
  accessToken: string | undefined,
  name: string,
): Promise<Workspace> {
  return apiFetch<Workspace>("/workspaces", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
