import { fn } from "storybook/test";
import { Link } from "react-router-dom";
import {
  C, cardStyle, Chip,
} from "../../pages/ConversationDetail";
import {
  convoCompleted, convoAwaitingClaims, convoAwaitingSpeakers,
  convoReviewed, convoError, convoPending,
  linkedEntities, reviewStats, synthesis,
} from "../review-fixtures";

/**
 * ConversationDetail header extracted as a pure render function for stories.
 * This mirrors the header section of ConversationDetail without hooks/API calls.
 */
function ConversationHeader({
  convo, isReviewed, reviewing, reviewed, reviewStatsData,
  reprocessing, discarding, linkedEntities: linked, peopleStatus,
  onMarkReviewed, onReprocess, onDiscard, onShowReassign,
}) {
  return (
    <div className="py-4">
      <Link to="/review" className="text-accent text-sm no-underline">{"\u2190"} Back to review</Link>
      <div style={{ marginTop: 16, display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h1 className="text-xl font-bold text-text">
            {convo.manual_note || convo.title || convo.source || "Conversation"}
          </h1>
          <p className="text-sm text-text-dim mt-1">
            {convo.source || "unknown"} &middot; {(convo.captured_at || convo.created_at)?.slice(0, 10) || ""} &middot; {convo.processing_status || ""}
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {linked && Object.keys(linked).length > 0 && (
            <button onClick={onShowReassign}
              style={{ padding: "8px 16px", background: `${C.amber}22`, color: C.amber,
                border: `1px solid ${C.amber}44`, borderRadius: 6, fontSize: 13, cursor: "pointer", fontWeight: 500 }}>
              Reassign Speaker
            </button>
          )}
          {(convo.processing_status === "completed" || convo.processing_status === "awaiting_claim_review") && !isReviewed && (<>
            <button onClick={onDiscard} disabled={discarding}
              style={{ padding: "6px 14px", background: "transparent", color: "#ef4444",
                border: "1px solid #ef444444", borderRadius: 6, fontSize: 12, cursor: "pointer",
                opacity: discarding ? 0.7 : 1 }}>
              {discarding ? "Discarding..." : "\u2717 Discard"}
            </button>
            <button onClick={onMarkReviewed} disabled={reviewing}
              style={{ padding: "8px 16px", background: C.success, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer", opacity: reviewing ? 0.7 : 1 }}>
              {reviewing ? "Reviewing..." : (<>
                {"\u2713 Mark as Reviewed"}
                {peopleStatus && (peopleStatus.yellow + peopleStatus.red) > 0 && (
                  <span style={{ marginLeft: 8, fontSize: 11, opacity: 0.8 }}>
                    ({peopleStatus.yellow + peopleStatus.red} unconfirmed)
                  </span>
                )}
              </>)}
            </button>
          </>)}
          {isReviewed && (
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ padding: "8px 16px", background: `${C.success}22`, color: C.success, borderRadius: 6, fontSize: 13, fontWeight: 600 }}>
                {"\u2713"} Reviewed
              </span>
              {reviewStatsData && (
                <span style={{ fontSize: 12, color: C.textDim }}>
                  {reviewStatsData.approved} approved
                  {reviewStatsData.corrections > 0 && <> &middot; {reviewStatsData.corrections} corrected</>}
                  {reviewStatsData.dismissed > 0 && <> &middot; {reviewStatsData.dismissed} dismissed</>}
                  {reviewStatsData.beliefs_affected > 0 && (
                    <> &middot; <span style={{ color: C.warning }}>{reviewStatsData.beliefs_affected} beliefs affected</span></>
                  )}
                </span>
              )}
            </div>
          )}
          {convo.processing_status === "awaiting_speaker_review" && (
            <Link to={`/review/${convo.id}/speakers`}
              style={{ padding: "8px 16px", background: "#a78bfa", color: "#fff", border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer", textDecoration: "none", fontWeight: 500 }}>
              Confirm Speakers
            </Link>
          )}
          {(convo.processing_status === "error" || convo.processing_status === "pending") && (
            <button onClick={onReprocess} disabled={reprocessing}
              style={{ padding: "8px 16px", background: C.accent, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, cursor: "pointer", opacity: reprocessing ? 0.7 : 1 }}>
              {reprocessing ? "Processing..." : "Reprocess"}
            </button>
          )}
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "12px 0 20px" }}>
        {convo.duration_seconds && <Chip label="Duration" value={`${Math.round(convo.duration_seconds / 60)}m`} />}
        {convo.context_classification && <Chip label="Context" value={convo.context_classification} />}
      </div>
    </div>
  );
}

const headerActions = {
  onMarkReviewed: fn(),
  onReprocess: fn(),
  onDiscard: fn(),
  onShowReassign: fn(),
};

export default {
  title: "Review/ConversationHeader",
  component: ConversationHeader,
  parameters: { layout: "padded" },
  args: {
    ...headerActions,
    reviewing: false,
    reviewed: false,
    reprocessing: false,
    discarding: false,
    isReviewed: false,
    reviewStatsData: null,
    linkedEntities: null,
    peopleStatus: null,
  },
};

export const Completed = {
  args: { convo: convoCompleted },
};

export const AwaitingClaimReview = {
  args: { convo: convoAwaitingClaims },
};

export const AwaitingClaimReviewWithUnconfirmed = {
  name: "Awaiting claims + unconfirmed people",
  args: {
    convo: convoAwaitingClaims,
    peopleStatus: { yellow: 2, red: 1, total: 5 },
  },
};

export const Reviewed = {
  args: {
    convo: convoReviewed,
    isReviewed: true,
    reviewStatsData: reviewStats,
  },
};

export const ReviewingInProgress = {
  name: "Reviewing in progress",
  args: {
    convo: convoCompleted,
    reviewing: true,
  },
};

export const ErrorState = {
  name: "Error — Reprocess available",
  args: { convo: convoError },
};

export const PendingState = {
  name: "Pending — Reprocess available",
  args: { convo: convoPending },
};

export const AwaitingSpeakerReview = {
  name: "Awaiting speakers — Confirm link",
  args: { convo: convoAwaitingSpeakers },
};

export const WithReassignButton = {
  name: "Linked entities — Reassign Speaker visible",
  args: {
    convo: convoCompleted,
    linkedEntities,
  },
};

export const FullChrome = {
  name: "Full header with all metadata",
  args: {
    convo: {
      ...convoCompleted,
      duration_seconds: 2700,
      context_classification: "professional",
    },
    linkedEntities,
    peopleStatus: { yellow: 1, red: 0, total: 4 },
  },
};
