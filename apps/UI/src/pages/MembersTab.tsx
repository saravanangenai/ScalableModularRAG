import { Alert, Button, Group, Loader, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "react-oidc-context";

import { addMember, listMembers, removeMember, updateMemberRole } from "../api/members";

const ROLES = ["owner", "editor", "viewer"];

export function MembersTab({ workspaceId }: { workspaceId: string }) {
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const queryClient = useQueryClient();
  const [newUserId, setNewUserId] = useState("");
  const [newRole, setNewRole] = useState<string | null>("viewer");
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: members,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["members", workspaceId],
    queryFn: () => listMembers(accessToken, workspaceId),
    enabled: Boolean(accessToken),
  });

  const myEmail = auth.user?.profile.email;
  const isOwner = members?.some((m) => m.email === myEmail && m.role === "owner") ?? false;

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["members", workspaceId] });
  }

  async function handleAdd() {
    if (!newUserId.trim() || !newRole) return;
    setActionError(null);
    try {
      await addMember(accessToken, workspaceId, newUserId.trim(), newRole);
      setNewUserId("");
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleRoleChange(userId: string, role: string) {
    setActionError(null);
    try {
      await updateMemberRole(accessToken, workspaceId, userId, role);
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function handleRemove(userId: string) {
    setActionError(null);
    try {
      await removeMember(accessToken, workspaceId, userId);
      await refresh();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <Stack>
      {isOwner && (
        <Group align="flex-end">
          <TextInput
            label="User ID"
            description="The member's user ID (no lookup-by-email yet — a known limitation, see specs/071-search-frontend)"
            placeholder="uuid"
            value={newUserId}
            onChange={(event) => setNewUserId(event.currentTarget.value)}
            flex={1}
          />
          <Select label="Role" data={ROLES} value={newRole} onChange={setNewRole} />
          <Button onClick={() => void handleAdd()} disabled={!newUserId.trim()}>
            Add
          </Button>
        </Group>
      )}

      {actionError && <Alert color="red">{actionError}</Alert>}
      {isLoading && <Loader />}
      {isError && <Alert color="red">Failed to load members.</Alert>}

      {members && (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Email</Table.Th>
              <Table.Th>Role</Table.Th>
              {isOwner && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {members.map((member) => (
              <Table.Tr key={member.user_id}>
                <Table.Td>{member.display_name}</Table.Td>
                <Table.Td>{member.email}</Table.Td>
                <Table.Td>
                  {isOwner ? (
                    <Select
                      data={ROLES}
                      value={member.role}
                      onChange={(role) => role && void handleRoleChange(member.user_id, role)}
                    />
                  ) : (
                    <Text>{member.role}</Text>
                  )}
                </Table.Td>
                {isOwner && (
                  <Table.Td>
                    <Button
                      color="red"
                      variant="subtle"
                      onClick={() => void handleRemove(member.user_id)}
                    >
                      Remove
                    </Button>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
