import { Alert, Button, Card, Group, Loader, Stack, Text, TextInput, Title } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "react-oidc-context";
import { Link } from "react-router-dom";

import { createWorkspace, listWorkspaces } from "../api/workspaces";

export function WorkspaceListPage() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const accessToken = auth.user?.access_token;

  const {
    data: workspaces,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => listWorkspaces(accessToken),
    enabled: Boolean(accessToken),
  });

  async function handleCreate() {
    if (!newWorkspaceName.trim()) return;
    setCreateError(null);
    try {
      await createWorkspace(accessToken, newWorkspaceName.trim());
      setNewWorkspaceName("");
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <Stack p="lg" maw={640} mx="auto">
      <Group justify="space-between">
        <Title order={2}>Workspaces</Title>
        <Button variant="subtle" onClick={() => void auth.signoutRedirect()}>
          Sign out
        </Button>
      </Group>

      <Group>
        <TextInput
          placeholder="New workspace name"
          value={newWorkspaceName}
          onChange={(event) => setNewWorkspaceName(event.currentTarget.value)}
          flex={1}
        />
        <Button onClick={() => void handleCreate()} disabled={!newWorkspaceName.trim()}>
          Create
        </Button>
      </Group>

      {createError && <Alert color="red">{createError}</Alert>}
      {isLoading && <Loader />}
      {isError && <Alert color="red">{error.message}</Alert>}
      {workspaces && workspaces.length === 0 && (
        <Text c="dimmed">No workspaces yet — create one above to get started.</Text>
      )}
      {workspaces?.map((workspace) => (
        <Card key={workspace.id} withBorder component={Link} to={`/workspaces/${workspace.id}`}>
          <Text fw={500}>{workspace.name}</Text>
        </Card>
      ))}
    </Stack>
  );
}
