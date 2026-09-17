import { Badge, Tooltip } from "@mantine/core";

import type { Job } from "../api/jobs";

const COLOR_BY_STATUS: Record<Job["status"], string> = {
  queued: "gray",
  parsing: "blue",
  chunking: "blue",
  embedding: "blue",
  indexing: "blue",
  ready: "green",
  failed: "red",
};

export function JobStatusBadge({ job }: { job: Job }) {
  const badge = (
    <Badge color={COLOR_BY_STATUS[job.status]} variant="light">
      {job.status}
    </Badge>
  );

  if (job.status === "failed" && job.failure_reason) {
    return (
      <Tooltip label={`${job.failure_stage ?? "unknown stage"}: ${job.failure_reason}`}>
        {badge}
      </Tooltip>
    );
  }

  return badge;
}
