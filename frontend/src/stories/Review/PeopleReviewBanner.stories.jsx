import { PeopleReviewBanner, C, cardStyle } from "../../pages/ConversationDetail";
import { fn } from "storybook/test";
import { contacts, peopleAllGreen, peopleMixed, peopleUnresolved } from "../review-fixtures";

/**
 * PeopleReviewBanner calls api.conversationPeople() internally.
 * To isolate it for stories, we render a static presentation wrapper
 * that mirrors the banner's render output without the API call.
 */
function PeopleReviewBannerStatic({ people, allGreen, expanded: initExpanded = false }) {
  const nonSelf = people.filter(p => !p.is_self);
  const yellowPeople = nonSelf.filter(p => p.status === "auto_resolved");
  const redPeople = nonSelf.filter(p => p.status === "provisional" || p.status === "unresolved");
  const greenPeople = nonSelf.filter(p => p.status === "confirmed");
  const skippedPeople = nonSelf.filter(p => p.status === "skipped");
  const selfPeople = people.filter(p => p.is_self);

  const statusDot = (status) => {
    const colors = { confirmed: C.success, auto_resolved: C.warning, provisional: C.danger, unresolved: C.danger, skipped: C.textDim };
    return <span style={{ color: colors[status] || C.textDim, fontSize: 10 }}>{"\u25CF"}</span>;
  };

  if (allGreen && !initExpanded) {
    return (
      <div style={{ ...cardStyle, marginBottom: 16, cursor: "pointer", borderColor: C.success + "44", background: C.success + "08" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 14 }}>{"\uD83D\uDC65"}</span>
          <span style={{ color: C.success, fontWeight: 600, fontSize: 13 }}>
            {"\u2705"} All {nonSelf.length} people confirmed
          </span>
          <span style={{ color: C.textDim, fontSize: 11, marginLeft: "auto" }}>click to expand</span>
        </div>
      </div>
    );
  }

  const renderPerson = (person) => (
    <div key={person.original_name} style={{
      display: "flex", alignItems: "center", gap: 8, padding: "8px 0",
      borderBottom: `1px solid ${C.border}`,
    }}>
      {statusDot(person.status)}
      <span style={{ fontSize: 13, color: C.text, flex: 1 }}>
        {person.canonical_name || person.original_name}
        {person.is_self && <span style={{ fontSize: 10, color: C.textDim, marginLeft: 6 }}>(you)</span>}
      </span>
      <span style={{ fontSize: 11, padding: "2px 6px", borderRadius: 3,
        background: person.status === "confirmed" ? C.success + "22" :
          person.status === "auto_resolved" ? C.warning + "22" :
          person.status === "skipped" ? C.textDim + "22" : C.danger + "22",
        color: person.status === "confirmed" ? C.success :
          person.status === "auto_resolved" ? C.warning :
          person.status === "skipped" ? C.textDim : C.danger,
      }}>
        {person.status.replace("_", " ")}
      </span>
      {!person.is_self && person.status !== "confirmed" && person.status !== "skipped" && (
        <div style={{ display: "flex", gap: 4 }}>
          {person.status === "auto_resolved" && (
            <button style={{ fontSize: 11, padding: "2px 8px", borderRadius: 3, border: `1px solid ${C.success}44`, background: "transparent", color: C.success, cursor: "pointer" }}>
              Confirm
            </button>
          )}
          <button style={{ fontSize: 11, padding: "2px 8px", borderRadius: 3, border: `1px solid ${C.accent}44`, background: "transparent", color: C.accent, cursor: "pointer" }}>
            Link
          </button>
          {person.is_provisional && (
            <button style={{ fontSize: 11, padding: "2px 8px", borderRadius: 3, border: `1px solid ${C.warning}44`, background: "transparent", color: C.warning, cursor: "pointer" }}>
              Create
            </button>
          )}
          <button style={{ fontSize: 11, padding: "2px 8px", borderRadius: 3, border: `1px solid ${C.border}`, background: "transparent", color: C.textDim, cursor: "pointer" }}>
            Skip
          </button>
        </div>
      )}
    </div>
  );

  return (
    <div style={{ ...cardStyle, marginBottom: 16, borderColor: redPeople.length > 0 ? C.warning + "44" : C.border }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <span style={{ fontSize: 14 }}>{"\uD83D\uDC65"}</span>
        <span style={{ fontWeight: 600, fontSize: 14, color: C.text }}>People in this conversation</span>
        {redPeople.length > 0 && (
          <span style={{ fontSize: 12, padding: "1px 8px", borderRadius: 3, background: C.danger + "22", color: C.danger }}>
            {redPeople.length} unresolved
          </span>
        )}
        {yellowPeople.length > 0 && (
          <span style={{ fontSize: 12, padding: "1px 8px", borderRadius: 3, background: C.warning + "22", color: C.warning }}>
            {yellowPeople.length} auto-resolved
          </span>
        )}
      </div>
      {redPeople.map(renderPerson)}
      {yellowPeople.map(renderPerson)}
      {greenPeople.map(renderPerson)}
      {skippedPeople.map(renderPerson)}
      {selfPeople.map(renderPerson)}
    </div>
  );
}

export default {
  title: "Review/PeopleReviewBanner",
  component: PeopleReviewBannerStatic,
  parameters: { layout: "padded" },
};

export const AllGreenCollapsed = {
  name: "All green (collapsed)",
  args: { people: peopleAllGreen, allGreen: true },
};

export const AllGreenExpanded = {
  name: "All green (expanded)",
  args: { people: peopleAllGreen, allGreen: true, expanded: true },
};

export const MixedStatus = {
  name: "Mixed status (expanded)",
  args: { people: peopleMixed, allGreen: false },
};

export const HeavyUnresolved = {
  name: "Unresolved/provisional heavy",
  args: { people: peopleUnresolved, allGreen: false },
};

export const WithSelfPerson = {
  name: "Self person visible",
  args: { people: peopleMixed, allGreen: false },
};

export const SinglePerson = {
  name: "Single non-self person",
  args: {
    people: [
      { original_name: "Stephen Andrews", canonical_name: "Stephen Andrews", entity_id: "c-006", status: "confirmed", is_self: true, is_provisional: false },
      { original_name: "Unknown Caller", canonical_name: null, entity_id: null, status: "unresolved", is_self: false, is_provisional: false },
    ],
    allGreen: false,
  },
};
