import { Card, Empty, StatusChip, ProcessingChip, ShowMoreButton } from "../../pages/Today";

export default {
  title: "Today/Card",
  component: Card,
  parameters: { layout: "padded" },
};

export const Default = {
  args: {
    title: "Active claims",
    children: (
      <p className="text-sm text-text-muted">
        Some content goes inside the card body.
      </p>
    ),
  },
};

export const WithBadge = {
  args: {
    title: "Needs review",
    badge: 12,
    children: (
      <p className="text-sm text-text-muted">Card with a badge count.</p>
    ),
  },
};

export const WithAction = {
  args: {
    title: "Open commitments",
    badge: 3,
    action: (
      <button className="text-xs text-accent hover:text-accent-hover transition-colors cursor-pointer bg-transparent border-0">
        View all &rarr;
      </button>
    ),
    children: (
      <p className="text-sm text-text-muted">Card with action button.</p>
    ),
  },
};

export const EmptyState = {
  render: () => (
    <Card title="Empty section">
      <Empty message="Nothing to show right now." />
    </Card>
  ),
};

export const StatusChips = {
  name: "Status chips (all variants)",
  render: () => (
    <Card title="Status chips">
      <div className="flex flex-wrap gap-2">
        {["active", "refined", "provisional", "qualified", "time_bounded", "contested", "stale", "superseded", "under_review"].map(s => (
          <StatusChip key={s} status={s} />
        ))}
      </div>
    </Card>
  ),
};

export const ProcessingChips = {
  name: "Processing chips (all variants)",
  render: () => (
    <Card title="Processing chips">
      <div className="flex flex-wrap gap-2">
        {["completed", "processing", "pending", "error", "transcribing", "awaiting_speaker_review", "triaging", "extracting", "awaiting_claim_review"].map(s => (
          <ProcessingChip key={s} status={s} />
        ))}
      </div>
    </Card>
  ),
};

export const ShowMoreButtons = {
  name: "Show more / less button",
  render: () => (
    <Card title="Expandable list">
      <p className="text-sm text-text-muted mb-2">Items shown here...</p>
      <ShowMoreButton expanded={false} count={8} onClick={() => {}} />
    </Card>
  ),
};
