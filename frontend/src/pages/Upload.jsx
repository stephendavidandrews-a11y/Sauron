import { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

const C = {
  bg: '#0a0f1a', card: '#111827', border: '#1e293b',
  text: '#e2e8f0', textDim: '#64748b', accent: '#3b82f6',
  success: '#22c55e', danger: '#ef4444', warning: '#f59e0b',
};

const ACCEPTED = '.m4a,.mp3,.wav,.flac,.ogg,.opus,.webm';

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

export default function Upload() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [source, setSource] = useState('iphone');
  const [note, setNote] = useState('');
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = useCallback((f) => {
    if (!f) return;
    const ext = f.name.split('.').pop().toLowerCase();
    const allowed = ['m4a', 'mp3', 'wav', 'flac', 'ogg', 'opus', 'webm'];
    if (!allowed.includes(ext)) {
      setError(`Unsupported format .${ext}. Use: ${allowed.join(', ')}`);
      return;
    }
    if (f.size > 200 * 1024 * 1024) {
      setError(`File too large (${formatBytes(f.size)}). Max: 200 MB`);
      return;
    }
    setFile(f);
    setError(null);
    setResult(null);
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setDragOver(false);
  }, []);

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('source', source);
      if (note.trim()) formData.append('note', note.trim());

      const xhr = new XMLHttpRequest();

      const responsePromise = new Promise((resolve, reject) => {
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            setProgress(Math.round((e.loaded / e.total) * 100));
          }
        });

        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(JSON.parse(xhr.responseText));
          } else {
            reject(new Error(`${xhr.status}: ${xhr.responseText}`));
          }
        });

        xhr.addEventListener('error', () => reject(new Error('Network error')));
        xhr.addEventListener('abort', () => reject(new Error('Upload cancelled')));
      });

      xhr.open('POST', '/api/pipeline/upload');
      xhr.send(formData);

      const data = await responsePromise;
      setResult(data);
      setFile(null);
      setNote('');
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (e) {
      setError(e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setNote('');
    setError(null);
    setResult(null);
    setProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div style={{ maxWidth: 600, margin: '0 auto', padding: '32px 16px' }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: C.text, marginBottom: 8 }}>
        Upload Recording
      </h1>
      <p style={{ fontSize: 13, color: C.textDim, marginBottom: 28 }}>
        Upload audio from iPhone Voice Memos, Plaud Note Pro, or any recording.
        Processing starts automatically.
      </p>

      {/* Drop zone */}
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => !uploading && fileInputRef.current?.click()}
        style={{
          border: `2px dashed ${dragOver ? C.accent : file ? C.success : C.border}`,
          borderRadius: 12,
          padding: file ? '24px' : '48px 24px',
          textAlign: 'center',
          cursor: uploading ? 'default' : 'pointer',
          background: dragOver ? `${C.accent}08` : file ? `${C.success}06` : 'transparent',
          transition: 'all 0.2s',
          marginBottom: 20,
        }}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED}
          onChange={(e) => handleFile(e.target.files?.[0])}
          style={{ display: 'none' }}
        />

        {file ? (
          <div>
            <div style={{ fontSize: 28, marginBottom: 8 }}>🎙️</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: C.text, marginBottom: 4 }}>
              {file.name}
            </div>
            <div style={{ fontSize: 12, color: C.textDim }}>
              {formatBytes(file.size)} · .{file.name.split('.').pop().toLowerCase()}
            </div>
            {!uploading && (
              <button onClick={(e) => { e.stopPropagation(); handleReset(); }}
                style={{ marginTop: 10, fontSize: 11, color: C.textDim, background: 'none',
                  border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>
                Change file
              </button>
            )}
          </div>
        ) : (
          <div>
            <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.5 }}>📁</div>
            <div style={{ fontSize: 14, color: C.text, marginBottom: 6 }}>
              Drop audio file here or tap to browse
            </div>
            <div style={{ fontSize: 11, color: C.textDim }}>
              m4a · mp3 · wav · flac · ogg · opus · webm — up to 200 MB
            </div>
          </div>
        )}
      </div>

      {/* Source selector + Note */}
      {file && !result && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: 'flex', gap: 12, marginBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <label style={{ fontSize: 12, color: C.textDim, display: 'block', marginBottom: 4 }}>
                Source
              </label>
              <div style={{ display: 'flex', gap: 6 }}>
                {[
                  { key: 'iphone', label: '📱 iPhone' },
                  { key: 'plaud', label: '🎤 Plaud' },
                  { key: 'other', label: '📎 Other' },
                ].map(s => (
                  <button key={s.key}
                    onClick={() => setSource(s.key)}
                    disabled={uploading}
                    style={{
                      flex: 1, padding: '8px 12px', borderRadius: 6, fontSize: 13,
                      border: `1px solid ${source === s.key ? C.accent : C.border}`,
                      background: source === s.key ? `${C.accent}18` : 'transparent',
                      color: source === s.key ? C.accent : C.text,
                      cursor: uploading ? 'default' : 'pointer',
                      fontWeight: source === s.key ? 600 : 400,
                    }}>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div>
            <label style={{ fontSize: 12, color: C.textDim, display: 'block', marginBottom: 4 }}>
              Note (optional)
            </label>
            <input
              type="text"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              disabled={uploading}
              placeholder="e.g. Lunch with Sarah, Team standup, Coffee with Heath..."
              style={{
                width: '100%', padding: '8px 12px', borderRadius: 6, fontSize: 13,
                border: `1px solid ${C.border}`, background: C.bg, color: C.text,
                outline: 'none', boxSizing: 'border-box',
              }}
            />
          </div>
        </div>
      )}

      {/* Progress bar */}
      {uploading && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 12, color: C.textDim }}>Uploading...</span>
            <span style={{ fontSize: 12, color: C.accent, fontWeight: 600 }}>{progress}%</span>
          </div>
          <div style={{
            height: 6, borderRadius: 3, background: `${C.border}`,
            overflow: 'hidden',
          }}>
            <div style={{
              width: `${progress}%`, height: '100%', borderRadius: 3,
              background: C.accent, transition: 'width 0.2s',
            }} />
          </div>
        </div>
      )}

      {/* Upload button */}
      {file && !result && (
        <button onClick={handleUpload} disabled={uploading}
          style={{
            width: '100%', padding: '12px', borderRadius: 8, fontSize: 15,
            fontWeight: 600, border: 'none', cursor: uploading ? 'default' : 'pointer',
            background: uploading ? C.textDim : C.accent, color: '#fff',
            opacity: uploading ? 0.7 : 1,
          }}>
          {uploading ? `Uploading... ${progress}%` : 'Upload & Process'}
        </button>
      )}

      {/* Error */}
      {error && (
        <div style={{
          marginTop: 16, padding: '12px 16px', borderRadius: 8,
          background: `${C.danger}12`, border: `1px solid ${C.danger}33`,
          color: C.danger, fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {/* Success */}
      {result && (
        <div style={{
          marginTop: 16, padding: '20px', borderRadius: 8,
          background: `${C.success}08`, border: `1px solid ${C.success}30`,
        }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: C.success, marginBottom: 8 }}>
            ✓ Upload complete
          </div>
          <div style={{ fontSize: 13, color: C.textDim, marginBottom: 4 }}>
            <strong style={{ color: C.text }}>{result.filename}</strong> · {formatBytes(result.size_bytes)} · {result.source}
          </div>
          <div style={{ fontSize: 12, color: C.textDim, marginBottom: 16 }}>
            Processing has started automatically. The recording will appear in Review
            once transcription and speaker identification are complete.
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={handleReset}
              style={{
                flex: 1, padding: '10px', borderRadius: 6, fontSize: 13, fontWeight: 500,
                border: `1px solid ${C.border}`, background: 'transparent',
                color: C.text, cursor: 'pointer',
              }}>
              Upload Another
            </button>
            <button onClick={() => navigate('/review')}
              style={{
                flex: 1, padding: '10px', borderRadius: 6, fontSize: 13, fontWeight: 500,
                border: 'none', background: C.accent, color: '#fff', cursor: 'pointer',
              }}>
              Go to Review →
            </button>
          </div>
        </div>
      )}

      {/* Recent uploads - show processing conversations */}
      <RecentUploads />
    </div>
  );
}


function RecentUploads() {
  const [convos, setConvos] = useState([]);
  const navigate = useNavigate();

  useState(() => {
    // Load recent conversations to show processing status
    api.conversations(10, 0).then(data => {
      const recent = (data.conversations || data || [])
        .filter(c => ['pending', 'transcribing', 'awaiting_speaker_review'].includes(c.processing_status))
        .slice(0, 5);
      setConvos(recent);
    }).catch(() => {});
  }, []);

  if (convos.length === 0) return null;

  const statusColors = {
    pending: C.textDim,
    transcribing: C.warning,
    awaiting_speaker_review: '#a78bfa',
  };

  const statusLabels = {
    pending: 'Pending',
    transcribing: 'Transcribing...',
    awaiting_speaker_review: 'Awaiting Speaker Review',
  };

  return (
    <div style={{ marginTop: 32 }}>
      <h2 style={{ fontSize: 14, fontWeight: 600, color: C.textDim, marginBottom: 10 }}>
        Processing
      </h2>
      {convos.map(c => (
        <div key={c.id}
          onClick={() => {
            if (c.processing_status === 'awaiting_speaker_review') {
              navigate(`/review/${c.id}/speakers`);
            } else {
              navigate(`/review/${c.id}`);
            }
          }}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '10px 14px', borderRadius: 6, marginBottom: 6, cursor: 'pointer',
            background: C.card, border: `1px solid ${C.border}`,
          }}>
          <div>
            <div style={{ fontSize: 13, color: C.text, fontWeight: 500 }}>
              {c.manual_note || c.title || c.source + ' recording'}
            </div>
            <div style={{ fontSize: 11, color: C.textDim }}>{c.source}</div>
          </div>
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 4,
            color: statusColors[c.processing_status] || C.textDim,
            border: `1px solid ${(statusColors[c.processing_status] || C.textDim) + '44'}`,
          }}>
            {statusLabels[c.processing_status] || c.processing_status}
          </span>
        </div>
      ))}
    </div>
  );
}
