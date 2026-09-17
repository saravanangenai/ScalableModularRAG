import { Alert, Badge, Button, FileInput, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "react-oidc-context";

import { listDocuments, uploadDocument } from "../api/documents";
import { getJob, TERMINAL_JOB_STATUSES } from "../api/jobs";
import { JobStatusBadge } from "../components/JobStatusBadge";

export function DocumentsTab({ workspaceId }: { workspaceId: string }) {
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const {
    data: documents,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["documents", workspaceId],
    queryFn: () => listDocuments(accessToken, workspaceId),
    enabled: Boolean(accessToken),
  });

  const { data: activeJob } = useQuery({
    queryKey: ["job", workspaceId, activeJobId],
    queryFn: () => getJob(accessToken, workspaceId, activeJobId!),
    enabled: Boolean(accessToken) && Boolean(activeJobId),
    refetchInterval: (query) =>
      query.state.data && TERMINAL_JOB_STATUSES.has(query.state.data.status) ? false : 2000,
  });

  // Once the active job reaches a terminal state, refresh the document list so its
  // own `status` field reflects the outcome too.
  if (activeJob && TERMINAL_JOB_STATUSES.has(activeJob.status)) {
    void queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const result = await uploadDocument(accessToken, workspaceId, file);
      if (result.status === "queued") {
        setActiveJobId(result.job_id);
      }
      setFile(null);
      await queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : String(error));
    } finally {
      setUploading(false);
    }
  }

  return (
    <Stack>
      <Group align="flex-end">
        <FileInput
          label="Upload a PDF"
          placeholder="Choose file"
          accept="application/pdf"
          value={file}
          onChange={setFile}
          flex={1}
        />
        <Button onClick={() => void handleUpload()} loading={uploading} disabled={!file}>
          Upload
        </Button>
      </Group>

      {uploadError && <Alert color="red">Upload failed: {uploadError}</Alert>}
      {activeJob && !TERMINAL_JOB_STATUSES.has(activeJob.status) && (
        <Group>
          <Text size="sm">Ingesting:</Text>
          <JobStatusBadge job={activeJob} />
        </Group>
      )}

      {isLoading && <Loader />}
      {isError && <Alert color="red">Failed to load documents.</Alert>}
      {documents && documents.length === 0 && (
        <Text c="dimmed">No documents yet — upload one above.</Text>
      )}
      {documents && documents.length > 0 && (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Filename</Table.Th>
              <Table.Th>Status</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {documents.map((doc) => (
              <Table.Tr key={doc.id}>
                <Table.Td>{doc.filename}</Table.Td>
                <Table.Td>
                  <Badge color={doc.status === "ready" ? "green" : doc.status === "failed" ? "red" : "blue"} variant="light">
                    {doc.status}
                  </Badge>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
