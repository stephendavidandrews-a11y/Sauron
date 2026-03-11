import { fn } from "storybook/test";
import { PeopleReviewBanner } from "../../pages/ConversationDetail";
import {
  contacts,
  peopleAllGreen,
  peopleMixed,
  peopleUnresolved,
} from "../review-fixtures";

const noopAsync = fn().mockImplementation(() => Promise.resolve());

const serviceProps = {
  loadPeopleFn: noopAsync,
  confirmPersonFn: noopAsync,
  skipPersonFn: noopAsync,
  unskipPersonFn: noopAsync,
  dismissPersonFn: noopAsync,
  searchContactsFn: fn().mockImplementation(() => Promise.resolve([])),
  linkProvisionalFn: noopAsync,
  dismissProvisionalFn: noopAsync,
  confirmProvisionalFn: noopAsync,
};

const base = {
  conversationId: "conv-001",
  contacts,
  onResolved: fn(),
  onPeopleLoaded: fn(),
  ...serviceProps,
};

export default {
  title: "Review/PeopleReviewBanner",
  component: PeopleReviewBanner,
  parameters: { layout: "padded" },
};

export const AllGreenCollapsed = {
  name: "All green — collapsed",
  args: { ...base, initialPeople: peopleAllGreen },
};

export const AllGreenExpanded = {
  name: "All green — expanded (click to open)",
  args: { ...base, initialPeople: peopleAllGreen },
};

export const MixedStatus = {
  name: "Mixed: confirmed + auto-resolved + provisional + skipped",
  args: { ...base, initialPeople: peopleMixed },
};

export const HeavyUnresolved = {
  name: "Heavy unresolved — multiple provisionals",
  args: { ...base, initialPeople: peopleUnresolved },
};

export const WithSelfPerson = {
  name: "Self person shown at bottom",
  args: {
    ...base,
    initialPeople: [
      ...peopleMixed.filter((p) => !p.is_self),
      {
        original_name: "Stephen Andrews",
        canonical_name: "Stephen Andrews",
        entity_id: "c-006",
        status: "confirmed",
        is_self: true,
        is_provisional: false,
      },
    ],
  },
};

export const SinglePerson = {
  name: "Single non-self person",
  args: {
    ...base,
    initialPeople: [
      {
        original_name: "Sarah Chen",
        canonical_name: "Sarah Chen",
        entity_id: "c-001",
        status: "auto_resolved",
        is_self: false,
        is_provisional: false,
        claim_count: 3,
      },
    ],
  },
};
