import { Stack, Tabs, Title } from "@mantine/core";
import { useParams } from "react-router-dom";

import { DocumentsTab } from "./DocumentsTab";
import { MembersTab } from "./MembersTab";
import { SearchTab } from "./SearchTab";

export function WorkspacePage() {
  const { workspaceId } = useParams<{ workspaceId: string }>();

  if (!workspaceId) return null;

  return (
    <Stack p="lg" maw={900} mx="auto">
      <Title order={2}>Workspace</Title>
      <Tabs defaultValue="documents">
        <Tabs.List>
          <Tabs.Tab value="documents">Documents</Tabs.Tab>
          <Tabs.Tab value="members">Members</Tabs.Tab>
          <Tabs.Tab value="search">Search</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="documents" pt="md">
          <DocumentsTab workspaceId={workspaceId} />
        </Tabs.Panel>
        <Tabs.Panel value="members" pt="md">
          <MembersTab workspaceId={workspaceId} />
        </Tabs.Panel>
        <Tabs.Panel value="search" pt="md">
          <SearchTab workspaceId={workspaceId} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
