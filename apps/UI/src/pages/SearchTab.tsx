import { Alert, Button, Group, Loader, Stack, Text, TextInput } from "@mantine/core";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { useAuth } from "react-oidc-context";

import { search } from "../api/search";
import { ResultCard } from "../components/ResultCard";

export function SearchTab({ workspaceId }: { workspaceId: string }) {
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const [query, setQuery] = useState("");

  const mutation = useMutation({
    mutationFn: () => search(accessToken, workspaceId, query),
  });

  return (
    <Stack>
      <Group>
        <TextInput
          placeholder="Ask a question about this workspace's documents"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && query.trim()) mutation.mutate();
          }}
          flex={1}
        />
        <Button onClick={() => mutation.mutate()} loading={mutation.isPending} disabled={!query.trim()}>
          Search
        </Button>
      </Group>

      {mutation.isPending && <Loader />}
      {mutation.isError && <Alert color="red">{mutation.error.message}</Alert>}
      {mutation.isSuccess && mutation.data.results.length === 0 && (
        <Text c="dimmed">No results found for that query.</Text>
      )}
      {mutation.isSuccess &&
        mutation.data.results.map((result, index) => (
          <ResultCard key={`${result.document_id}-${index}`} result={result} />
        ))}
    </Stack>
  );
}
