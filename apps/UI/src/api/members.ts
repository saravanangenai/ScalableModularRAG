import { apiFetch } from "./client";

export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  role: string;
}

export function listMembers(
  accessToken: string | undefined,
  workspaceId: string,
): Promise<Member[]> {
  return apiFetch<Member[]>(`/workspaces/${workspaceId}/members`, accessToken);
}

export function addMember(
  accessToken: string | undefined,
  workspaceId: string,
  userId: string,
  role: string,
): Promise<void> {
  return apiFetch<void>(`/workspaces/${workspaceId}/members`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, role }),
  });
}

export function updateMemberRole(
  accessToken: string | undefined,
  workspaceId: string,
  userId: string,
  role: string,
): Promise<void> {
  return apiFetch<void>(`/workspaces/${workspaceId}/members/${userId}`, accessToken, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
}

export function removeMember(
  accessToken: string | undefined,
  workspaceId: string,
  userId: string,
): Promise<void> {
  return apiFetch<void>(`/workspaces/${workspaceId}/members/${userId}`, accessToken, {
    method: "DELETE",
  });
}
