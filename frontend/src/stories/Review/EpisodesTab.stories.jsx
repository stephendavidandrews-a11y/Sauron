import { fn } from "storybook/test";
import { EpisodesTab } from "../../pages/ConversationDetail";
import {
  contacts, episodes, claimsByEpisode, orphanClaims, allClaims,
  makeClaim, makeEpisode, claimApproved, claimDismissed, claimDeferred,
} from "../review-fixtures";

const defaults = {
  conversationId: "conv-001",
  contacts,
  updateClaim: fn(),
  addClaimToState: fn(),
};

export default {
  title: "Review/EpisodesTab",
  component: EpisodesTab,
  parameters: { layout: "padded" },
  args: defaults,
};

export const Normal = {
  args: {
    episodes,
    claims: allClaims,
  },
};

export const SingleEpisode = {
  args: {
    episodes: [episodes[0]],
    claims: claimsByEpisode["ep-001"],
  },
};

export const WithOrphanClaims = {
  name: "Episodes + orphan claims",
  args: {
    episodes,
    claims: [...allClaims, ...orphanClaims],
  },
};

export const MixedReviewStates = {
  name: "Episode with mixed claim states",
  args: {
    episodes: [episodes[0]],
    claims: [
      claimApproved,
      claimDismissed,
      claimDeferred,
      makeClaim({ id: 130, episode_id: "ep-001", claim_text: "Still pending review." }),
    ],
  },
};

export const AllReviewed = {
  name: "Episode with all claims reviewed",
  args: {
    episodes: [episodes[0]],
    claims: [
      { ...claimApproved, episode_id: "ep-001" },
      makeClaim({ id: 131, episode_id: "ep-001", review_status: "user_confirmed" }),
      makeClaim({ id: 132, episode_id: "ep-001", review_status: "dismissed" }),
    ],
  },
};

export const Empty = {
  name: "No episodes or claims",
  args: {
    episodes: [],
    claims: [],
  },
};

export const OrphanClaimsOnly = {
  name: "Only orphan claims, no episodes",
  args: {
    episodes: [],
    claims: orphanClaims,
  },
};

export const ManyEpisodes = {
  name: "5 episodes with dense claims",
  args: {
    episodes: [
      ...episodes,
      makeEpisode({ id: "ep-004", title: "Cross-border coordination update", episode_type: "briefing", start_time: 725, end_time: 900 }),
      makeEpisode({ id: "ep-005", title: "Enforcement case review", episode_type: "discussion", start_time: 905, end_time: 1100 }),
    ],
    claims: [
      ...allClaims,
      makeClaim({ id: 140, episode_id: "ep-004", claim_text: "EU counterparts agree on margin harmonization timeline." }),
      makeClaim({ id: 141, episode_id: "ep-004", claim_type: "commitment", claim_text: "Will share the EMIR comparison doc next week.", firmness: "firm", direction: "owed_by_me", has_deadline: true }),
      makeClaim({ id: 142, episode_id: "ep-005", claim_text: "Three enforcement cases are pending final review.", confidence: 0.91 }),
      makeClaim({ id: 143, episode_id: "ep-005", claim_type: "position", claim_text: "Favors stronger penalties for repeat offenders.", confidence: 0.77 }),
    ],
  },
};
