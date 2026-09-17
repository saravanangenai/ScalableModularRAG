import { Badge, Card, Group, Text } from "@mantine/core";

import type { SearchResult } from "../api/search";

const LABEL_BY_CONTENT_TYPE: Record<string, string> = {
  page_text_plus_ocr: "Text",
  table: "Table",
  image: "Image",
};

/** Content-type-aware rendering (specs/071-search-frontend/plan.md): a text snippet, a
 * table (already markdown-formatted server-side, per specs/051-table-intelligence), or an
 * image's caption/metadata (already embedded in `text`, per specs/050-vision-captioning —
 * no image-byte-serving endpoint in this increment, tracked as a follow-up). */
export function ResultCard({ result }: { result: SearchResult }) {
  const label = result.content_type ? LABEL_BY_CONTENT_TYPE[result.content_type] : "Unknown";
  const isStructured = result.content_type === "table" || result.content_type === "image";

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Badge variant="light">{label}</Badge>
          <Text size="sm" c="dimmed">
            {result.filename} · page {result.page_number}
          </Text>
        </Group>
        <Text size="sm" c="dimmed">
          score {result.score.toFixed(3)}
        </Text>
      </Group>
      {isStructured ? (
        <Text component="pre" size="sm" style={{ whiteSpace: "pre-wrap" }}>
          {result.text}
        </Text>
      ) : (
        <Text size="sm" lineClamp={6}>
          {result.text}
        </Text>
      )}
    </Card>
  );
}
