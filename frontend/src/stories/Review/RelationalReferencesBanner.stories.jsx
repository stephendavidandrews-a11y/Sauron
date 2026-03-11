import { fn } from "storybook/test";
import { RelationalReferencesBanner } from "../../pages/ConversationDetail";
import { contacts, relationalClaims } from "../review-fixtures";

const noopAsync = fn().mockImplementation(() => Promise.resolve());

const serviceProps = {
  loadRelationalClaimsFn: noopAsync,
  searchContactsFn: fn().mockImplementation(() => Promise.resolve([])),
  linkEntityFn: fn().mockImplementation(() => Promise.resolve({})),
  saveRelationshipFn: noopAsync,
};

const base = {
  conversationId: "conv-001",
  contacts,
  onResolved: fn(),
  ...serviceProps,
};

export default {
  title: "Review/RelationalReferencesBanner",
  component: RelationalReferencesBanner,
  parameters: { layout: "padded" },
};

export const UnresolvedClaims = {
  name: "Unresolved relational claims",
  args: { ...base, initialClaims: relationalClaims },
};

export const WithSearchOpen = {
  name: "Two unresolved claims (click Link to open search)",
  args: { ...base, initialClaims: relationalClaims },
};

export const PluralClaim = {
  name: "Plural relational reference",
  args: {
    ...base,
    initialClaims: [
      {
        id: 202,
        claim_type: "fact",
        claim_text:
          "His colleagues all agree the timeline is too aggressive for full implementation.",
        subject_name: "his colleagues",
        subject_entity_id: null,
        is_relational: true,
        anchor_contact: { id: "c-002", canonical_name: "Mark Weber" },
        anchor_reference: "His",
        relational_term_raw: "colleagues",
        relational_term: "colleagues",
        entities: [],
        is_plural: true,
      },
    ],
  },
};

export const NoAnchor = {
  name: "Claim with no anchor set",
  args: {
    ...base,
    initialClaims: [
      {
        id: 203,
        claim_type: "fact",
        claim_text: "Their lawyer said the filing deadline won't hold.",
        subject_name: "their lawyer",
        subject_entity_id: null,
        is_relational: true,
        anchor_contact: null,
        anchor_reference: null,
        relational_term_raw: "lawyer",
        relational_term: "lawyer",
        entities: [],
        is_plural: false,
      },
    ],
  },
};

export const MixedClaims = {
  name: "Multiple claims — different relationship types",
  args: {
    ...base,
    initialClaims: [
      ...relationalClaims,
      {
        id: 204,
        claim_type: "commitment",
        claim_text: "Her assistant will coordinate the meeting logistics by Friday.",
        subject_name: "her assistant",
        subject_entity_id: null,
        is_relational: true,
        anchor_contact: { id: "c-001", canonical_name: "Sarah Chen" },
        anchor_reference: "Her",
        relational_term_raw: "assistant",
        relational_term: "assistant",
        entities: [],
        is_plural: false,
      },
    ],
  },
};

export const SingleClaim = {
  name: "Single unresolved claim",
  args: { ...base, initialClaims: [relationalClaims[0]] },
};

export const AllResolved = {
  name: "All resolved — banner hidden (returns null)",
  args: {
    ...base,
    initialClaims: [
      {
        id: 200,
        claim_type: "fact",
        claim_text: "My brother thinks the rulemaking will stall.",
        subject_name: "Mark Weber",
        subject_entity_id: "c-002",
        is_relational: true,
        anchor_contact: { id: "c-006", canonical_name: "Stephen Andrews" },
        anchor_reference: "My",
        relational_term_raw: "brother",
        relational_term: "brother",
        entities: [{ entity_id: "c-002", entity_name: "Mark Weber" }],
        is_plural: false,
      },
    ],
  },
};

export const EmptyClaims = {
  name: "No relational claims — banner hidden",
  args: { ...base, initialClaims: [] },
};
