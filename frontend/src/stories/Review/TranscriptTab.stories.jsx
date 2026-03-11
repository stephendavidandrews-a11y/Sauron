import { fn } from "storybook/test";
import { TranscriptTab } from "../../pages/ConversationDetail";
import { contacts, transcript, transcriptEmpty, makeSegment } from "../review-fixtures";

export default {
  title: "Review/TranscriptTab",
  component: TranscriptTab,
  parameters: { layout: "padded" },
  args: {
    conversationId: "conv-001",
    contacts,
  },
};

export const Normal = {
  args: { transcript },
};

export const MultipleSpeakers = {
  name: "Multiple speakers (4 distinct)",
  args: { transcript },
};

export const UnknownSpeaker = {
  name: "Unknown speaker present",
  args: {
    transcript: [
      ...transcript.slice(0, 3),
      makeSegment({
        id: 50, speaker_label: "SPEAKER_04", speaker_name: null, speaker_id: null,
        voice_sample_count: 0, start_time: 33.0, end_time: 40.0,
        text: "I have a different perspective on that. The enforcement timeline is more compressed than people realize.",
      }),
      makeSegment({
        id: 51, speaker_label: "SPEAKER_04", speaker_name: null, speaker_id: null,
        voice_sample_count: 0, start_time: 40.5, end_time: 48.0,
        text: "We should factor in the election cycle before committing to any deadlines.",
      }),
      ...transcript.slice(3),
    ],
  },
};

export const CorrectedSegments = {
  name: "Corrected transcript indicators",
  args: {
    transcript: transcript.map((seg, i) =>
      i === 8 ? seg : // seg 9 is already user_corrected: 1
      i === 2 ? { ...seg, user_corrected: 1 } :
      i === 4 ? { ...seg, user_corrected: 1 } :
      seg
    ),
  },
};

export const VoiceEnrolled = {
  name: "Voice enrolled vs not enrolled",
  args: {
    transcript: [
      makeSegment({ id: 60, speaker_name: "Stephen Andrews", speaker_id: "c-006", voice_sample_count: 12, text: "I have a full voiceprint enrolled." }),
      makeSegment({ id: 61, speaker_label: "SPEAKER_01", speaker_name: "Sarah Chen", speaker_id: "c-001", voice_sample_count: 8, start_time: 5.0, text: "I also have a voiceprint." }),
      makeSegment({ id: 62, speaker_label: "SPEAKER_02", speaker_name: "Mark Weber", speaker_id: "c-002", voice_sample_count: 0, start_time: 10.0, text: "I am identified but have no voice samples." }),
      makeSegment({ id: 63, speaker_label: "SPEAKER_03", speaker_name: null, speaker_id: null, voice_sample_count: 0, start_time: 15.0, text: "I am completely unknown." }),
    ],
  },
};

export const Empty = {
  args: { transcript: transcriptEmpty },
};

export const LongTranscript = {
  name: "Long transcript (20 segments)",
  args: {
    transcript: Array.from({ length: 20 }, (_, i) =>
      makeSegment({
        id: 70 + i,
        speaker_label: `SPEAKER_0${i % 3}`,
        speaker_name: ["Stephen Andrews", "Sarah Chen", "Mark Weber"][i % 3],
        speaker_id: ["c-006", "c-001", "c-002"][i % 3],
        voice_sample_count: [12, 8, 0][i % 3],
        start_time: i * 10,
        end_time: i * 10 + 8,
        text: `Transcript segment ${i + 1}: This is a sample of ongoing discussion about regulatory policy and its implications for market participants.`,
        user_corrected: i === 5 || i === 12 ? 1 : 0,
      })
    ),
  },
};
