import { EvidenceHit } from "../../pages/Search";
import { fn } from "storybook/test";

export default {
  title: "Search/EvidenceHit",
  component: EvidenceHit,
  parameters: { layout: "padded" },
  args: {
    navigate: fn(),
    logClick: fn(),
    conversationId: "conv-123",
  },
};

export const ClaimHit = {
  args: {
    hit: {
      source_type: "claim",
      claim_type: "fact",
      claim_text: "The CFTC plans to finalize position limits by Q3 2026.",
      speaker_name: "Sarah Chen",
      subject_name: "CFTC",
      confidence: 0.92,
      similarity: 0.87,
      evidence_quote: "Sarah mentioned that position limits would be finalized by end of Q3.",
      modality: "stated",
      source_id: "claim-1",
    },
  },
};

export const EpisodeHit = {
  args: {
    hit: {
      source_type: "episode",
      episode_type: "meeting",
      title: "Derivatives Working Group Sync",
      summary: "Discussion about upcoming regulatory changes, position limits timeline, and cross-border coordination with EU counterparts on margin requirements.",
      similarity: 0.79,
      source_id: "episode-1",
    },
  },
};

export const CommitmentHit = {
  args: {
    hit: {
      source_type: "claim",
      claim_type: "commitment",
      claim_text: "Will send the updated compliance framework by Friday.",
      speaker_name: "John Smith",
      subject_name: "Sarah Chen",
      confidence: 0.85,
      similarity: 0.73,
      evidence_quote: "I will get that compliance framework over to you by end of day Friday.",
      modality: "stated",
      source_id: "claim-2",
    },
  },
};

export const LowConfidence = {
  args: {
    hit: {
      source_type: "claim",
      claim_type: "position",
      claim_text: "Might support expanding swap dealer definitions.",
      speaker_name: "Mark Weber",
      confidence: 0.45,
      similarity: 0.52,
      modality: "hedged",
      source_id: "claim-3",
    },
  },
};

export const GenericHit = {
  name: "Other source type",
  args: {
    hit: {
      source_type: "extraction_summary",
      text: "Summary of key takeaways from the Q1 regulatory review meeting covering enforcement priorities and rulemaking timelines.",
      similarity: 0.68,
      source_id: "extract-1",
    },
  },
};
