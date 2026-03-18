import { fetchJSON } from './client';

export const pipelineApi = {
  pipelineStatus: () => fetchJSON('/pipeline/status'),
  pipelineIngest: (source = null) =>
    fetchJSON(`/pipeline/ingest${source ? `?source=${source}` : ''}`, { method: 'POST' }),
  pipelineProcess: (conversationId) =>
    fetchJSON(`/pipeline/process/${conversationId}`, { method: 'POST' }),
  pipelineProcessPending: () =>
    fetchJSON('/pipeline/process-pending', { method: 'POST' }),
  routingStatus: () => fetchJSON('/pipeline/routing-status'),
  confirmSpeakers: (conversationId) =>
    fetchJSON(`/pipeline/confirm-speakers/${conversationId}`, { method: 'POST' }),
  promoteTriage: (conversationId) =>
    fetchJSON(`/pipeline/promote-triage/${conversationId}`, { method: 'POST' }),
  archiveTriage: (conversationId) =>
    fetchJSON(`/pipeline/archive-triage/${conversationId}`, { method: 'POST' }),
  audioClipUrl: (conversationId, start, end) =>
    `/api/audio/${conversationId}/clip?start=${start}&end=${end}`,
  speakerSampleUrl: (conversationId, label) =>
    `/api/audio/${conversationId}/speaker-sample/${label}`,
  diagnosticsStatus: () => fetchJSON('/diagnostics/status'),
  diagnosticsPipeline: () => fetchJSON('/diagnostics/pipeline'),
  diagnosticsRouting: () => fetchJSON('/diagnostics/routing'),
};
