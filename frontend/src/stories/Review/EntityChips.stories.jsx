import { fn } from "storybook/test";
import { EntityChips } from "../../pages/ConversationDetail";
import {
  contacts,
  claimFact,
  claimNoEntities,
  claimRelationship,
  makeClaim,
} from "../review-fixtures";

// EntityChips calls api.searchContacts internally; in stories it falls
// back to filtering the contacts prop from its catch block.

export default {
  title: "Review/EntityChips",
  component: EntityChips,
  parameters: { layout: "padded" },
  args: {
    contacts,
    onLink: fn(),
    onRemoveEntity: fn(),
    conversationId: "conv-001",
  },
};

export const WithEntities = {
  name: "With entities",
  args: {
    claim: claimFact,
  },
};

export const NoEntities = {
  name: "No entities (empty array)",
  args: {
    claim: claimNoEntities,
  },
};

export const SubjectNameOnly = {
  name: "Subject name only (no entities, has subject_name)",
  args: {
    claim: makeClaim({
      id: 401,
      entities: [],
      subject_name: "David Kim",
      subject_entity_id: null,
      linked_entity_name: "David Kim",
    }),
  },
};

export const MultipleEntities = {
  name: "Multiple entities with different roles",
  args: {
    claim: claimRelationship,
  },
};

export const UserLinked = {
  name: "Entity with link_source user",
  args: {
    claim: makeClaim({
      id: 402,
      entities: [
        {
          id: "el-001",
          claim_id: 402,
          entity_id: "c-002",
          entity_name: "Mark Weber",
          role: "subject",
          link_source: "user",
          relationship_label: null,
        },
      ],
    }),
  },
};
